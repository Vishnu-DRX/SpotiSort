"""Backtest: `python -m src.backtest` (read-only).

Simulates an inbox from the user's owned/collaborative playlists: every track's true home(s) = the playlist(s) it is in.
Runs the real rules engine with the given config (age ignored) and reports per-playlist precision/recall and the top
confusions, plus per-signal language precision measured against the language playlists in the config.

Outputs (counts only, safe to commit):  logs/backtest.json, logs/signal-precision.json
Outputs (names, git-ignored):           logs/backtest-detail.json, logs/backtest-detail.md

Caveats (also in the report): playlist membership is a proxy for "true home" (a track can fit several playlists);
the playlist language signal is measured leave-one-out; signal precision is estimated only on tracks that sit in a
mapped language playlist, so languages without a mapped playlist cannot be measured.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import artifacts
from .config import ConfigError, load_config
from .enrichment.cache import DEFAULT_PATH, EnrichmentCache
from .enrichment.enricher import Enricher
from .enrichment.musicbrainz import MusicBrainz
from .enrichment.playlist_language import LanguageMap
from .models import Config, Enrichment, Playlist, Track
from .planner import resolve_target
from .rules_engine import first_match
from .signals import MIN_PRECISION, MIN_SAMPLES, TRUSTED_BY_DESIGN, gate, qualified_map
from .spotify_client import SpotifyClient, SpotifyError, load_env

SIGNALS = ("playlist", "script", "hint", "country_default")
TEST_PLAYLIST = "spotisort test"


def _ratio(a: int, b: int) -> float | None:
    return round(a / b, 4) if b else None


def signal_precision(
    candidates: Mapping[str, Mapping[str, str | None]], truth_language: Mapping[str, str]
) -> dict[str, dict[str, dict[str, Any]]]:
    """Per signal, per language: truth / predicted / correct / precision / recall over language-labelled tracks."""
    out: dict[str, dict[str, dict[str, Any]]] = {s: {} for s in SIGNALS}
    truth_counts = Counter(truth_language.values())
    for sig in SIGNALS:
        predicted: Counter[str] = Counter()
        correct: Counter[str] = Counter()
        for tid, truth in truth_language.items():
            said = (candidates.get(tid) or {}).get(sig)
            if said:
                predicted[said] += 1
                if said == truth:
                    correct[said] += 1
        for lang in set(truth_counts) | set(predicted):
            out[sig][lang] = {
                "truth": truth_counts.get(lang, 0),
                "predicted": predicted.get(lang, 0),
                "correct": correct.get(lang, 0),
                "precision": _ratio(correct.get(lang, 0), predicted.get(lang, 0)),
                "recall": _ratio(correct.get(lang, 0), truth_counts.get(lang, 0)),
            }
    return out


def routing_metrics(
    tracks: Sequence[Track],
    truth: Mapping[str, set[str]],
    enrichments: Mapping[str, Enrichment],
    config: Config,
    playlists: Sequence[Playlist],
    now: datetime,
) -> dict[str, Any]:
    """Run the real first-match logic (age ignored) and compare to true homes. Keys are playlist ids."""
    pred_by_pl: Counter[str] = Counter()
    tp_by_pl: Counter[str] = Counter()
    truth_by_pl: Counter[str] = Counter()
    unrouted_by_pl: Counter[str] = Counter()
    confusion: Counter[tuple[str, str]] = Counter()
    rule_pred: Counter[str] = Counter()
    rule_ok: Counter[str] = Counter()
    misroutes: list[dict[str, Any]] = []
    routed = correct = unrouted = 0
    for t in tracks:
        homes = truth.get(t.id, set())
        for h in homes:
            truth_by_pl[h] += 1
        m = first_match(t, enrichments.get(t.id), config.rules, now, config.default_days_threshold)
        target, _, _ = resolve_target(m.rule.target_playlist, playlists) if m else (None, None, None)
        if m is None or target is None:
            unrouted += 1
            for h in homes:
                unrouted_by_pl[h] += 1
            continue
        routed += 1
        pred_by_pl[target.id] += 1
        rule_pred[m.rule.name] += 1
        if target.id in homes:
            correct += 1
            tp_by_pl[target.id] += 1
            rule_ok[m.rule.name] += 1
        else:
            for h in homes:
                confusion[(h, target.id)] += 1
            misroutes.append({"track": t, "predicted": target.id, "homes": sorted(homes), "rule": m.rule.name})
    return {
        "pred_by_pl": pred_by_pl, "tp_by_pl": tp_by_pl, "truth_by_pl": truth_by_pl, "unrouted_by_pl": unrouted_by_pl,
        "confusion": confusion, "rule_pred": rule_pred, "rule_ok": rule_ok, "misroutes": misroutes,
        "routed": routed, "correct": correct, "unrouted": unrouted,
    }


def build_reports(
    *,
    tracks: Sequence[Track],
    truth: Mapping[str, set[str]],
    playlists: Sequence[Playlist],
    names: Mapping[str, str],
    config: Config,
    metrics: Mapping[str, Any],
    precision: Mapping[str, Any],
    all_rules_enabled: bool,
    cfg_hash: str,
    now: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """(counts-only report, detail report with names). Playlist labels P01.. by name order, rules R01.. by file order."""
    pl_ids = sorted(names, key=lambda i: names[i].casefold())
    label = {pid: f"P{n + 1:02d}" for n, pid in enumerate(pl_ids)}
    rule_label = {r.name: f"R{n + 1:02d}" for n, r in enumerate(config.rules)}

    pl_rows = []
    for pid in pl_ids:
        pred, tp, tr = metrics["pred_by_pl"][pid], metrics["tp_by_pl"][pid], metrics["truth_by_pl"][pid]
        pl_rows.append({
            "id": label[pid], "tracks": tr, "predicted": pred, "tp": tp,
            "precision": _ratio(tp, pred), "recall": _ratio(tp, tr), "unrouted": metrics["unrouted_by_pl"][pid],
        })
    conf_rows = [
        {"true": label[a], "predicted": label[b], "count": n}
        for (a, b), n in sorted(metrics["confusion"].items(), key=lambda kv: -kv[1])[:50]
    ]
    rule_rows = [
        {"name_id": rule_label[r.name], "predicted": metrics["rule_pred"][r.name], "correct": metrics["rule_ok"][r.name],
         "precision": _ratio(metrics["rule_ok"][r.name], metrics["rule_pred"][r.name])}
        for r in config.rules
    ]
    n = len(tracks)
    report = {
        "version": 1,
        "generated_at": artifacts.iso(now),
        "config_hash": cfg_hash,
        "all_rules_enabled": all_rules_enabled,
        "inbox": {"tracks": n, "playlists": len(pl_ids)},
        "playlists": pl_rows,
        "confusions": conf_rows,
        "totals": {
            "tracks": n, "routed": metrics["routed"], "correct": metrics["correct"],
            "misrouted": metrics["routed"] - metrics["correct"], "unrouted": metrics["unrouted"],
            "precision": _ratio(metrics["correct"], metrics["routed"]),
            "recall": _ratio(metrics["correct"], n),
        },
        "rules": rule_rows,
        "caveats": [
            "true home = playlist membership (a song can fit several playlists)",
            "playlist language signal is leave-one-out",
            "signal precision is measured only on tracks inside mapped language playlists",
        ],
    }
    mis = []
    for m in metrics["misroutes"][:200]:
        t: Track = m["track"]
        mis.append({
            "title": t.name, "artists": [a.name for a in t.artists],
            "true": [names[h] for h in m["homes"]], "predicted": names[m["predicted"]], "rule": m["rule"],
        })
    detail = {
        **report,
        "playlists": [{**row, "name": names[pid]} for row, pid in zip(pl_rows, pl_ids)],
        "rules": [{**row, "name": r.name} for row, r in zip(rule_rows, config.rules)],
        "confusions": [
            {"true": names[a], "predicted": names[b], "count": c}
            for (a, b), c in sorted(metrics["confusion"].items(), key=lambda kv: -kv[1])[:50]
        ],
        "top_misroutes": mis,
    }
    return report, detail


def build_signal_report(precision: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    doc = {"version": 1, "generated_at": artifacts.iso(now), "min_precision": MIN_PRECISION, "min_samples": MIN_SAMPLES,
           "trusted_by_design": sorted(TRUSTED_BY_DESIGN), "by_signal": precision}
    doc["qualified"] = qualified_map(doc)
    return doc


def render_markdown(detail: Mapping[str, Any], signals: Mapping[str, Any]) -> str:
    t = detail["totals"]
    lines = [
        "# Backtest detail (local only; contains playlist and song names)", "",
        f"Generated {detail['generated_at']} · {detail['inbox']['tracks']} tracks from {detail['inbox']['playlists']} playlists · "
        f"all rules enabled: {detail['all_rules_enabled']}", "",
        f"**Totals:** routed {t['routed']}, correct {t['correct']}, misrouted {t['misrouted']}, unrouted {t['unrouted']}, "
        f"precision {t['precision']}, recall {t['recall']}", "",
        "## Per playlist", "", "| playlist | tracks | predicted | tp | precision | recall | unrouted |", "|---|---|---|---|---|---|---|",
    ]
    for p in detail["playlists"]:
        lines.append(f"| {p['name']} | {p['tracks']} | {p['predicted']} | {p['tp']} | {p['precision']} | {p['recall']} | {p['unrouted']} |")
    lines += ["", "## Per rule", "", "| rule | predicted | correct | precision |", "|---|---|---|---|"]
    for r in detail["rules"]:
        lines.append(f"| {r['name']} | {r['predicted']} | {r['correct']} | {r['precision']} |")
    lines += ["", "## Top confusions (true -> predicted)", ""]
    lines += [f"- {c['true']} -> {c['predicted']}: {c['count']}" for c in detail["confusions"][:15]]
    lines += ["", "## Sample misroutes", ""]
    lines += [f"- {m['title']} - {', '.join(m['artists'])}: in {', '.join(m['true'])}, predicted {m['predicted']} (rule {m['rule']})"
              for m in detail["top_misroutes"][:25]]
    lines += ["", "## Language signal precision (qualified = may drive rules)", ""]
    for lang, ok in signals["qualified"].items():
        lines.append(f"- {lang}: qualified signals = {ok or 'none'}")
    for sig, per in signals["by_signal"].items():
        for lang, s in sorted(per.items()):
            lines.append(f"  - {sig}/{lang}: predicted {s['predicted']}, correct {s['correct']}, precision {s['precision']}, recall {s['recall']}")
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> int:
    load_env(args.env)
    try:
        config = load_config(args.config)
        cfg_text = Path(args.config).read_text(encoding="utf-8")
    except (ConfigError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.all_rules:
        config = replace(config, rules=tuple(replace(r, enabled=True) for r in config.rules))

    client = SpotifyClient.from_env(dry_run=True)  # read-only by construction
    playlists = list(client.iter_my_playlists())
    usable = [p for p in playlists if p.usable and p.name.casefold() != TEST_PLAYLIST]
    truth: dict[str, set[str]] = defaultdict(set)
    by_id: dict[str, Track] = {}
    names: dict[str, str] = {}
    lang_of_playlist: dict[str, str] = {}
    lang_by_name = {k.casefold().strip(): v for k, v in config.language_playlists.items()}
    for pl in usable:
        items = list(client.iter_playlist_items(pl.id))
        if not items:
            continue
        names[pl.id] = pl.name
        if pl.name.casefold().strip() in lang_by_name:
            lang_of_playlist[pl.id] = lang_by_name[pl.name.casefold().strip()]
        for t in items:
            by_id.setdefault(t.id, t)
            truth[t.id].add(pl.id)
        print(f"  read {len(items):4d} tracks", file=sys.stderr)
    tracks = list(by_id.values())
    print(f"{len(tracks)} unique tracks from {len(names)} playlists", file=sys.stderr)

    lmap = LanguageMap()
    for pl in usable:
        if pl.id in lang_of_playlist:
            lmap.add_playlist([t for t in tracks if pl.id in truth[t.id]], lang_of_playlist[pl.id])

    cache = EnrichmentCache(args.cache)
    mb = MusicBrainz() if (config.musicbrainz and not args.no_network) else None
    enricher = Enricher(cache, mb, lmap, config.english_default)
    raw: dict[str, Enrichment] = {}
    cands: dict[str, dict[str, str | None]] = {}
    for i, t in enumerate(tracks, 1):
        raw[t.id] = enricher.resolve(t, exclude_own_playlist_vote=True)
        cands[t.id] = enricher.signal_candidates(t, loo=True)
        if mb and mb.requests_made and i % 25 == 0 and cache.dirty:
            cache.save()
        if i % 100 == 0:
            print(f"  enriched {i}/{len(tracks)} (musicbrainz requests {mb.requests_made if mb else 0})", file=sys.stderr)
    if cache.dirty:
        cache.save()

    # ground-truth language: a track inside exactly one distinct mapped language
    truth_language: dict[str, str] = {}
    for tid, homes in truth.items():
        langs = {lang_of_playlist[h] for h in homes if h in lang_of_playlist}
        if len(langs) == 1:
            truth_language[tid] = next(iter(langs))
    now = datetime.now(timezone.utc)
    sig = build_signal_report(signal_precision(cands, truth_language), now)
    gated = {tid: gate(e, sig)[0] for tid, e in raw.items()}

    metrics = routing_metrics(tracks, truth, gated, config, playlists, now)
    report, detail = build_reports(
        tracks=tracks, truth=truth, playlists=playlists, names=names, config=config, metrics=metrics,
        precision=sig, all_rules_enabled=args.all_rules, cfg_hash=artifacts.config_hash(cfg_text), now=now,
    )
    out = Path(args.out)
    artifacts.atomic_write_json(out / "backtest.json", report)
    artifacts.atomic_write_json(out / "signal-precision.json", sig)
    artifacts.atomic_write_json(out / "backtest-detail.json", detail)
    (out / "backtest-detail.md").write_text(render_markdown(detail, sig), encoding="utf-8")

    t = report["totals"]
    print(f"backtest: {t['tracks']} tracks | routed {t['routed']} | correct {t['correct']} | misrouted {t['misrouted']} | "
          f"unrouted {t['unrouted']} | precision {t['precision']} | recall {t['recall']}")
    print("qualified language signals:", {k: v for k, v in sig["qualified"].items()})
    print(f"wrote {out}/backtest.json, signal-precision.json (counts) and backtest-detail.* (names, git-ignored)")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m src.backtest", description=__doc__.split("\n")[0])
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--env", default=".env")
    p.add_argument("--cache", default=str(DEFAULT_PATH))
    p.add_argument("--out", default="logs")
    p.add_argument("--all-rules", action="store_true", help="treat disabled rules as enabled (evaluate draft rules)")
    p.add_argument("--no-network", action="store_true", help="do not call MusicBrainz (cache + local signals only)")
    args = p.parse_args(argv)
    try:
        return run(args)
    except (SpotifyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
