"""Pure rule-matching logic (unit-testable, no I/O).

TODO: implement match evaluation per IMPLEMENTATION_PLAN.md §5.2 / §6.
No popularity-based keys — field removed from Spotify API.
"""

from __future__ import annotations

from typing import Any


def track_matches_rule(track: dict[str, Any], rule: dict[str, Any]) -> bool:
    """Return True if `track` satisfies all AND-combined keys in rule['match'].

    Supported match keys (planned):
      artist_in, genre_contains, release_year_before, release_year_after,
      explicit, track_name_contains, album_name_contains

    TODO: implement; treat missing match keys as no-op.
    """
    raise NotImplementedError("rules_engine.track_matches_rule — not implemented yet")


def first_matching_rule(
    track: dict[str, Any],
    rules: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Evaluate enabled rules in file order; return the first match, or None.

    TODO: skip rules with enabled: false; first match wins.
    """
    raise NotImplementedError("rules_engine.first_matching_rule — not implemented yet")


def resolve_days_threshold(
    rule: dict[str, Any] | None,
    default_days_threshold: int,
) -> int:
    """Return per-rule days_threshold override, else the global default.

    TODO: implement.
    """
    raise NotImplementedError("rules_engine.resolve_days_threshold — not implemented yet")
