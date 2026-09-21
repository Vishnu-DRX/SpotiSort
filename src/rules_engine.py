"""Pure rule-matching logic (no I/O). No popularity key: Spotify removed the field.

Semantics
- Rules are evaluated in file order; the first enabled rule that matches wins.
- All keys inside one rule's ``match`` are AND-combined.
- A rule's age gate (``days_threshold``, else the default) is part of its condition:
  a track younger than the threshold does not match that rule, later rules still apply.
- A track with no ``added_at`` never satisfies an age gate (conservative: never moved).
- Genre/language conditions are simply false when enrichment is missing or empty.
- ``release_year_before`` is strict (year < N); ``release_year_after`` is strict (year > N).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Sequence

from .models import Enrichment, Match, Rule, Track

DEFAULT_DAYS_THRESHOLD = 14
_YEAR_RE = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$")


def release_year(release_date: str | None, precision: str | None = None) -> int | None:
    """Year from a Spotify ``release_date`` at ``year``, ``month`` or ``day`` precision.

    Returns None when the string is missing or malformed. The string shape decides;
    ``precision`` is accepted for interface symmetry with the API and only used to
    reject a value that is shorter than its declared precision.
    """
    if not release_date:
        return None
    m = _YEAR_RE.match(release_date.strip())
    if not m:
        return None
    parts = sum(1 for g in m.groups() if g)
    needed = {"year": 1, "month": 2, "day": 3}.get(precision or "", 1)
    if parts < needed:
        return None
    return int(m.group(1))


def age_days(track: Track, now: datetime) -> float | None:
    if track.added_at is None:
        return None
    return (now - track.added_at).total_seconds() / 86400


def resolve_days_threshold(rule: Rule, default_days_threshold: int) -> int:
    return rule.days_threshold if rule.days_threshold is not None else default_days_threshold


def _fold(value: str) -> str:
    return value.strip().casefold()


def _match_keys(
    track: Track, enrichment: Enrichment | None, match: dict[str, Any]
) -> dict[str, Any] | None:
    """Return {key: what matched} if every key is satisfied, else None."""
    matched: dict[str, Any] = {}
    for key, wanted in match.items():
        if key == "artist_in":
            names = {_fold(a.name) for a in track.artists}
            hits = [w for w in wanted if _fold(w) in names]
            if not hits:
                return None
            matched[key] = hits[0]
        elif key == "genre_contains":
            genres = [_fold(g) for g in (enrichment.genres if enrichment else ())]
            hit = next((w for w in wanted if _fold(w) and any(_fold(w) in g for g in genres)), None)
            if hit is None:
                return None
            matched[key] = hit
        elif key == "language_in":
            lang = enrichment.language if enrichment else None
            if not lang or _fold(lang) not in {_fold(w) for w in wanted}:
                return None
            matched[key] = lang
        elif key in ("release_year_before", "release_year_after"):
            year = release_year(track.release_date, track.release_date_precision)
            if year is None:
                return None
            ok = year < wanted if key == "release_year_before" else year > wanted
            if not ok:
                return None
            matched[key] = year
        elif key == "explicit":
            if bool(track.explicit) is not wanted:
                return None
            matched[key] = wanted
        elif key == "track_name_contains":
            if not wanted.strip() or _fold(wanted) not in _fold(track.name):
                return None
            matched[key] = wanted
        elif key == "album_name_contains":
            if not wanted.strip() or _fold(wanted) not in _fold(track.album_name):
                return None
            matched[key] = wanted
        else:  # unknown key: never silently ignore a condition
            return None
    return matched


def evaluate(
    track: Track,
    enrichment: Enrichment | None,
    rules: Sequence[Rule],
    now: datetime,
    default_days_threshold: int = DEFAULT_DAYS_THRESHOLD,
) -> Match | None:
    """First enabled rule that matches ``track`` (age gate included), or None."""
    age = age_days(track, now)
    for rule in rules:
        if not rule.enabled or not rule.match:
            continue
        if age is None or age < resolve_days_threshold(rule, default_days_threshold):
            continue
        matched = _match_keys(track, enrichment, rule.match)
        if matched is not None:
            return Match(rule=rule, matched=matched, age_days=age)
    return None
