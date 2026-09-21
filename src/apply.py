"""Guarded apply and restore (cross-cutting rule 1: no liked song may be lost).

Order of operations for a plan (one run):
  1. guard: refuse in dry-run; refuse a plan larger than ``max_moves`` (before any call)
  2. add every planned song to its target playlist (per-batch results; a failed batch stops that playlist)
  3. re-read each target playlist (short poll, read-after-write lag) => ``confirmed`` = songs really there
  4. write the journal (callback must succeed) BEFORE any removal
  5. remove only ``confirmed`` songs from Liked Songs (per-batch results)
  6. verify with /me/library/contains and re-read Liked Songs and the target playlists; reconcile by ID sets:
       lost        = (liked_before - removed) - liked_after     must be empty (a song vanished)
       resurrected = removed & liked_after                       must be empty (removal did not stick)
     any lost song is re-added via PUT /me/library and the run ends non-zero.
Nothing here ever removes a song that was not confirmed in its target playlist.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .planner import insert_batches
from .spotify_client import SpotifyError, validate_track_uris

EXIT_OK = 0
EXIT_FAILED = 6  # partial failure, nothing lost
EXIT_TOO_MANY = 4
EXIT_MISMATCH = 5  # reconcile mismatch (a song vanished or a removal did not stick)
DEFAULT_MAX_MOVES = 50
HARD_MAX_MOVES = 500  # --max-moves may not be raised above this
POLL_TRIES = 5
POLL_INTERVAL = 1.0


class TooManyMoves(RuntimeError):
    pass


@dataclass
class ApplyResult:
    exit_code: int = EXIT_OK
    liked_before: int = 0
    liked_after: int | None = None
    confirmed: list[str] = field(default_factory=list)  # songs verified present in their target playlist
    removed: list[str] = field(default_factory=list)  # songs verified gone from Liked Songs
    still_liked: list[str] = field(default_factory=list)  # confirmed but the removal did not stick (safe: in both places)
    journal: list[dict[str, Any]] = field(default_factory=list)
    batches: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    reconcile: dict[str, Any] = field(default_factory=dict)
    aborted: str | None = None

    @property
    def ok(self) -> bool:
        return self.exit_code == EXIT_OK


def _batch_rows(kind: str, target: str, outcomes: Iterable[Any]) -> list[dict[str, Any]]:
    return [
        {"kind": kind, "target": target, "size": len(o.uris), "committed": o.ok, "error": o.error}
        for o in outcomes
    ]


def _poll(read: Callable[[], Any], done: Callable[[Any], bool], sleep: Callable[[float], None],
          tries: int = POLL_TRIES, interval: float = POLL_INTERVAL) -> Any:
    """Read until ``done`` or out of tries; returns the last read (GETs can lag right after a write)."""
    value = read()
    for _ in range(tries - 1):
        if done(value):
            break
        sleep(interval)
        value = read()
    return value


def apply_moves(
    client: Any,
    moves: Sequence[Mapping[str, Any]],
    *,
    liked_uris_before: set[str],
    write_journal: Callable[[list[dict[str, Any]]], None],
    max_moves: int = DEFAULT_MAX_MOVES,
    sleep: Callable[[float], None] = time.sleep,
) -> ApplyResult:
    """Execute a plan safely. ``moves`` are planner move dicts (uri, playlist_id, target_position, ...)."""
    if getattr(client, "dry_run", True):
        raise RuntimeError("apply_moves refuses to run with a dry-run client")
    if len(moves) > max_moves:
        raise TooManyMoves(f"plan has {len(moves)} moves, above the --max-moves cap of {max_moves}; nothing was done")
    validate_track_uris(m["uri"] for m in moves)
    uris_in_plan = [m["uri"] for m in moves]
    if len(set(uris_in_plan)) != len(uris_in_plan):
        raise ValueError("plan lists the same song more than once; refusing to apply an ambiguous plan")

    res = ApplyResult(liked_before=len(liked_uris_before))
    # only songs that are actually liked right now can be "moved"
    live = [m for m in moves if m["uri"] in liked_uris_before]
    for m in moves:
        if m["uri"] not in liked_uris_before:
            res.warnings.append("a planned song is no longer in Liked Songs; skipped")
    if not live:
        res.liked_after = res.liked_before
        return res

    # 2. add to targets (per playlist, honouring position + newest-first ordering)
    wanted: dict[str, set[str]] = {}
    already = {m["uri"] for m in live if m.get("already_in_target")}
    to_add = [m for m in live if not m.get("already_in_target")]
    for m in live:
        wanted.setdefault(m["playlist_id"], set()).add(m["uri"])
    failed_playlists: set[str] = set()
    for batch in insert_batches(to_add):
        if batch.playlist_id in failed_playlists:  # keep a playlist's order free of holes: stop after its first failure
            res.batches.append({"kind": "add_to_playlist", "target": batch.playlist_id, "size": len(batch.uris),
                                "committed": False, "error": "skipped after an earlier batch for this playlist failed"})
            continue
        outcomes = client.add_playlist_items_batched(batch.playlist_id, batch.uris, position=batch.position)
        res.batches += _batch_rows("add_to_playlist", batch.playlist_id, outcomes)
        for o in outcomes:
            if not o.ok:
                res.errors.append(f"add to playlist failed: {o.error}")
                failed_playlists.add(batch.playlist_id)

    try:
        return _confirm_journal_remove_reconcile(client, res, live, wanted, liked_uris_before, write_journal, sleep)
    except SpotifyError as exc:
        # A read failed mid-run. Whatever was written is on disk (journal first); report instead of crashing.
        removed_something = any(b["kind"] == "remove_from_liked" for b in res.batches)
        res.errors.append(f"run interrupted by an API error ({type(exc).__name__}): {exc}")
        res.aborted = "interrupted; verify Liked Songs and use the journal/restore command if needed"
        res.exit_code = EXIT_MISMATCH if removed_something else EXIT_FAILED
        if removed_something:
            res.reconcile = {"ok": False, "error": "reconcile could not complete", "liked_before": res.liked_before}
        if res.liked_after is None:
            res.liked_after = res.liked_before if not removed_something else None
        return res


def _confirm_journal_remove_reconcile(
    client: Any,
    res: ApplyResult,
    live: Sequence[Mapping[str, Any]],
    wanted: dict[str, set[str]],
    liked_uris_before: set[str],
    write_journal: Callable[[list[dict[str, Any]]], None],
    sleep: Callable[[float], None],
) -> ApplyResult:
    # 3. confirm by re-reading the targets
    confirmed: set[str] = set()
    for pid, uris in wanted.items():
        def read(pid=pid) -> set[str]:
            return {t.uri for t in client.iter_playlist_items(pid)}

        present = _poll(read, lambda p, uris=uris: uris <= p, sleep)
        confirmed |= uris & present
        missing = uris - present
        if missing:
            res.errors.append(f"{len(missing)} song(s) not confirmed in target playlist; they stay in Liked Songs")
    res.confirmed = sorted(confirmed)
    if not confirmed:
        res.exit_code = EXIT_FAILED if res.errors else EXIT_OK
        res.liked_after = res.liked_before
        return res

    # 4. journal BEFORE any removal (a failing journal aborts the removal)
    by_uri = {m["uri"]: m for m in live}
    res.journal = [
        {"uri": u, "name": by_uri[u]["track"], "artists": by_uri[u]["artist"],
         "original_added_at": by_uri[u]["original_added_at"], "target_playlist_id": by_uri[u]["playlist_id"],
         "already_in_target": bool(by_uri[u].get("already_in_target"))}
        for u in sorted(confirmed)
    ]
    try:
        write_journal(res.journal)
    except Exception as exc:  # noqa: BLE001 - any failure to persist the journal must stop the removal
        res.aborted = f"journal could not be written ({type(exc).__name__}); nothing was removed"
        res.errors.append(res.aborted)
        res.exit_code = EXIT_FAILED
        res.liked_after = res.liked_before
        return res

    # fresh baseline right before removal: the user may have liked/unliked songs while the run was preparing
    baseline = {t.uri for t in client.iter_saved_tracks()}
    to_remove = sorted(confirmed & baseline)
    if len(to_remove) != len(confirmed):
        res.warnings.append("a confirmed song was no longer in Liked Songs at removal time; left alone")
    if not to_remove:
        res.liked_after = len(baseline)
        return res

    # 5. remove only confirmed songs from Liked Songs
    outcomes = client.remove_saved_tracks_batched(to_remove)
    res.batches += _batch_rows("remove_from_liked", "liked", outcomes)
    for o in outcomes:
        if not o.ok:
            res.errors.append(f"remove from Liked Songs failed: {o.error}")

    # 6. verify + reconcile by ID sets
    targets = set(to_remove)
    flags = _poll(lambda: client.contains_saved(to_remove), lambda f: not any(f.values()), sleep)
    after = _poll(lambda: {t.uri for t in client.iter_saved_tracks()}, lambda a: not (targets & a), sleep)
    if targets - after != {u for u, liked in flags.items() if not liked}:
        res.warnings.append("contains() and the Liked Songs list disagreed after removal (read-after-write lag); the list was used")
    removed = targets - after  # authoritative: what is really gone from Liked Songs
    lost = (baseline - targets) - after  # a song we did NOT remove has vanished
    resurrected = targets & after  # a removal that did not stick (song is safe: in playlist and still liked)
    newly = after - baseline

    # every song we removed from Liked Songs must still be in its target playlist (re-read after the removal)
    gone_from_target: set[str] = set()
    for pid, uris in wanted.items():
        mine = uris & removed
        if mine:
            present = _poll(lambda pid=pid: {t.uri for t in client.iter_playlist_items(pid)}, lambda p, m=mine: m <= p, sleep)
            gone_from_target |= mine - present
    res.removed = sorted(removed)
    res.still_liked = sorted(resurrected)
    res.liked_after = len(after)
    res.reconcile = {
        "liked_before": res.liked_before,
        "removed": len(removed),
        "expected_after": len(baseline) - len(removed) + len(newly),
        "actual_after": len(after),
        "new_likes_during_run": len(newly),
        "lost": len(lost),
        "resurrected": len(resurrected),
        "gone_from_target": len(gone_from_target),
        "ok": not lost and not resurrected and not gone_from_target,
    }
    rescue = sorted(lost | gone_from_target)
    if rescue:
        res.exit_code = EXIT_MISMATCH
        res.aborted = "reconcile mismatch: song(s) vanished from Liked Songs or their playlist; re-adding to Liked Songs"
        res.errors.append(res.aborted)
        try:
            outcomes = client.save_tracks_batched(rescue)  # skips songs that are already liked (no date reset)
            res.batches += _batch_rows("re_add_lost", "liked", outcomes)
            if any(not o.ok for o in outcomes):
                res.errors.append("could not re-add every lost song; see journal / restore")
        except SpotifyError as exc:
            res.errors.append(f"re-add of lost songs failed: {exc}")
    elif resurrected and any(not o.ok for o in outcomes):
        res.exit_code = EXIT_FAILED  # the removal call itself failed and said so: songs are in both places, nothing lost
    elif resurrected:
        res.exit_code = EXIT_MISMATCH
        res.aborted = "reconcile mismatch: a removal did not stick (song is in Liked Songs and in its playlist; nothing lost)"
        res.errors.append(res.aborted)
    elif res.errors:
        res.exit_code = EXIT_FAILED
    return res


# ---------------------------------------------------------------- restore


def load_journal(path: str | Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    journal = data.get("journal") if isinstance(data, dict) else None
    if not isinstance(journal, list):
        raise ValueError(f"{path} has no journal")
    if data.get("mode") != "apply" or data.get("dry_run") is not False:
        raise ValueError(f"{path} is not the log of an apply run (dry-run journals list songs that were never moved)")
    for e in journal:
        if not isinstance(e, dict) or "uri" not in e:
            raise ValueError("journal entry without a uri")
        if not isinstance(e.get("target_playlist_id"), str) or not e["target_playlist_id"]:
            raise ValueError("journal entry without a target_playlist_id")
    validate_track_uris(e["uri"] for e in journal)
    return journal


def restore_from_log(
    client: Any,
    path: str | Path,
    *,
    remove_from_targets: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> ApplyResult:
    """Re-add journaled songs to Liked Songs (re-saving resets their ``added_at`` to now; the journal keeps the original).

    Songs already liked are skipped. ``remove_from_targets`` additionally removes them from the playlist they were
    moved to (used to clean up test runs); off by default so a restore never deletes anything from a playlist.
    """
    if getattr(client, "dry_run", True):
        raise RuntimeError("restore refuses to run with a dry-run client")
    journal = load_journal(path)
    res = ApplyResult()
    uris = [e["uri"] for e in journal]
    liked_before = {t.uri for t in client.iter_saved_tracks()}
    res.liked_before = len(liked_before)
    todo = [u for u in uris if u not in liked_before]
    if todo:
        outcomes = client.save_tracks_batched(todo)
        res.batches += _batch_rows("restore_to_liked", "liked", outcomes)
        for o in outcomes:
            if not o.ok:
                res.errors.append(f"restore failed: {o.error}")
    flags = _poll(lambda: client.contains_saved(uris), lambda f: all(f.values()), sleep)
    res.removed = []
    res.confirmed = sorted(u for u, liked in flags.items() if liked)  # now liked again
    missing = [u for u, liked in flags.items() if not liked]
    if missing:
        res.errors.append(f"{len(missing)} song(s) are still not in Liked Songs after restore")
    if remove_from_targets and not missing:
        by_playlist: dict[str, list[str]] = {}
        for e in journal:
            if e.get("already_in_target"):  # it was in the playlist before the run: never remove it from there
                continue
            by_playlist.setdefault(e["target_playlist_id"], []).append(e["uri"])
        for pid, ids in by_playlist.items():
            outcomes = client.remove_playlist_items_batched(pid, ids)
            res.batches += _batch_rows("remove_from_target", pid, outcomes)
            for o in outcomes:
                if not o.ok:
                    res.errors.append(f"could not remove from target playlist: {o.error}")
    res.liked_after = len({t.uri for t in client.iter_saved_tracks()})
    res.exit_code = EXIT_FAILED if res.errors else EXIT_OK
    return res
