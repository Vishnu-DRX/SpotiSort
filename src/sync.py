"""Sync entrypoint: `python -m src.sync` (dry-run by default).

Dry-run by default. ``--apply`` runs the guarded add -> verify -> journal -> remove -> reconcile flow in apply.py;
it needs a selector (--newest / --only-uris) and honours --max-moves.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from .config import ConfigError, load_config
from .enrich import build_language_map
from .enrichment.cache import DEFAULT_PATH, EnrichmentCache
from .enrichment.enricher import Enricher
from .enrichment.musicbrainz import MusicBrainz
from dataclasses import replace

from . import artifacts
from .planner import Plan, build_plan, targets_needed
from .signals import gate, load_precision
from .apply import DEFAULT_MAX_MOVES, HARD_MAX_MOVES, EXIT_TOO_MANY, TooManyMoves, apply_moves, load_journal, restore_from_log
from .spotify_client import SpotifyClient, SpotifyError, load_env, validate_track_uris

SAVE_EVERY = 25


class AuditSession(requests.Session):
    """requests.Session that records a (method, host) histogram of every HTTP call."""

    def __init__(self) -> None:
        super().__init__()
        self.audit: Counter[str] = Counter()

    def request(self, method, url, *args, **kwargs):  # noqa: D401
        self.audit[f"{method.upper()} {urlparse(url).netloc}"] += 1
        return super().request(method, url, *args, **kwargs)

    def write_calls_to_api(self) -> int:
        return sum(n for k, n in self.audit.items() if k.split()[0] != "GET" and k.endswith("api.spotify.com"))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m src.sync",
        description="Sort aged Liked Songs into existing playlists by rules. Dry-run is the default.",
    )
    p.add_argument("--apply", action="store_true", help="perform writes (guarded; needs a selector)")
    p.add_argument("--max-moves", type=int, default=DEFAULT_MAX_MOVES, help="abort if the plan has more moves (default 50)")
    p.add_argument("--newest", type=int, default=None, help="only consider the N newest liked songs")
    p.add_argument("--only-uris", default=None, help="only these spotify:track: URIs (comma list, or @file)")
    p.add_argument("--allow-unselected", action="store_true", help="scheduled runs only: apply without a selector (still capped by --max-moves)")
    p.add_argument("--restore", default=None, metavar="LOG", help="re-add a run's journaled songs to Liked Songs (preview unless --apply)")
    p.add_argument("--remove-from-target", action="store_true", help="with --restore --apply: also remove them from the playlist they were moved to")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--env", default=".env")
    p.add_argument("--cache", default=str(DEFAULT_PATH))
    p.add_argument("--logs-dir", default="logs")
    p.add_argument("--limit", type=int, default=None, help="plan at most N moves (oldest liked first)")
    p.add_argument("--since", default=None, help="only consider songs liked on/after YYYY-MM-DD")
    p.add_argument("--rule", default=None, help="only plan moves for the rule with this name")
    p.add_argument("--titles", choices=("auto", "always", "never"), default="auto",
                   help="song titles in written logs: auto = follow logging.include_track_names on a committed "
                        "workflow run (SPOTISORT_COMMITTED_RUN=1), always visible on an ordinary local run")
    p.add_argument("--cron", default=os.environ.get("SPOTISORT_CRON"), help="cron of the schedule, shown on the dashboard Overview")
    p.add_argument("--what-if-enable-all", action="store_true", help="preview: treat disabled rules as enabled (dry-run only)")
    p.add_argument("--no-network", action="store_true", help="do not call MusicBrainz (cache + local signals only)")
    return p.parse_args(argv)


def build_log(plan: Plan, dry_run: bool, audit: dict[str, int], now: datetime, runtime_s: float) -> dict[str, Any]:
    journal = [
        {
            "uri": m["uri"], "name": m["track"], "artists": m["artist"],
            "original_added_at": m["original_added_at"], "target_playlist_id": m["playlist_id"],
        }
        for m in plan.moves
    ]
    return {
        "date": now.date().isoformat(),
        "dry_run": dry_run,
        "evaluated": plan.evaluated,
        "moved": plan.moves,
        "skipped_no_match": plan.skipped_no_match,
        "skipped_too_young": plan.skipped_too_young,
        "skipped_playlist_missing": plan.skipped_playlist_missing,
        "errors": [],
        "warnings": plan.warnings,
        "journal": journal,  # dry-run: the entries that WOULD be journalled before any removal
        "http_audit": dict(audit),
        "runtime_seconds": round(runtime_s, 1),
    }


def log_path(logs_dir: Path, now: datetime, mode: str) -> Path:
    """logs/YYYY-MM-DD.json; an apply log is never overwritten (later runs get -2, -3...) and a dry run never
    overwrites an apply log (it goes to -dryrun), because the apply log holds the restore journal."""
    base = logs_dir / f"{now.date().isoformat()}.json"
    if mode == "apply":
        cand, n = base, 1
        while cand.exists():
            n += 1
            cand = logs_dir / f"{now.date().isoformat()}-{n}.json"
        return cand
    try:
        if base.exists() and json.loads(base.read_text(encoding="utf-8")).get("mode") == "apply":
            return logs_dir / f"{now.date().isoformat()}-dryrun.json"
    except (OSError, ValueError):
        pass
    return base


def select_tracks(tracks: list, newest: int | None, only_uris: set[str] | None) -> list:
    """Restrict the songs a run may touch (master decision 12): the N newest liked and/or an explicit URI set."""
    out = list(tracks)
    if only_uris is not None:
        out = [t for t in out if t.uri in only_uris]
    if newest is not None:
        out = sorted(out, key=lambda t: (t.added_at is not None, t.added_at), reverse=True)[:max(newest, 0)]
    return out


def parse_only_uris(value: str | None) -> set[str] | None:
    if not value:
        return None
    raw = Path(value[1:]).read_text(encoding="utf-8").split() if value.startswith("@") else value.split(",")
    uris = {u.strip() for u in raw if u.strip()}
    validate_track_uris(uris)
    return uris


def check_apply_guards(args: argparse.Namespace) -> str | None:
    """Return an error message if --apply was requested without the required safety selectors."""
    if not args.apply:
        return None
    if args.what_if_enable_all:
        return "--what-if-enable-all is a preview and cannot be combined with --apply"
    if not (args.newest or args.only_uris or args.allow_unselected or args.restore):
        return ("--apply needs a selector: --only-uris, --newest N, or (scheduled runs only) --allow-unselected. "
                "It will never touch the whole library by default.")
    if args.max_moves < 1 or args.max_moves > HARD_MAX_MOVES:
        return f"--max-moves must be between 1 and {HARD_MAX_MOVES}"
    if args.newest is not None and args.newest < 1:
        return "--newest must be >= 1"
    return None


def hide_titles(args: argparse.Namespace, config) -> bool:
    """Committed logs stay private-by-default: titles are written only if the config opts in.

    Deliberately does NOT key off the ambient ``GITHUB_ACTIONS`` variable, which GitHub sets on every step of
    every workflow (including a plain ``pytest`` job) and would silently redact titles in unrelated test runs.
    Only the sync workflow's own commit-producing step sets ``SPOTISORT_COMMITTED_RUN``.
    """
    if args.titles == "always":
        return False
    if args.titles == "never":
        return True
    return bool(os.environ.get("SPOTISORT_COMMITTED_RUN")) and not config.include_track_names


def run(args: argparse.Namespace) -> int:
    problem = check_apply_guards(args)
    if problem:
        print(f"error: {problem}", file=sys.stderr)
        return 2
    started = time.monotonic()
    load_env(args.env)
    logs_dir = Path(args.logs_dir)
    if args.restore:
        return run_restore(args, logs_dir, started)
    try:
        config = load_config(args.config)
        since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc) if args.since else None
        only_uris = parse_only_uris(args.only_uris)
    except (ConfigError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    session = AuditSession()
    client = SpotifyClient.from_env(dry_run=not args.apply, session=session)
    now = datetime.now(timezone.utc)
    mode = "apply" if args.apply else "dry_run"

    all_tracks = list(client.iter_saved_tracks())
    liked_uris_before = {t.uri for t in all_tracks}
    tracks = select_tracks(all_tracks, args.newest, only_uris)
    playlists = list(client.iter_my_playlists())
    lmap, lang_warnings, _ = build_language_map(client, config, playlists)

    cache = EnrichmentCache(args.cache)
    mb = MusicBrainz() if (config.musicbrainz and not args.no_network) else None
    enricher = Enricher(cache, mb, lmap, config.english_default)
    enrichments = {}
    saved_at = 0
    for t in tracks:
        enrichments[t.id] = enricher.resolve(t)
        if mb and mb.requests_made - saved_at >= SAVE_EVERY:
            cache.save()
            saved_at = mb.requests_made
    if cache.dirty:
        cache.save()

    precision = load_precision(logs_dir / "signal-precision.json")
    raw_enrichments = enrichments
    enrichments = {tid: gate(e, precision)[0] for tid, e in raw_enrichments.items()}  # only qualified signals drive rules
    cfg_text = Path(args.config).read_text(encoding="utf-8")
    if args.what_if_enable_all:
        config = replace(config, rules=tuple(replace(r, enabled=True) for r in config.rules))

    needed = targets_needed(tracks, enrichments, config, now, playlists, args.rule)
    membership = {pid: {t.uri for t in client.iter_playlist_items(pid)} for pid in needed}

    plan = build_plan(
        tracks, enrichments, config, now, playlists, membership,
        only_rule=args.rule, since=since, limit=args.limit,
    )
    plan.warnings = lang_warnings + plan.warnings
    if enricher.errors:
        plan.warnings.append(f"{enricher.errors} MusicBrainz lookup(s) failed; those artists have no genre this run")

    run_id = now.strftime("%Y%m%dT%H%M%SZ")
    snapshot = artifacts.build_latest_plan(
        tracks, raw_enrichments, config, now, playlists, precision=precision, run_id=run_id, mode=mode,
        what_if=args.what_if_enable_all, cfg_hash=artifacts.config_hash(cfg_text),
    )
    rule_counts = {r["name"]: r["wins"] for r in snapshot["rules"]}
    logs_dir.mkdir(parents=True, exist_ok=True)
    out = log_path(logs_dir, now, mode)

    def base_log(duration: float, dry: bool) -> dict[str, Any]:
        log = build_log(plan, dry, session.audit, now, duration)
        log.update({
            "run_id": run_id, "mode": mode, "what_if": args.what_if_enable_all,
            "liked_before": len(liked_uris_before), "liked_after": len(liked_uris_before),
            "verdict": "dry_run" if dry else "in_progress", "rule_counts": rule_counts,
            "config_hash": snapshot["config_hash"], "plan_counts": snapshot["counts"],
        })
        return log

    result = None
    moved = 0
    exit_code = 0
    if args.apply:
        def write_journal(journal: list[dict[str, Any]]) -> None:  # runs BEFORE any removal from Liked Songs
            log = base_log(time.monotonic() - started, False)
            log["journal"] = journal
            artifacts.atomic_write_json(out, log)

        try:
            result = apply_moves(
                client, plan.moves, liked_uris_before=liked_uris_before, write_journal=write_journal,
                max_moves=args.max_moves,
            )
        except TooManyMoves as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_TOO_MANY
        moved = len(result.removed)
        exit_code = result.exit_code
    elif session.write_calls_to_api():  # cannot happen (client refuses), but verify rather than assume
        print("FATAL: a write call reached the Spotify API during a dry run", file=sys.stderr)
        return 3

    duration = time.monotonic() - started
    log = base_log(duration, not args.apply)
    liked_after = len(liked_uris_before)
    if result is not None:
        liked_after = result.liked_after if result.liked_after is not None else len(liked_uris_before)
        log.update({
            "journal": result.journal, "errors": result.errors, "warnings": plan.warnings + result.warnings,
            "batches": result.batches, "reconcile": result.reconcile, "liked_after": liked_after,
            "moved_uris": result.removed, "still_liked": result.still_liked,
            "restore_command": f"python -m src.sync --restore {out.as_posix()} --apply",
            "verdict": "ok" if result.ok else ("mismatch" if result.reconcile and not result.reconcile.get("ok") else "error"),
        })
    hide = hide_titles(args, config)
    artifacts.atomic_write_json(out, artifacts.redact_log(log) if hide else log)
    artifacts.atomic_write_json(logs_dir / "latest-plan.json", artifacts.redact_plan(snapshot) if hide else snapshot)
    artifacts.update_runs_index(
        logs_dir / "runs.json",
        artifacts.run_entry(
            run_id=run_id, now=now, mode=mode, plan_counts=snapshot["counts"], moved=moved, errors=len(log["errors"]),
            warnings=len(log["warnings"]), liked_before=len(liked_uris_before), liked_after=liked_after,
            duration_s=duration, rule_counts=rule_counts, log_file=out.name, what_if=args.what_if_enable_all,
            reconcile_ok=(result.reconcile.get("ok") if result and result.reconcile else None),
            moves_by_playlist=dict(Counter(m["playlist"] for m in plan.moves if m["uri"] in (set(result.removed) if result else {m["uri"] for m in plan.moves}))),
        ),
        now,
        schedule=artifacts.schedule_info(args.cron, now),
    )
    print_summary(plan, out, applied=result)
    return exit_code


def run_restore(args: argparse.Namespace, logs_dir: Path, started: float) -> int:
    """`--restore LOG`: re-add journaled songs to Liked Songs. Preview unless --apply is also given."""
    try:
        journal = load_journal(args.restore)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"restore: {len(journal)} journaled song(s) in {args.restore}")
    if not args.apply:
        print("DRY RUN: nothing was changed. Add --apply to re-add them to Liked Songs "
              "(their added_at resets to now; --remove-from-target also removes them from their playlist).")
        return 0
    client = SpotifyClient.from_env(dry_run=False)
    res = restore_from_log(client, args.restore, remove_from_targets=args.remove_from_target)
    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%SZ")
    logs_dir.mkdir(parents=True, exist_ok=True)
    out = logs_dir / f"{now.date().isoformat()}-restore.json"
    artifacts.atomic_write_json(out, {
        "date": now.date().isoformat(), "run_id": run_id, "mode": "restore", "source_log": Path(args.restore).name,
        "restored_now_liked": res.confirmed, "errors": res.errors, "batches": res.batches,
        "liked_before": res.liked_before, "liked_after": res.liked_after,
        "verdict": "ok" if res.ok else "error",
    })
    print(f"restored: {len(res.confirmed)} now liked; errors: {len(res.errors)}; log: {out}")
    return res.exit_code


def print_summary(plan: Plan, out: Path, applied=None) -> None:
    if applied is None:
        print(f"DRY RUN: evaluated {plan.evaluated} liked songs; no writes performed.")
    else:
        print(f"APPLIED: evaluated {plan.evaluated} liked songs; moved {len(applied.removed)}, "
              f"confirmed in playlists {len(applied.confirmed)}, errors {len(applied.errors)}.")
    print(f"  would move: {len(plan.moves)}   too young: {len(plan.skipped_too_young)}   "
          f"no rule matched: {plan.skipped_no_match}   target problems: {len(plan.skipped_playlist_missing)}")
    per_pl = Counter(m["playlist"] for m in plan.moves)
    for name, n in per_pl.most_common():
        print(f"    -> {name}: {n}")
    for w in plan.warnings:
        print(f"  warning: {w}")
    print(f"log: {out}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run(args)
    except (SpotifyError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
