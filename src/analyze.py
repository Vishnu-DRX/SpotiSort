"""Analyze mode: `python -m src.analyze` drafts a starting config.yaml from your existing playlists.

Read-only: uses a dry-run client, reads only owned/collaborative playlists (followed ones return 403 and are
skipped and reported), and never applies anything. Every drafted rule is ``enabled: false`` with a rationale
comment; ``language_playlists`` suggestions are made for playlists that are >= 70 % one language.

Language in a profile comes from content signals only (script, artist country default, cache) and never from
``language_playlists``, so a playlist's language is not circularly derived from its own mapping.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .config import ConfigError, load_config
from .enrichment.cache import DEFAULT_PATH, EnrichmentCache
from .enrichment.enricher import Enricher
from .enrichment.musicbrainz import MusicBrainz
from .models import Config, Enrichment, Playlist, Track
from .rules_engine import release_year
from .spotify_client import SpotifyClient, SpotifyError, load_env

MIN_TRACKS = 10  # smaller playlists are too thin to infer a pattern from
LANGUAGE_SHARE = 0.70
GENRE_SHARE = 0.40
ARTIST_SHARE = 0.30
ERA_SPAN = 15
EXPLICIT_HIGH = 0.90


@dataclass
class Profile:
    name: str
    tracks: int
    top_genres: list[tuple[str, int]] = field(default_factory=list)
    genre_tracks: int = 0  # tracks that had any genre
    top_artists: list[tuple[str, int]] = field(default_factory=list)
    languages: dict[str, int] = field(default_factory=dict)
    language_tracks: int = 0
    year_p10: int | None = None
    year_p90: int | None = None
    year_median: int | None = None
    explicit_ratio: float = 0.0


def _percentile(sorted_vals: Sequence[int], q: float) -> int:
    idx = min(len(sorted_vals) - 1, max(0, round(q * (len(sorted_vals) - 1))))
    return sorted_vals[idx]


def analyze_playlist(name: str, tracks: Sequence[Track], enrichments: Mapping[str, Enrichment]) -> Profile:
    """Pure: summarise one playlist. ``enrichments`` is keyed by track id (missing => no genre/language)."""
    genres: Counter[str] = Counter()
    artists: Counter[str] = Counter()
    languages: Counter[str] = Counter()
    years: list[int] = []
    explicit = genre_tracks = 0
    for t in tracks:
        e = enrichments.get(t.id)
        if e and e.genres:
            genre_tracks += 1
            genres.update(set(e.genres))
        if e and e.language:
            languages[e.language] += 1
        for a in t.artists:
            if a.name:
                artists[a.name] += 1
        y = release_year(t.release_date, t.release_date_precision)
        if y is not None:
            years.append(y)
        explicit += 1 if t.explicit else 0
    years.sort()
    p = Profile(
        name=name,
        tracks=len(tracks),
        top_genres=genres.most_common(5),
        genre_tracks=genre_tracks,
        top_artists=artists.most_common(5),
        languages=dict(languages.most_common()),
        language_tracks=sum(languages.values()),
        explicit_ratio=round(explicit / len(tracks), 3) if tracks else 0.0,
    )
    if years:
        p.year_p10, p.year_p90 = _percentile(years, 0.10), _percentile(years, 0.90)
        p.year_median = int(statistics.median(years))
    return p


def dominant_language(p: Profile) -> tuple[str, float] | None:
    if not p.tracks or not p.languages:
        return None
    lang, n = next(iter(p.languages.items()))
    share = n / p.tracks
    return (lang, share) if share >= LANGUAGE_SHARE else None


@dataclass
class DraftRule:
    name: str
    target: str
    match: dict
    rationale: str


def infer_rule(p: Profile) -> tuple[DraftRule | None, str | None]:
    """(rule, reason_skipped). A rule needs at least one identifying condition; explicit alone is too broad."""
    if p.tracks < MIN_TRACKS:
        return None, f"only {p.tracks} tracks (< {MIN_TRACKS}): too few to infer a pattern"
    match: dict = {}
    why: list[str] = []
    dom = dominant_language(p)
    if dom and dom[0] != "english":  # english is a weak default (any Latin-script US/GB/... song), never a rule on its own
        match["language_in"] = [dom[0]]
        why.append(f"{dom[1]:.0%} of tracks are {dom[0]}")
    if p.genre_tracks >= MIN_TRACKS and p.top_genres:
        picked = [g for g, n in p.top_genres[:2] if n / p.genre_tracks >= GENRE_SHARE]
        if picked:
            match["genre_contains"] = picked
            share = p.top_genres[0][1] / p.genre_tracks
            why.append(f"{share:.0%} of the {p.genre_tracks} genre-tagged tracks are '{picked[0]}'")
    covered, picked_artists = 0, []
    for a, n in p.top_artists[:3]:
        if n >= 3:
            picked_artists.append(a)
            covered += n
    if picked_artists and covered / p.tracks >= ARTIST_SHARE:
        match["artist_in"] = picked_artists
        why.append(f"{covered / p.tracks:.0%} of tracks are by {', '.join(picked_artists)}")
    if not match:  # era and explicit only refine a rule; alone they would match half the library
        return None, "no distinguishing pattern (no dominant language, genre or artist group)"
    if p.year_p10 and p.year_p90 and p.year_p90 - p.year_p10 <= ERA_SPAN:
        match["release_year_after"] = p.year_p10 - 1
        match["release_year_before"] = p.year_p90 + 1
        why.append(f"80% of tracks released {p.year_p10}-{p.year_p90}")
    if p.explicit_ratio >= EXPLICIT_HIGH:
        match["explicit"] = True
        why.append(f"{p.explicit_ratio:.0%} explicit")
    rationale = f'"{p.name}" inferred from {p.tracks} tracks: ' + "; ".join(why) + ". Review before enabling."
    return DraftRule(f"{p.name} (inferred)", p.name, match, rationale), None


def _q(value) -> str:
    """YAML-safe scalar: JSON strings/numbers/bools are valid YAML flow scalars."""
    if isinstance(value, bool):
        return "true" if value else "false"
    out = json.dumps(value, ensure_ascii=False)
    for code in (0x2028, 0x2029, 0x85):  # YAML line breaks that JSON leaves raw
        out = out.replace(chr(code), "\\u%04x" % code)
    return out


def _c(text: str) -> str:
    return " ".join(str(text).split())  # keep comments on one line


def render_draft(profiles: Iterable[Profile], skipped_followed: int = 0, unreadable: Sequence[str] = ()) -> str:
    profiles = list(profiles)
    lines = [
        "# SpotiSort draft config, generated by `python -m src.analyze`. NOTHING here is applied automatically.",
        "# Every rule starts disabled. Review each one, then set enabled: true (or use the config builder).",
        f"# Analysed {len(profiles)} owned/collaborative playlists; {skipped_followed} followed playlists were skipped (not readable).",
        "",
        "default_days_threshold: 14",
        "fallback_playlist: null",
        "enrichment:",
        "  musicbrainz: true",
        "  english_default: true",
        "",
    ]
    suggestions = []
    seen_names: set[str] = set()
    for p in profiles:
        dom = dominant_language(p)
        if dom and dom[0] != "english" and p.tracks >= MIN_TRACKS and len(p.name) <= 200:  # english is the default; not worth teaching
            if p.name.casefold() in seen_names:
                continue
            seen_names.add(p.name.casefold())
            suggestions.append((p, dom))
    if suggestions:
        lines.append("# Suggested language playlists (playlist is >= 70% one language); they teach SpotiSort which artists sing in it.")
        lines.append("language_playlists:")
        for p, (lang, share) in suggestions:
            lines.append(f"  {_q(p.name)}: {lang}   # {share:.0%} of {p.tracks} tracks")
    else:
        lines.append("language_playlists: {}")
    lines += ["", "rules:"]
    used: set[str] = set()
    emitted = 0
    skipped_notes: list[str] = []
    for p in profiles:
        rule, reason = infer_rule(p)
        if rule is None:
            skipped_notes.append(f"# skipped {_c(_q(p.name))}: {reason}")
            continue
        if rule.name.casefold() in used:
            skipped_notes.append(f"# skipped {_c(_q(p.name))}: duplicate playlist name")
            continue
        used.add(rule.name.casefold())
        emitted += 1
        lines.append(f"  # {_c(rule.rationale)}")
        lines.append(f"  - name: {_q(rule.name)}")
        lines.append("    enabled: false   # analyze-mode rules start disabled until reviewed")
        lines.append("    match:")
        for key, val in rule.match.items():
            rendered = "[" + ", ".join(_q(v) for v in val) + "]" if isinstance(val, list) else _q(val)
            lines.append(f"      {key}: {rendered}")
        lines.append(f"    target_playlist: {_q(rule.target)}")
        lines.append("")
    if emitted == 0:
        lines[-1] = "rules: []"
    if skipped_notes or unreadable:
        lines.append("# ---- playlists without a drafted rule ----")
        lines += skipped_notes
        lines += [f"# unreadable (skipped): {_c(_q(n))}" for n in unreadable]
    return "\n".join(lines).rstrip() + "\n"


def run(args: argparse.Namespace) -> int:
    load_env(args.env)
    cfg_path = Path(args.config)
    try:
        config = load_config(cfg_path) if cfg_path.exists() else Config()
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    client = SpotifyClient.from_env(dry_run=True)
    playlists = list(client.iter_my_playlists())
    usable = [p for p in playlists if p.usable and p.name.casefold() != "spotisort test"]
    followed = sum(1 for p in playlists if not p.usable)

    cache = EnrichmentCache(args.cache)
    mb = MusicBrainz() if (config.musicbrainz and not args.no_network) else None
    enricher = Enricher(cache, mb, None, config.english_default)  # no language_map: content signals only

    profiles: list[Profile] = []
    unreadable: list[str] = []
    for pl in usable:
        try:
            tracks = list(client.iter_playlist_items(pl.id))
        except SpotifyError as exc:
            if exc.status == 403:
                unreadable.append(pl.name)
                continue
            raise
        enr = {t.id: enricher.resolve(t) for t in tracks}
        profiles.append(analyze_playlist(pl.name, tracks, enr))
        print(f"  analysed {len(tracks):4d} tracks", file=sys.stderr)
    if cache.dirty:
        cache.save()

    draft = render_draft(profiles, followed, unreadable)
    out = Path(args.output)
    out.write_text(draft, encoding="utf-8")
    print(f"wrote {out}: {len(profiles)} playlists analysed, {followed} followed skipped, {len(unreadable)} unreadable")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m src.analyze", description=__doc__.split("\n")[0])
    p.add_argument("--output", default="config.draft.yaml")
    p.add_argument("--config", default="config.yaml", help="only used for enrichment settings")
    p.add_argument("--env", default=".env")
    p.add_argument("--cache", default=str(DEFAULT_PATH))
    p.add_argument("--no-network", action="store_true", help="do not call MusicBrainz (cache + local signals only)")
    args = p.parse_args(argv)
    try:
        return run(args)
    except (SpotifyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
