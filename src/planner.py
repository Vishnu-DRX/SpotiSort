"""Pure planning: turn liked tracks + enrichment + config into an explainable list of intended moves.

No I/O and no Spotify calls. ``sync.py`` gathers the inputs and prints/writes the result.

Decisions per track (first-match-wins on conditions; the age gate applies to the matched rule only):
  move       -> conditions matched and the rule's age gate is met
  too_young  -> conditions matched but the song is not old enough yet: left in Liked Songs, evaluation stops
  no_match   -> nothing matched (optionally routed to ``fallback_playlist`` once older than the default threshold)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

from .models import Config, Enrichment, Match, Playlist, Rule, Track
from .rules_engine import age_days, first_match

FALLBACK_RULE = "(fallback_playlist)"


@dataclass
class Decision:
    track: Track
    kind: str  # move | too_young | no_match
    rule_name: str | None = None
    target_name: str | None = None
    create_missing: bool = False
    matched: dict[str, Any] = field(default_factory=dict)
    age_days: float | None = None
    threshold: int | None = None


def decide(
    track: Track,
    enrichment: Enrichment | None,
    config: Config,
    now: datetime,
    only_rule: str | None = None,
) -> Decision:
    m: Match | None = first_match(track, enrichment, config.rules, now, config.default_days_threshold)
    age = age_days(track, now)
    if m is not None:
        if only_rule and m.rule.name.casefold() != only_rule.casefold():
            return Decision(track, "no_match", age_days=age)  # excluded by --rule; precedence was still respected
        kind = "move" if m.aged else "too_young"
        return Decision(
            track, kind, m.rule.name, m.rule.target_playlist, m.rule.create_missing_playlists,
            dict(m.matched), m.age_days, m.threshold,
        )
    if config.fallback_playlist and not only_rule:
        threshold = config.default_days_threshold
        if age is not None and age >= threshold:
            return Decision(track, "move", FALLBACK_RULE, config.fallback_playlist, False, {}, age, threshold)
    return Decision(track, "no_match", age_days=age)


def resolve_target(name: str, playlists: Sequence[Playlist]) -> tuple[Playlist | None, str | None, str | None]:
    """(playlist, problem, warning). Only owned/collaborative playlists are usable; exact case-insensitive name."""
    folded = name.casefold().strip()
    same = [p for p in playlists if p.name.casefold().strip() == folded]
    usable = [p for p in same if p.usable]
    if len(usable) == 1:
        return usable[0], None, None
    if len(usable) > 1:
        return None, "ambiguous", f"target playlist name is ambiguous ({len(usable)} owned/collaborative matches): {name!r}"
    if same:
        return None, "not_writable", f"playlist {name!r} exists but is followed (not owned/collaborative); cannot write"
    return None, "missing", f"target playlist not found: {name!r}"


@dataclass
class Plan:
    moves: list[dict[str, Any]] = field(default_factory=list)
    skipped_playlist_missing: list[dict[str, Any]] = field(default_factory=list)
    skipped_too_young: list[dict[str, Any]] = field(default_factory=list)
    skipped_no_match: int = 0
    warnings: list[str] = field(default_factory=list)
    evaluated: int = 0


def build_plan(
    tracks: Iterable[Track],
    enrichments: Mapping[str, Enrichment],
    config: Config,
    now: datetime,
    playlists: Sequence[Playlist],
    membership: Mapping[str, set[str]] | None = None,
    *,
    only_rule: str | None = None,
    since: datetime | None = None,
    limit: int | None = None,
) -> Plan:
    """Explainable plan. ``membership`` maps playlist id -> track URIs already in it (for ``already_in_target``)."""
    membership = membership or {}
    plan = Plan()
    warned: set[str] = set()
    candidates = [t for t in tracks if since is None or (t.added_at is not None and t.added_at >= since)]
    candidates.sort(key=lambda t: (t.added_at is None, t.added_at))  # oldest liked first
    for t in candidates:
        plan.evaluated += 1
        d = decide(t, enrichments.get(t.id), config, now, only_rule)
        if d.kind == "no_match":
            plan.skipped_no_match += 1
            continue
        if d.kind == "too_young":
            plan.skipped_too_young.append({
                "track": t.name, "artist": t.artists[0].name if t.artists else "", "rule": d.rule_name,
                "age_days": round(d.age_days, 1) if d.age_days is not None else None, "threshold_days": d.threshold,
            })
            continue
        playlist, problem, warning = resolve_target(d.target_name, playlists)
        if playlist is None:
            if warning and warning not in warned:
                warned.add(warning)
                plan.warnings.append(warning)
            plan.skipped_playlist_missing.append({
                "track": t.name, "target_playlist": d.target_name, "rule": d.rule_name, "reason": problem,
                "would_create": bool(d.create_missing and problem == "missing"),
            })
            continue
        if limit is not None and len(plan.moves) >= limit:
            continue
        plan.moves.append({
            "track": t.name,
            "artist": ", ".join(a.name for a in t.artists),
            "uri": t.uri,
            "playlist": playlist.name,
            "playlist_id": playlist.id,
            "rule": d.rule_name,
            "matched": d.matched,
            "age_days": round(d.age_days, 1) if d.age_days is not None else None,
            "threshold_days": d.threshold,
            "already_in_target": t.uri in membership.get(playlist.id, set()),
            "original_added_at": t.added_at.isoformat() if t.added_at else None,
            "target_position": next((r.target_position for r in config.rules if r.name == d.rule_name), "bottom"),
        })
    # within a playlist songs are ordered newest liked first (master decision 14); stable across playlists
    plan.moves.sort(key=lambda m: m["original_added_at"] or "", reverse=True)
    return plan


def targets_needed(
    tracks: Iterable[Track],
    enrichments: Mapping[str, Enrichment],
    config: Config,
    now: datetime,
    playlists: Sequence[Playlist],
    only_rule: str | None = None,
) -> set[str]:
    """Playlist ids whose contents must be read (for already_in_target) given the plan's targets."""
    ids: set[str] = set()
    for t in tracks:
        d = decide(t, enrichments.get(t.id), config, now, only_rule)
        if d.kind == "move":
            p, _, _ = resolve_target(d.target_name, playlists)
            if p is not None:
                ids.add(p.id)
    return ids


@dataclass(frozen=True)
class InsertBatch:
    playlist_id: str
    uris: tuple[str, ...]
    position: int | None  # None = append at the bottom; 0 = insert at the top


def insert_batches(moves: Sequence[Mapping[str, Any]], batch_size: int = 100) -> list[InsertBatch]:
    """Turn planned moves into ordered playlist-insert calls (master decision 14).

    Per playlist the songs are newest-liked-first. ``bottom``: batches are appended in that order. ``top``: each
    batch is inserted at position 0, **oldest chunk first**, so after all batches the newest song is at index 0
    and the existing playlist order sits untouched below (inserting newest chunk first would invert the order).
    A playlist is either top or bottom per rule; mixing rules with different positions on one playlist is split
    per position group.
    """
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for m in moves:
        groups.setdefault((m["playlist_id"], m.get("target_position", "bottom")), []).append(m)
    out: list[InsertBatch] = []
    for (pid, position), items in groups.items():
        items = sorted(items, key=lambda m: m.get("original_added_at") or "", reverse=True)  # newest first
        chunks = [tuple(i["uri"] for i in items[k:k + batch_size]) for k in range(0, len(items), batch_size)]
        if position == "top":
            out += [InsertBatch(pid, c, 0) for c in reversed(chunks)]
        else:
            out += [InsertBatch(pid, c, None) for c in chunks]
    return out
