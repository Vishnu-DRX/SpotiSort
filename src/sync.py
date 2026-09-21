"""Sync entrypoint: `python -m src.sync` (dry-run by default).

Phase 3: full read-only pipeline (fetch -> enrich -> evaluate -> resolve targets -> explainable plan ->
log). ``--apply`` is not implemented yet (Phase 4) and refuses to run.
"""

from __future__ import annotations

import argparse
import json
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
from .planner import Plan, build_plan, targets_needed
from .spotify_client import SpotifyClient, SpotifyError, load_env

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
    p.add_argument("--apply", action="store_true", help="perform writes (NOT IMPLEMENTED until Phase 4)")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--env", default=".env")
    p.add_argument("--cache", default=str(DEFAULT_PATH))
    p.add_argument("--logs-dir", default="logs")
    p.add_argument("--limit", type=int, default=None, help="plan at most N moves (oldest liked first)")
    p.add_argument("--since", default=None, help="only consider songs liked on/after YYYY-MM-DD")
    p.add_argument("--rule", default=None, help="only plan moves for the rule with this name")
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


def run(args: argparse.Namespace) -> int:
    if args.apply:
        print("error: --apply is not implemented yet (Phase 4). Running dry-run only is supported.", file=sys.stderr)
        return 2
    started = time.monotonic()
    load_env(args.env)
    try:
        config = load_config(args.config)
        since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc) if args.since else None
    except (ConfigError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    session = AuditSession()
    client = SpotifyClient.from_env(dry_run=True, session=session)
    now = datetime.now(timezone.utc)

    tracks = list(client.iter_saved_tracks())
    playlists = list(client.iter_my_playlists())
    lmap, lang_warnings, _ = build_language_map(client, config)

    cache = EnrichmentCache(args.cache)
    mb = MusicBrainz() if (config.musicbrainz and not args.no_network) else None
    enricher = Enricher(cache, mb, lmap)
    enrichments = {}
    saved_at = 0
    for t in tracks:
        enrichments[t.id] = enricher.resolve(t)
        if mb and mb.requests_made - saved_at >= SAVE_EVERY:
            cache.save()
            saved_at = mb.requests_made
    if cache.dirty:
        cache.save()

    needed = targets_needed(tracks, enrichments, config, now, playlists, args.rule)
    membership = {pid: {t.uri for t in client.iter_playlist_items(pid)} for pid in needed}

    plan = build_plan(
        tracks, enrichments, config, now, playlists, membership,
        only_rule=args.rule, since=since, limit=args.limit,
    )
    plan.warnings = lang_warnings + plan.warnings
    if enricher.errors:
        plan.warnings.append(f"{enricher.errors} MusicBrainz lookup(s) failed; those artists have no genre this run")

    if session.write_calls_to_api():  # cannot happen (client refuses), but verify rather than assume
        print("FATAL: a write call reached the Spotify API during a dry run", file=sys.stderr)
        return 3

    log = build_log(plan, True, session.audit, now, time.monotonic() - started)
    logs_dir = Path(args.logs_dir)
    logs_dir.mkdir(parents=True, exist_ok=True)
    out = logs_dir / f"{date.today().isoformat()}.json"
    out.write_text(json.dumps(log, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print_summary(plan, out)
    return 0


def print_summary(plan: Plan, out: Path) -> None:
    print(f"DRY RUN: evaluated {plan.evaluated} liked songs; no writes performed.")
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
    except (SpotifyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
