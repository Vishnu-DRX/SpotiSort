"""Enrichment coverage report: `python -m src.enrich --report`.

Read-only against Spotify (dry-run client); talks to MusicBrainz unless --no-network or disabled in config.
Writes logs/enrichment-coverage.json (counts and top-10 unresolved artists only) and updates the cache.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from .config import ConfigError, load_config
from .enrichment.cache import DEFAULT_PATH, EnrichmentCache
from .enrichment.enricher import Enricher
from .enrichment.isrc_country import isrc_country, language_hint_from_country
from .enrichment.musicbrainz import MusicBrainz
from .enrichment.playlist_language import LanguageMap, resolve_language_playlists
from .models import Config
from .spotify_client import SpotifyClient, SpotifyError, load_env

GENRE_GATE = 60.0
LANGUAGE_GATE = 85.0
SAVE_EVERY = 25


def build_language_map(client: SpotifyClient, config: Config, playlists=None) -> tuple[LanguageMap, list[str], dict[str, int]]:
    """Learn artist->language from the configured language playlists (read-only)."""
    lmap = LanguageMap()
    if not config.language_playlists:
        return lmap, [], {}
    ids, warnings = resolve_language_playlists(
        config.language_playlists, playlists if playlists is not None else client.iter_my_playlists()
    )
    sizes: dict[str, int] = {}
    for pid, lang in ids.items():
        tracks = list(client.iter_playlist_items(pid))
        lmap.add_playlist(tracks, lang)
        sizes[lang] = sizes.get(lang, 0) + len(tracks)
    return lmap, warnings, sizes


def coverage(tracks, enrichments, mb: MusicBrainz | None, enricher: Enricher) -> dict[str, Any]:
    n = len(tracks)
    artists: dict[str, dict[str, Any]] = {}
    lang_sources: Counter[str] = Counter()
    languages: Counter[str] = Counter()
    unresolved_lang: Counter[str] = Counter()
    hinted = 0  # unresolved tracks a WEAK country hint would label (hypothetical, not applied)
    english_speaking = {"US", "GB", "AU", "CA", "IE", "NZ"}
    for t, e in zip(tracks, enrichments):
        if t.artists:
            key = t.artists[0].id or t.artists[0].name
            slot = artists.setdefault(key, {"name": t.artists[0].name, "has_genre": False, "tracks": 0})
            slot["tracks"] += 1
            slot["has_genre"] = slot["has_genre"] or bool(e.genres)
        if e.language:
            languages[e.language] += 1
            lang_sources["playlist" if "playlist" in e.sources else "script"] += 1
        else:
            lang_sources["none"] += 1
            entry = enricher.cache.get_artist(t.artists[0].id) if t.artists else None
            country = (entry or {}).get("country")
            if country in english_speaking or language_hint_from_country(isrc_country(t.isrc)):
                hinted += 1
            if t.artists:
                unresolved_lang[t.artists[0].name] += 1
    with_genre = sum(1 for a in artists.values() if a["has_genre"])
    with_lang = sum(languages.values())
    no_genre = sorted((a for a in artists.values() if not a["has_genre"]), key=lambda a: -a["tracks"])
    genre_pct = round(100 * with_genre / len(artists), 1) if artists else 0.0
    lang_pct = round(100 * with_lang / n, 1) if n else 0.0
    return {
        "date": date.today().isoformat(),
        "tracks": n,
        "unique_primary_artists": len(artists),
        "genre_coverage_pct_of_artists": genre_pct,
        "language_coverage_pct_of_tracks": lang_pct,
        "hypothetical_language_pct_with_weak_country_hint": round(100 * (with_lang + hinted) / n, 1) if n else 0.0,
        "gates": {
            "genre_ge_60": genre_pct >= GENRE_GATE,
            "language_ge_85": lang_pct >= LANGUAGE_GATE,
        },
        "language_source_counts": dict(lang_sources),
        "language_distribution": dict(languages.most_common()),
        "genre_source_counts": {"musicbrainz": with_genre, "none": len(artists) - with_genre},
        "top_unresolved_artists_genre": [{"name": a["name"], "tracks": a["tracks"]} for a in no_genre[:10]],
        "top_unresolved_artists_language": [{"name": k, "tracks": v} for k, v in unresolved_lang.most_common(10)],
        "musicbrainz": {
            "requests": mb.requests_made if mb else 0,
            "retries_after_503_or_429": mb.retries_503 if mb else 0,
            "errors": enricher.errors,
        },
    }


def run(args: argparse.Namespace) -> int:
    load_env(args.env)
    config_path = Path(args.config)
    try:
        config = load_config(config_path) if config_path.exists() else Config()
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    client = SpotifyClient.from_env(dry_run=True)
    print("reading liked songs...", file=sys.stderr)
    tracks = list(client.iter_saved_tracks())
    if args.limit:
        tracks = tracks[: args.limit]
    lmap, warnings, sizes = build_language_map(client, config)
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    print(f"{len(tracks)} tracks; language playlists learned from {sizes or 'none'}", file=sys.stderr)

    cache = EnrichmentCache(args.cache)
    use_mb = config.musicbrainz and not args.no_network
    mb = MusicBrainz() if use_mb else None
    enricher = Enricher(cache, mb, lmap)

    enrichments = []
    last_saved = 0
    for i, t in enumerate(tracks, 1):
        enrichments.append(enricher.resolve(t))
        if mb and mb.requests_made - last_saved >= SAVE_EVERY:
            cache.save()
            last_saved = mb.requests_made
        if i % 50 == 0:
            print(f"  {i}/{len(tracks)}  musicbrainz requests: {mb.requests_made if mb else 0}", file=sys.stderr)
    if cache.dirty:
        cache.save()

    report = coverage(tracks, enrichments, mb, enricher)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "tracks", "unique_primary_artists", "genre_coverage_pct_of_artists",
        "language_coverage_pct_of_tracks", "gates", "language_source_counts", "musicbrainz")}, indent=2))
    print(f"wrote {out}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m src.enrich", description=__doc__.split("\n")[0])
    p.add_argument("--report", action="store_true", required=True, help="coverage report over all liked tracks")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--env", default=".env")
    p.add_argument("--cache", default=str(DEFAULT_PATH))
    p.add_argument("--out", default="logs/enrichment-coverage.json")
    p.add_argument("--limit", type=int, default=0, help="only the first N liked tracks (for a quick trial)")
    p.add_argument("--no-network", action="store_true", help="do not call MusicBrainz; cache + local signals only")
    args = p.parse_args(argv)
    try:
        return run(args)
    except (SpotifyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
