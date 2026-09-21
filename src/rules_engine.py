"""Pure rule-matching logic (no I/O). No popularity key: Spotify removed the field.

Semantics
- Rules are evaluated in file order; the first enabled rule that matches wins.
- All keys inside one rule's ``match`` are AND-combined.
- The age gate (``days_threshold``, else the default) is checked on the matched rule only: a too-young
  match leaves the song in Liked Songs and stops evaluation (it never falls through to later rules).
- A track with no ``added_at`` never satisfies an age gate (conservative: never moved).
- Genre/language conditions are simply false when enrichment is missing or empty.
- ``release_year_before`` is strict (year < N); ``release_year_after`` is strict (year > N).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
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


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def age_days(track: Track, now: datetime) -> float | None:
    """Days since the track was liked; naive datetimes are treated as UTC."""
    if track.added_at is None:
        return None
    return (_aware(now) - _aware(track.added_at)).total_seconds() / 86400


def resolve_days_threshold(rule: Rule, default_days_threshold: int) -> int:
    return rule.days_threshold if rule.days_threshold is not None else default_days_threshold


def _fold(value: str) -> str:
    return value.strip().casefold()


def check_key(track: Track, enrichment: Enrichment | None, key: str, wanted: Any) -> tuple[bool, Any, Any]:
    """Evaluate one match key. Returns (passed, actual_value_seen, what_matched)."""
    if key == "artist_in":
        names = {_fold(a.name) for a in track.artists}
        hits = [w for w in wanted if _fold(w) in names]
        return bool(hits), [a.name for a in track.artists], hits[0] if hits else None
    if key == "genre_contains":
        genres = list(enrichment.genres) if enrichment else []
        folded = [_fold(g) for g in genres]
        hit = next((w for w in wanted if _fold(w) and any(_fold(w) in g for g in folded)), None)
        return hit is not None, genres, hit
    if key == "language_in":
        lang = enrichment.language if enrichment else None
        ok = bool(lang) and _fold(lang) in {_fold(w) for w in wanted}
        return ok, lang, lang if ok else None
    if key in ("release_year_before", "release_year_after"):
        year = release_year(track.release_date, track.release_date_precision)
        if year is None:
            return False, None, None
        ok = year < wanted if key == "release_year_before" else year > wanted
        return ok, year, year if ok else None
    if key == "explicit":
        ok = bool(track.explicit) is wanted
        return ok, bool(track.explicit), wanted if ok else None
    if key == "track_name_contains":
        ok = bool(wanted.strip()) and _fold(wanted) in _fold(track.name)
        return ok, track.name, wanted if ok else None
    if key == "album_name_contains":
        ok = bool(wanted.strip()) and _fold(wanted) in _fold(track.album_name)
        return ok, track.album_name, wanted if ok else None
    return False, None, None  # unknown key: never silently ignore a condition


def _match_keys(
    track: Track, enrichment: Enrichment | None, match: dict[str, Any]
) -> dict[str, Any] | None:
    """Return {key: what matched} if every key is satisfied, else None."""
    matched: dict[str, Any] = {}
    for key, wanted in match.items():
        ok, _, hit = check_key(track, enrichment, key, wanted)
        if not ok:
            return None
        matched[key] = hit
    return matched


def explain(
    track: Track,
    enrichment: Enrichment | None,
    rules: Sequence[Rule],
    now: datetime,
    default_days_threshold: int = DEFAULT_DAYS_THRESHOLD,
) -> dict[str, Any]:
    """Rule-by-rule trace, in order, for one track (the dashboard's Explain drawer).

    Every rule's conditions are evaluated (so the dashboard can show shadowed rules), but ``stopped_here`` marks the
    rule that actually decided the song: the first enabled rule whose conditions pass. Later rules are 'not_reached'.
    """
    age = age_days(track, now)
    trace: list[dict[str, Any]] = []
    decided: str | None = None
    for rule in rules:
        threshold = resolve_days_threshold(rule, default_days_threshold)
        entry: dict[str, Any] = {"rule": rule.name, "enabled": rule.enabled, "threshold_days": threshold, "conditions": []}
        if not rule.enabled or not rule.match:
            entry["result"] = "skipped_disabled" if not rule.enabled else "skipped_empty"
            trace.append(entry)
            continue
        all_ok = True
        for key, wanted in rule.match.items():
            ok, actual, _ = check_key(track, enrichment, key, wanted)
            entry["conditions"].append({"key": key, "wanted": wanted, "actual": actual, "passed": ok})
            all_ok = all_ok and ok
        if decided is not None:
            entry["result"] = "not_reached_but_would_match" if all_ok else "not_reached"
        elif all_ok:
            decided = rule.name
            aged = age is not None and age >= threshold
            entry["result"] = "matched" if aged else "matched_too_young"
        else:
            entry["result"] = "failed"
        trace.append(entry)
    return {"trace": trace, "decided_by": decided, "age_days": age}


def first_match(
    track: Track,
    enrichment: Enrichment | None,
    rules: Sequence[Rule],
    now: datetime,
    default_days_threshold: int = DEFAULT_DAYS_THRESHOLD,
) -> Match | None:
    """First enabled rule whose *conditions* match, with ``aged`` saying whether its age gate is met.

    Conditions are matched first-match-wins; the age gate is checked only on that rule, so a too-young
    match stops evaluation instead of leaking into a later, broader rule (master decision 2).
    """
    age = age_days(track, now)
    for rule in rules:
        if not rule.enabled or not rule.match:
            continue
        matched = _match_keys(track, enrichment, rule.match)
        if matched is None:
            continue
        threshold = resolve_days_threshold(rule, default_days_threshold)
        aged = age is not None and age >= threshold
        return Match(rule=rule, matched=matched, age_days=age, threshold=threshold, aged=aged)
    return None


def evaluate(
    track: Track,
    enrichment: Enrichment | None,
    rules: Sequence[Rule],
    now: datetime,
    default_days_threshold: int = DEFAULT_DAYS_THRESHOLD,
) -> Match | None:
    """The rule to act on now, or None (no match, or matched but not old enough yet)."""
    match = first_match(track, enrichment, rules, now, default_days_threshold)
    return match if match is not None and match.aged else None
