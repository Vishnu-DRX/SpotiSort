"""Generate the dashboard demo fixtures: `python scripts/make_dashboard_fixtures.py [out_dir]`.

Writes docs/dashboard/fixtures/*.json. The plan / run entries / runs index are produced by the REAL builders in
``src.artifacts`` from fabricated tracks, playlists and config (obviously fake artists and titles); the rest
(per-run logs, coverage, precision, backtest) is hand-built to the shapes in docs/dashboard/DATA.md.
Everything uses fixed timestamps, so regenerating is byte-for-byte reproducible (tests rely on it).
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.artifacts import (  # noqa: E402
    atomic_write_json,
    build_latest_plan,
    config_hash,
    run_entry,
    schedule_info,
    update_runs_index,
)
from src.models import Artist, Config, Enrichment, Playlist, Rule, Track  # noqa: E402
from src.signals import qualified_map  # noqa: E402

DEFAULT_OUT = ROOT / "docs" / "dashboard" / "fixtures"
NOW = datetime(2026, 9, 21, 6, 0, 0, tzinfo=timezone.utc)
CONFIG_TEXT = "fixture-config-v1"

# ----------------------------------------------------------------------------- fabricated inbox
# (title, artists, genres, language, lang_source, lang_conf, release_date, age_days, explicit)
_S = [
    # Malayalam (playlist / script tiers)
    ("Fake Ponnonam", ["Mala Fakeri"], ["filmi"], "malayalam", "playlist", 0.98, "2019-08-01", 40, False),
    ("Kadalinte Sample", ["Mala Fakeri"], [], "malayalam", "script", 0.9, "2021-02-11", 20, False),
    ("Nilavu Placeholder", ["Vayali Test"], [], "malayalam", "playlist", 0.97, "2023-05-05", 3, False),
    ("Mazha Fixture", ["Vayali Test"], ["filmi"], "malayalam", "script", 0.9, "2022-07-07", 9, False),
    # Hindi
    ("Fake Dil", ["Pyaar Placeholder"], ["bollywood"], "hindi", "playlist", 0.99, "2018-01-01", 60, False),
    ("Placeholder Pyaar", ["Pyaar Placeholder", "DJ Sample"], ["bollywood"], "hindi", "playlist", 0.98, "2020-03-03", 25, False),
    ("Sample Sitara", ["Tara Testani"], [], "hindi", "script", 0.9, "2024-01-20", 16, False),
    ("Test Tara", ["Tara Testani"], [], "hindi", "playlist", 0.96, "2025-11-11", 5, False),
    # Bengali -> ambiguous target; Tamil (playlist) -> not writable target
    ("Fake Nodi", ["Sur Mockjee"], [], "bengali", "script", 0.9, "2017-06-06", 30, False),
    ("Sample Kaatru", ["Isai Fakeman"], ["kollywood"], "tamil", "playlist", 0.97, "2022-09-09", 33, False),
    # Weak signals that fail the 90% bar -> blocked (below_90_percent, unmeasured)
    ("Fake Thendral", ["Isai Fakeman"], [], "tamil", "hint", 0.58, "2021-04-04", 22, False),
    ("Sample Ragam", ["Raga Placeholder"], [], "telugu", "hint", 0.5, "2020-10-10", 12, False),
    # Spanish via a hint that DOES qualify
    ("Noche Falsa", ["La Banda Ejemplo"], ["latin pop"], "spanish", "hint", 0.93, "2022-12-12", 30, False),
    ("Baila Ejemplo", ["La Banda Ejemplo"], ["latin pop"], "spanish", "hint", 0.9, "2025-02-02", 4, False),
    # Rock legends (top position, 21-day threshold) and the shadowed "live" rule
    ("Fake Anthem", ["Fake Band Alpha"], ["rock"], "english", "country_default", 0.7, "2015-05-05", 50, False),
    ("Fake Anthem (Live)", ["Fake Band Alpha"], ["rock"], "english", "country_default", 0.7, "2016-06-06", 45, False),
    ("Sample Ballad", ["Fake Band Beta"], ["rock", "soft rock"], "english", "country_default", 0.7, "2012-04-04", 30, False),
    ("Sample Ballad II", ["Fake Band Beta"], ["rock"], "english", "country_default", 0.7, "2013-03-03", 10, False),
    ("Test Riff", ["Fake Band Alpha", "DJ Sample"], ["rock"], "english", "country_default", 0.7, "2014-01-01", 21.5, True),
    # Lo-fi
    ("Nameless Loop 01", ["Beats Not Real"], ["lo-fi", "chillhop"], None, None, None, "2023-01-01", 15, False),
    ("Nameless Loop 02", ["Beats Not Real"], ["lo-fi"], None, None, None, "2023-02-01", 40, False),
    ("Nameless Loop 03", ["Beats Not Real"], ["lo-fi hip hop"], None, None, None, "2023-03-01", 90, False),
    ("Nameless Loop 04", ["Beats Not Real"], ["lo-fi"], None, None, None, "2023-04-01", 200, False),
    ("Nameless Loop 05", ["Beats Not Real"], ["lo-fi"], None, None, None, "2026-08-01", 6, False),
    # Old jazz -> target playlist missing
    ("Pretend Blues", ["Quartet Nowhere"], ["jazz", "blues"], None, None, None, "1965-01-01", 100, False),
    ("Fake Swing", ["Quartet Nowhere"], ["jazz", "swing"], None, None, None, "1958-01-01", 35, False),
    ("Modern Fake Jazz", ["Quartet Nowhere"], ["jazz"], "english", "country_default", 0.7, "2015-01-01", 60, False),
    # English pop (country_default tier, qualified)
    ("Placeholder Love", ["Sample Singer"], ["pop"], "english", "country_default", 0.7, "2022-01-01", 18, False),
    ("Lorem Ipsum Night", ["Sample Singer"], ["pop"], "english", "country_default", 0.7, "2022-02-01", 70, False),
    ("Dummy Hearts", ["Faux Star"], ["pop", "dance pop"], "english", "country_default", 0.7, "2024-05-01", 44, True),
    ("Example Summer", ["Faux Star"], ["pop"], "english", "country_default", 0.7, "2024-06-01", 16, False),
    ("Mock Midnight", ["Test Tones"], ["synth-pop"], "english", "country_default", 0.7, "2021-09-09", 120, False),
    ("Fixture Sunrise", ["Test Tones"], ["synth-pop"], "english", "country_default", 0.7, "2021-10-10", 8, False),
    ("Stand-In Song", ["Sample Singer"], ["pop"], "english", "country_default", 0.7, "2020-08-08", 14.5, False),
    # No match: unknown language and/or genre, or languages without a rule
    ("Untitled Demo 01", ["Anon Artist"], [], None, None, None, "2026-01-01", 33, False),
    ("Untitled Demo 02", ["Anon Artist"], ["ambient"], None, None, None, "2026-02-01", 47, False),
    ("Untitled Demo 03", ["Anon Artist"], [], None, None, None, "2026-03-01", 2, False),
    ("Sakura Placeholder", ["Nihon Sample"], ["j-pop"], "japanese", "script", 0.95, "2023-03-03", 55, False),
    ("Annyeong Fixture", ["K Sample"], ["k-pop"], "korean", "hint", 0.85, "2024-04-04", 26, False),
    ("Fake Honky Tonk", ["Dusty Mockfield"], ["country"], None, None, None, "2019-09-09", 80, False),
    ("Fake Honky Tonk II", ["Dusty Mockfield"], ["country"], None, None, None, "2019-10-10", 12, False),
    ("Bass Dummy", ["DJ Sample"], ["electronic"], None, None, None, "2025-05-05", 19, True),
]

CONFIG = Config(
    default_days_threshold=14,
    english_default=True,
    rules=(
        Rule("Malayalam favourites", "Fake Malayalam Mix", {"language_in": ["malayalam"]}, days_threshold=7),
        Rule("Hindi hits", "Fake Hindi Hits", {"language_in": ["hindi"]}, target_position="top"),
        Rule("Bengali corner", "Fake Duplicate", {"language_in": ["bengali"]}),
        Rule("Tamil and Telugu", "Fake Tamil Telugu", {"language_in": ["tamil", "telugu"]}),
        Rule("Spanish nights", "Fake Latino", {"language_in": ["spanish"]}),
        Rule("Rock legends", "Fake Rock", {"artist_in": ["Fake Band Alpha", "Fake Band Beta"]},
             days_threshold=21, target_position="top"),
        Rule("Alpha live cuts", "Fake Rock", {"artist_in": ["Fake Band Alpha"], "track_name_contains": "live"}),
        Rule("Lo-fi study", "Fake Chill", {"genre_contains": ["lo-fi"]}),
        Rule("Old jazz", "Fake Jazz Vault", {"genre_contains": ["jazz"], "release_year_before": 1990}),
        Rule("Polka party", "Fake Polka", {"genre_contains": ["polka"]}),
        Rule("Draft country", "Fake Country", {"genre_contains": ["country"]}, enabled=False),
        Rule("English pop", "Fake English", {"language_in": ["english"], "genre_contains": ["pop"]}),
    ),
)

PLAYLISTS = [
    Playlist("pl01", "Fake Malayalam Mix", "me", True, False, items_total=120),
    Playlist("pl02", "Fake Hindi Hits", "me", True, False, items_total=88),
    Playlist("pl03", "Fake Duplicate", "me", True, False, items_total=10),
    Playlist("pl04", "Fake Duplicate", "me", True, False, items_total=12),
    Playlist("pl05", "Fake Tamil Telugu", "someone-else", False, False, items_total=64),
    Playlist("pl06", "Fake Latino", "me", True, False, items_total=30),
    Playlist("pl07", "Fake Rock", "me", True, False, items_total=300),
    Playlist("pl08", "Fake Chill", "me", True, False, items_total=45),
    Playlist("pl09", "Fake Polka", "me", True, False, items_total=5),
    Playlist("pl10", "Fake Country", "me", True, False, items_total=60),
    Playlist("pl11", "Fake English", "me", True, False, items_total=210),
]

PRECISION = {
    "version": 1,
    "generated_at": "2026-09-21T05:30:00+00:00",
    "min_precision": 0.9,
    "min_samples": 10,
    "by_signal": {
        "playlist": {
            "malayalam": {"truth": 120, "predicted": 118, "correct": 118, "precision": 1.0, "recall": 0.9833},
            "hindi": {"truth": 88, "predicted": 84, "correct": 83, "precision": 0.9881, "recall": 0.9432},
            "tamil": {"truth": 64, "predicted": 60, "correct": 59, "precision": 0.9833, "recall": 0.9219},
        },
        "script": {
            "malayalam": {"truth": 120, "predicted": 40, "correct": 40, "precision": 1.0, "recall": 0.3333},
            "hindi": {"truth": 88, "predicted": 30, "correct": 29, "precision": 0.9667, "recall": 0.3295},
            "bengali": {"truth": 12, "predicted": 12, "correct": 12, "precision": 1.0, "recall": 1.0},
            "japanese": {"truth": 9, "predicted": 9, "correct": 9, "precision": 1.0, "recall": 1.0},
        },
        "hint": {
            "spanish": {"truth": 24, "predicted": 20, "correct": 19, "precision": 0.95, "recall": 0.7917},
            "tamil": {"truth": 64, "predicted": 14, "correct": 8, "precision": 0.5714, "recall": 0.125},
            "korean": {"truth": 6, "predicted": 6, "correct": 5, "precision": 0.8333, "recall": 0.8333},
        },
        "country_default": {
            "english": {"truth": 210, "predicted": 200, "correct": 190, "precision": 0.95, "recall": 0.9048},
            "hindi": {"truth": 88, "predicted": 5, "correct": 2, "precision": 0.4, "recall": 0.0227},
        },
    },
}
PRECISION["qualified"] = qualified_map(PRECISION)


def _build_inputs():
    tracks, enrichments = [], {}
    for i, (title, artists, genres, lang, src, conf, rel, age, explicit) in enumerate(_S, start=1):
        tid = f"fx{i:03d}"
        tracks.append(Track(
            id=tid, uri=f"spotify:track:{tid}", name=title,
            artists=tuple(Artist("art-" + a.lower().replace(" ", "-"), a) for a in artists),
            album_name=f"Fake Album {i:02d}", release_date=rel, release_date_precision="day", explicit=explicit,
            added_at=NOW - timedelta(days=age),
        ))
        enrichments[tid] = Enrichment(
            genres=tuple(genres), language=lang,
            sources=tuple(s for s in (("musicbrainz",) if genres else ()) + ((src,) if src else ())),
            language_source=src, language_confidence=conf,
            genre_source="musicbrainz" if genres else None, genre_confidence=0.8 if genres else None,
        )
    return tracks, enrichments


def build_plan(**overrides):
    tracks, enrichments = _build_inputs()
    kwargs = dict(precision=PRECISION, run_id="2026-09-21T06:00:00Z", mode="dry_run", what_if=False,
                  cfg_hash=config_hash(CONFIG_TEXT), inbox_kind="fresh_inbox")
    kwargs.update(overrides)
    return build_latest_plan(tracks, enrichments, CONFIG, NOW, PLAYLISTS, **kwargs)


# ----------------------------------------------------------------------------- runs
def _mv(track, artist, playlist, pid, rule, age, thr, added, pos="bottom", already=False):
    return {"track": track, "artist": artist, "uri": "spotify:track:" + track.lower().replace(" ", "")[:12], "playlist": playlist,
            "playlist_id": pid, "rule": rule, "matched": {}, "age_days": age, "threshold_days": thr,
            "already_in_target": already, "original_added_at": added, "target_position": pos}


def _journal(moves):
    return [{"uri": m["uri"], "name": m["track"], "artists": [m["artist"]], "original_added_at": m["original_added_at"],
             "target_playlist_id": m["playlist_id"]} for m in moves]


RUN_SPECS = [
    # date, time-of-day, mode, what_if, plan_counts, moved, errors, warnings, before, after, secs, rule_counts
    dict(date="2026-09-14", mode="dry_run", what_if=False, plan=dict(will_move=7, too_young=5, no_match=20, blocked=0, target_problem=0),
         moved=0, errors=0, warnings=0, before=52, after=52, secs=41.2, rc={"Lo-fi study": 3, "English pop": 4}),
    dict(date="2026-09-15", mode="apply", what_if=False, plan=dict(will_move=6, too_young=4, no_match=18, blocked=0, target_problem=0),
         moved=6, errors=0, warnings=0, before=52, after=46, secs=88.4, rc={"Lo-fi study": 2, "English pop": 3, "Hindi hits": 1}),
    dict(date="2026-09-16", mode="dry_run", what_if=False, plan=dict(will_move=3, too_young=6, no_match=17, blocked=1, target_problem=0),
         moved=0, errors=0, warnings=1, before=46, after=46, secs=39.0, rc={"Lo-fi study": 1, "Spanish nights": 2}),
    dict(date="2026-09-17", mode="apply", what_if=False, plan=dict(will_move=4, too_young=5, no_match=17, blocked=1, target_problem=1),
         moved=4, errors=0, warnings=3, before=46, after=43, secs=95.7, rc={"Spanish nights": 2, "Lo-fi study": 1, "Rock legends": 1}),
    dict(date="2026-09-18", mode="dry_run", what_if=False, plan=dict(will_move=0, too_young=0, no_match=0, blocked=0, target_problem=0),
         moved=0, errors=1, warnings=0, before=43, after=43, secs=12.3, rc={}),
    dict(date="2026-09-19", mode="dry_run", what_if=False, plan=dict(will_move=5, too_young=7, no_match=25, blocked=2, target_problem=2),
         moved=0, errors=0, warnings=2, before=41, after=41, secs=44.8, rc={"Hindi hits": 2, "English pop": 3}),
    dict(date="2026-09-20", mode="dry_run", what_if=True, plan=dict(will_move=17, too_young=6, no_match=15, blocked=2, target_problem=3),
         moved=0, errors=0, warnings=2, before=43, after=43, secs=46.1, rc={"Draft country": 2, "English pop": 5, "Hindi hits": 3}),
]


def build_runs(out: Path, plan: dict) -> dict:
    """Write per-run logs + runs.json (oldest first so the index ends newest first). Returns the runs index."""
    runs_path = out / "runs.json"
    if runs_path.exists():
        runs_path.unlink()
    latest_spec = dict(date="2026-09-21", mode="dry_run", what_if=False, plan=plan["counts"], moved=0, errors=0,
                       warnings=min(plan["counts"]["target_problem"], 2), before=plan["liked_total"], after=plan["liked_total"], secs=42.5,
                       rc={r["name"]: r["wins"] for r in plan["rules"] if r["wins"]})
    index = None
    for spec in RUN_SPECS + [latest_spec]:
        hour = 6
        when = datetime.fromisoformat(spec["date"]).replace(hour=hour, tzinfo=timezone.utc)
        run_id = when.strftime("%Y-%m-%dT%H:%M:%SZ")
        log_file = f"{spec['date']}.json"
        entry = run_entry(run_id=run_id, now=when, mode=spec["mode"], plan_counts=spec["plan"], moved=spec["moved"],
                          errors=spec["errors"], warnings=spec["warnings"], liked_before=spec["before"],
                          liked_after=spec["after"], duration_s=spec["secs"], rule_counts=spec["rc"], log_file=log_file,
                          what_if=spec["what_if"])
        atomic_write_json(out / log_file, _run_log(spec, entry, plan))
        # decision 34: the Overview reads a top-level `schedule` field from runs.json (built by
        # src.artifacts.schedule_info from the workflow's SPOTISORT_CRON). The demo fixtures show a fixed
        # example schedule so "Next scheduled run" has something real to display in Demo mode.
        index = update_runs_index(runs_path, entry, when, schedule=schedule_info("0 3 * * *", NOW))
    return index


def _run_log(spec: dict, entry: dict, plan: dict) -> dict:
    apply = spec["mode"] == "apply"
    is_latest = spec["date"] == "2026-09-21"
    if is_latest:
        moved = [_mv(s["title"], ", ".join(s["artists"]), s["target_playlist"], "plfix", s["rule"], s["age_days"],
                     next(r["threshold_days"] for r in plan["rules"] if r["name"] == s["rule"]), s["added_at"], s["target_position"])
                 for s in plan["songs"] if s["decision"] == "will_move"]
        young = [{"track": s["title"], "artist": s["artists"][0], "rule": s["rule"], "age_days": s["age_days"],
                  "threshold_days": next(r["threshold_days"] for r in plan["rules"] if r["name"] == s["rule"])}
                 for s in plan["songs"] if s["decision"] == "too_young"]
        missing = [{"track": s["title"], "target_playlist": s["target_playlist"], "rule": s["rule"], "reason": s["target_status"],
                    "would_create": False} for s in plan["songs"] if s["decision"] == "target_problem"]
        errors: list[str] = []
        warnings = [f"target playlist {m['target_playlist']!r} is {m['reason']}" for m in missing][:2]
    else:
        n = spec["moved"] if apply else spec["plan"]["will_move"]
        pool = [("Fake Anthem", "Fake Band Alpha", "Fake Rock", "pl07", "Rock legends", "top"),
                ("Placeholder Love", "Sample Singer", "Fake English", "pl11", "English pop", "bottom"),
                ("Nameless Loop 02", "Beats Not Real", "Fake Chill", "pl08", "Lo-fi study", "bottom"),
                ("Fake Dil", "Pyaar Placeholder", "Fake Hindi Hits", "pl02", "Hindi hits", "top"),
                ("Noche Falsa", "La Banda Ejemplo", "Fake Latino", "pl06", "Spanish nights", "bottom"),
                ("Dummy Hearts", "Faux Star", "Fake English", "pl11", "English pop", "bottom"),
                ("Mock Midnight", "Test Tones", "Fake English", "pl11", "English pop", "bottom")]
        moved = [_mv(t, a, pl, pid, r, 30.0 + i, 14, f"2026-08-{10 + i:02d}T10:00:00+00:00", pos)
                 for i, (t, a, pl, pid, r, pos) in enumerate((pool * 2)[:n])]
        young = [{"track": f"Fresh Fixture {i}", "artist": "Sample Singer", "rule": "English pop", "age_days": 2.0 + i, "threshold_days": 14}
                 for i in range(spec["plan"]["too_young"])][:3]
        missing = [{"track": "Pretend Blues", "target_playlist": "Fake Jazz Vault", "rule": "Old jazz", "reason": "missing", "would_create": False}
                   for _ in range(spec["plan"]["target_problem"])]
        errors = ["GET /me/tracks failed: HTTP 503 after 5 retries (fixture error)"] if spec["errors"] else []
        warnings = [f"warning {i + 1}: target playlist 'Fake Jazz Vault' not found" for i in range(spec["warnings"])]
    log = {
        "date": spec["date"], "run_id": entry["run_id"], "mode": spec["mode"], "dry_run": not apply, "what_if": spec["what_if"],
        "evaluated": spec["before"], "moved": moved, "skipped_no_match": spec["plan"]["no_match"],
        "skipped_too_young": young, "skipped_playlist_missing": missing, "errors": errors, "warnings": warnings,
        "journal": _journal(moved) if apply else [],
        "liked_before": spec["before"], "liked_after": spec["after"], "verdict": entry["verdict"],
        "rule_counts": entry["rule_counts"], "config_hash": config_hash(CONFIG_TEXT), "plan_counts": dict(spec["plan"]),
        "http_audit": ({"GET api.spotify.com": 31, "POST api.spotify.com": 2, "PUT api.spotify.com": 0, "DELETE api.spotify.com": 3}
                       if apply else {"GET api.spotify.com": 28}),
        "runtime_seconds": entry["duration_seconds"],
    }
    if apply:
        expected = spec["before"] - spec["moved"]
        by_pl: dict[str, int] = {}
        for m in moved:
            by_pl[m["playlist_id"]] = by_pl.get(m["playlist_id"], 0) + 1
        log["reconcile"] = {"expected_after": expected, "actual_after": spec["after"], "ok": expected == spec["after"]}
        log["restore_command"] = f"python -m src.sync --restore logs/{spec['date']}.json"
        log["batches"] = [{"playlist_id": pid, "size": n, "committed": True} for pid, n in sorted(by_pl.items())]
        if not log["reconcile"]["ok"]:
            log["warnings"].append("liked count did not reconcile: expected 42, found 43; run aborted and songs re-added")
    return log


# ----------------------------------------------------------------------------- coverage / backtest
def coverage() -> dict:
    return {
        "date": "2026-09-21", "tracks": len(_S), "unique_primary_artists": 24,
        "genre_coverage_pct_of_artists": 79.2, "genre_note": "fixture data",
        "language_coverage_pct_whole_library": 82.6, "language_coverage_pct_target_language_tracks": 100.0,
        "target_language_tracks": 15, "target_language_tracks_resolved": 15,
        "language_source_counts": {"playlist": 6, "script": 6, "hint": 5, "country_default": 13, "none": 12},
        "language_distribution": {"english": 13, "hindi": 4, "malayalam": 4, "tamil": 2, "spanish": 2, "bengali": 1,
                                  "telugu": 1, "japanese": 1, "korean": 1},
        "genre_source_counts": {"musicbrainz": 32, "none": 12},
        "musicbrainz": {"requests": 18, "retries_after_503_or_429": 1, "errors": 0},
    }


_BT_NAMES = ["Fake Malayalam Mix", "Fake Hindi Hits", "Fake Rock", "Fake Chill", "Fake Latino"]
_BT_TP = [104, 80, 262, 40, 0]
_BT_UNROUTED = [8, 3, 20, 2, 30]
_BT_CONF = [(0, 1, 6), (1, 0, 4), (2, 3, 20), (3, 2, 3), (1, 3, 5), (0, 3, 2), (2, 0, 3)]
_BT_RULES = [("Malayalam favourites", 110, 104), ("Hindi hits", 90, 80), ("Rock legends", 270, 262), ("Lo-fi study", 60, 40),
             ("Spanish nights", 0, 0)]


def _ratio(a: int, b: int):
    return round(a / b, 4) if b else None


def backtest(detail: bool) -> dict:
    n = len(_BT_NAMES)
    out_mis = [sum(c for t, _, c in _BT_CONF if t == i) for i in range(n)]
    in_mis = [sum(c for _, p, c in _BT_CONF if p == i) for i in range(n)]
    playlists = []
    for i in range(n):
        tracks = _BT_TP[i] + _BT_UNROUTED[i] + out_mis[i]
        predicted = _BT_TP[i] + in_mis[i]
        row = {"id": f"P{i + 1:02d}"}
        if detail:
            row["name"] = _BT_NAMES[i]
        row.update({"tracks": tracks, "predicted": predicted, "tp": _BT_TP[i], "precision": _ratio(_BT_TP[i], predicted),
                    "recall": _ratio(_BT_TP[i], tracks), "unrouted": _BT_UNROUTED[i]})
        playlists.append(row)
    total_tracks = sum(p["tracks"] for p in playlists)
    routed = sum(p["predicted"] for p in playlists)
    correct = sum(_BT_TP)
    rules = []
    for i, (name, pred, ok) in enumerate(_BT_RULES):
        row = {"name_id": f"R{i + 1:02d}"}
        if detail:
            row["name"] = name
        row.update({"predicted": pred, "correct": ok, "precision": _ratio(ok, pred)})
        rules.append(row)
    data = {
        "version": 1, "generated_at": "2026-09-21T05:45:00+00:00", "config_hash": config_hash(CONFIG_TEXT),
        "all_rules_enabled": True, "inbox": {"tracks": total_tracks, "playlists": n}, "playlists": playlists,
        "confusions": [{"true": f"P{t + 1:02d}", "predicted": f"P{p + 1:02d}", "count": c} for t, p, c in _BT_CONF],
        "totals": {"tracks": total_tracks, "routed": routed, "correct": correct, "misrouted": routed - correct,
                   "unrouted": sum(_BT_UNROUTED), "precision": _ratio(correct, routed), "recall": _ratio(correct, total_tracks)},
        "rules": rules,
    }
    if detail:
        data["top_misroutes"] = [
            {"title": "Fake Anthem Remix", "artists": ["Fake Band Alpha"], "true": ["Fake Rock"], "predicted": "Fake Chill", "rule": "Lo-fi study"},
            {"title": "Sample Ballad III", "artists": ["Fake Band Beta"], "true": ["Fake Rock"], "predicted": "Fake Chill", "rule": "Lo-fi study"},
            {"title": "Fake Dil (Slow)", "artists": ["Pyaar Placeholder"], "true": ["Fake Hindi Hits"], "predicted": "Fake Chill", "rule": "Lo-fi study"},
            {"title": "Placeholder Pyaar II", "artists": ["Pyaar Placeholder"], "true": ["Fake Hindi Hits", "Fake Malayalam Mix"],
             "predicted": "Fake Malayalam Mix", "rule": "Malayalam favourites"},
            {"title": "Mazha Loop", "artists": ["Vayali Test"], "true": ["Fake Malayalam Mix"], "predicted": "Fake Hindi Hits", "rule": "Hindi hits"},
            {"title": "Nameless Loop 09", "artists": ["Beats Not Real"], "true": ["Fake Chill"], "predicted": "Fake Rock", "rule": "Rock legends"},
        ]
    return data


# ----------------------------------------------------------------------------- entry point
def generate(out: Path | str = DEFAULT_OUT) -> list[str]:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    plan = build_plan()
    atomic_write_json(out / "latest-plan.json", plan)
    build_runs(out, plan)
    atomic_write_json(out / "enrichment-coverage.json", coverage())
    atomic_write_json(out / "signal-precision.json", PRECISION)
    atomic_write_json(out / "backtest.json", backtest(False))
    atomic_write_json(out / "backtest-detail.json", backtest(True))
    return sorted(p.name for p in out.glob("*.json"))


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    for name in generate(target):
        print(target / name)
