"""In-memory simulated Spotify for offline tests of the apply / restore / sync flows.

``FakeSpotify`` mirrors the public surface of ``src.spotify_client.SpotifyClient`` that apply.py and sync.py use
(reads, ``*_batched`` writers returning ``BatchOutcome`` lists, ``contains_saved``, ``dry_run``), keeps real state
(a newest-first liked list plus playlists) and offers FAULT INJECTION knobs. Like the real writers, injected write
failures never raise: they come back as ``ok=False`` outcomes (later batches of the call are "skipped").

Knobs (all default to "healthy"):
  fail_call(method, nth)        the nth call (1-based) of ``method`` fails (every batch of it)
  fail_every(method)            every call of ``method`` fails
  fail_batch_of(method, batch, call=None)   batch number ``batch`` (1-based) of a call fails, later ones are skipped
  fail_playlist(pid)            adds to playlist ``pid`` fail
  lag = K                       after every committed write, the next K reads (of ``lag_kinds``) see the state as
                                it was before that write (read-after-write lag)
  vanish_after(method, uri)     after that method's call, ``uri`` silently disappears from Liked Songs
  ignore_removal.add(uri)       remove_saved_tracks_batched reports ok but the song stays liked
  contains_lies.add(uri)        contains_saved reports the opposite of the truth for ``uri``
  phantom_adds.add(uri)         playlist add reports ok but the song never shows up
  like_after(method, uri)       a brand-new like appears (top of Liked Songs) after that method's call
  raise_on[method] = exc        the method raises ``exc`` (a read blowing up, say)
  hooks[method] = fn(fake, *args)   runs at method entry (before any effect)
``calls`` is the ordered call log: ``(method_name, args)``; ``note(label)`` adds ``("note:label", ())``.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Callable, Iterable

from src.models import Artist, Playlist, Track
from src.spotify_client import (
    LIBRARY_BATCH,
    PLAYLIST_BATCH,
    PLAYLIST_ID_RE,
    BatchOutcome,
    DryRunError,
    SpotifyError,
    validate_track_uris,
)

BASE_NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def uri(n: int) -> str:
    return "spotify:track:" + f"{n:022d}"


def make_track(n: int, *, artist: str = "Bonobo", age_days: float = 60, name: str | None = None) -> Track:
    return Track(
        id=f"{n:022d}", uri=uri(n), name=name or f"Song {n}", artists=(Artist(f"a-{artist}", artist),),
        album_name="Album", release_date="2005-06-01", release_date_precision="day",
        added_at=BASE_NOW - timedelta(days=age_days),
    )


def make_move(track: Track, pid: str, *, position: str = "bottom", already: bool = False) -> dict[str, Any]:
    """A planner-shaped move dict (only the keys apply.py reads, plus a few informational ones)."""
    return {
        "track": track.name, "artist": ", ".join(a.name for a in track.artists), "uri": track.uri,
        "playlist": f"Playlist {pid}", "playlist_id": pid, "rule": "r", "matched": {}, "age_days": 60.0,
        "threshold_days": 14, "already_in_target": already,
        "original_added_at": track.added_at.isoformat() if track.added_at else None,
        "target_position": position,
    }


class FakeSpotify:
    def __init__(self, *, dry_run: bool = False):
        self.dry_run = dry_run
        self.catalog: dict[str, Track] = {}
        self.liked: list[str] = []  # newest first
        self.added: dict[str, datetime] = {}
        self.playlists: dict[str, Playlist] = {}
        self.items: dict[str, list[str]] = {}
        self.calls: list[tuple[str, tuple]] = []
        self.batch_sizes: list[tuple[str, int]] = []
        self.put_uris: list[str] = []  # every uri actually PUT to /me/library
        self.deleted_liked: list[str] = []  # every uri actually DELETEd from /me/library
        self.constructed: list[bool] = []  # dry_run flag of every from_env() through client_factory
        # knobs
        self.fail_nth: dict[str, set[int]] = {}
        self.fail_always: set[str] = set()
        self.fail_batches: dict[str, set[tuple[int | None, int]]] = {}
        self.fail_playlists: set[str] = set()
        self.lag = 0
        self.lag_kinds: set[str] = {"saved", "playlist", "contains"}
        self.vanish_rules: list[list[Any]] = []  # [method, uri, nth, done]
        self.like_rules: list[list[Any]] = []
        self.ignore_removal: set[str] = set()
        self.contains_lies: set[str] = set()
        self.phantom_adds: set[str] = set()
        self.raise_on: dict[str, BaseException] = {}
        self.hooks: dict[str, Callable[..., None]] = {}
        self._counts: Counter[str] = Counter()
        self._stale: SimpleNamespace | None = None
        self._lag_left = 0
        self._clock = BASE_NOW
        self._snap = 0

    # ---------------------------------------------------------------- building state

    def set_liked(self, tracks: Iterable[Track]) -> "FakeSpotify":
        for t in tracks:
            self.catalog[t.uri] = t
            self.added[t.uri] = t.added_at or self._tick()
            if t.uri not in self.liked:
                self.liked.append(t.uri)
        self._sort_liked()
        return self

    def like(self, track: Track) -> None:
        self.set_liked([track])

    def add_playlist(self, pid: str, name: str | None = None, items: Iterable[Track] = (), *, owned: bool = True) -> None:
        self.playlists[pid] = Playlist(id=pid, name=name or f"Playlist {pid}", owner_id="me" if owned else "other",
                                       owned=owned, collaborative=False)
        self.items[pid] = []
        for t in items:
            self.catalog[t.uri] = t
            self.items[pid].append(t.uri)

    def _sort_liked(self) -> None:
        self.liked.sort(key=lambda u: self.added[u], reverse=True)

    def _tick(self) -> datetime:
        self._clock += timedelta(seconds=1)
        return self._clock

    # ---------------------------------------------------------------- inspection helpers

    def liked_uris(self) -> set[str]:
        return set(self.liked)

    def playlist_uris(self, pid: str) -> list[str]:
        return list(self.items[pid])

    def names(self) -> list[str]:
        return [c[0] for c in self.calls]

    def count(self, method: str) -> int:
        return self.names().count(method)

    def first(self, method: str) -> int:
        return self.names().index(method)

    def write_calls(self) -> list[str]:
        writers = {"add_playlist_items_batched", "remove_playlist_items_batched", "save_tracks_batched",
                   "remove_saved_tracks_batched"}
        return [n for n in self.names() if n in writers]

    def note(self, label: str) -> None:
        self.calls.append((f"note:{label}", ()))

    # ---------------------------------------------------------------- knob helpers

    def fail_call(self, method: str, nth: int) -> None:
        self.fail_nth.setdefault(method, set()).add(nth)

    def fail_every(self, method: str) -> None:
        self.fail_always.add(method)

    def fail_batch_of(self, method: str, batch: int, call: int | None = None) -> None:
        self.fail_batches.setdefault(method, set()).add((call, batch))

    def fail_playlist(self, pid: str) -> None:
        self.fail_playlists.add(pid)

    def vanish_after(self, method: str, uri_: str, nth: int = 1) -> None:
        self.vanish_rules.append([method, uri_, nth, False])

    def like_after(self, method: str, track: Track | str, nth: int = 1) -> None:
        self.like_rules.append([method, track, nth, False])

    # ---------------------------------------------------------------- internals

    def _state(self) -> SimpleNamespace:
        return SimpleNamespace(liked=list(self.liked), items={k: list(v) for k, v in self.items.items()},
                               added=dict(self.added))

    def _view(self, kind: str) -> SimpleNamespace:
        if self._lag_left > 0 and kind in self.lag_kinds and self._stale is not None:
            self._lag_left -= 1
            return self._stale
        return self._state()

    def _begin_write(self) -> None:
        """Called right before a batch commits: remember the previous state for lagging reads."""
        if self.lag:
            self._stale = self._state()
            self._lag_left = self.lag

    def _enter(self, method: str, args: tuple) -> int:
        self._counts[method] += 1
        self.calls.append((method, args))
        if method in self.hooks:
            self.hooks[method](self, *args)
        if method in self.raise_on:
            raise self.raise_on[method]
        return self._counts[method]

    def _after(self, method: str, call_no: int) -> None:
        for rule in self.vanish_rules:
            if not rule[3] and rule[0] == method and call_no >= rule[2]:
                rule[3] = True
                if rule[1] in self.liked:
                    self.liked.remove(rule[1])
        for rule in self.like_rules:
            if not rule[3] and rule[0] == method and call_no >= rule[2]:
                rule[3] = True
                t = rule[1]
                if isinstance(t, str):
                    t = replace(make_track(int(t.rsplit(":", 1)[-1]) if t.rsplit(":", 1)[-1].isdigit() else 999999),
                                uri=t, id=t.rsplit(":", 1)[-1])
                t = replace(t, added_at=self._tick())
                self.set_liked([t])

    def _guard_write(self, what: str) -> None:
        if self.dry_run:
            raise DryRunError(f"dry-run: refusing to {what}")

    def _run(self, method: str, call_no: int, chunks: list[list[str]], commit: Callable[[list[str]], str | None],
             fails: Callable[[], bool] = lambda: False) -> list[BatchOutcome]:
        outs: list[BatchOutcome] = []
        failed = False
        for i, chunk in enumerate(chunks, 1):
            self.batch_sizes.append((method, len(chunk)))
            if failed:
                outs.append(BatchOutcome(tuple(chunk), False, "skipped after an earlier batch failed"))
                continue
            inject = (
                method in self.fail_always
                or call_no in self.fail_nth.get(method, ())
                or any(c in (None, call_no) and b == i for c, b in self.fail_batches.get(method, ()))
                or fails()
            )
            if inject:
                failed = True
                outs.append(BatchOutcome(tuple(chunk), False, "injected failure (HTTP 500)"))
                continue
            self._begin_write()
            try:
                snap = commit(chunk)
            except SpotifyError as exc:
                failed = True
                outs.append(BatchOutcome(tuple(chunk), False, str(exc)))
                continue
            outs.append(BatchOutcome(tuple(chunk), True, None, snap))
        self._after(method, call_no)
        return outs

    @staticmethod
    def _chunks(seq: list[str], size: int) -> list[list[str]]:
        return [seq[i:i + size] for i in range(0, len(seq), size)]

    def _next_snap(self) -> str:
        self._snap += 1
        return f"snap{self._snap}"

    # ---------------------------------------------------------------- reads

    def iter_saved_tracks(self):
        self._enter("iter_saved_tracks", ())
        v = self._view("saved")
        return iter([replace(self.catalog[u], added_at=v.added[u]) for u in v.liked])

    def iter_my_playlists(self):
        self._enter("iter_my_playlists", ())
        return iter(list(self.playlists.values()))

    def iter_playlist_items(self, playlist_id: str):
        if not isinstance(playlist_id, str) or not PLAYLIST_ID_RE.match(playlist_id):
            raise ValueError("invalid playlist id")
        self._enter("iter_playlist_items", (playlist_id,))
        if playlist_id not in self.items:
            raise SpotifyError(f"GET /playlists/{playlist_id}/items failed (HTTP 404): not found", 404)
        v = self._view("playlist")
        return iter([self.catalog[u] for u in v.items[playlist_id]])

    def _flags(self, uris: list[str], liked: Iterable[str]) -> dict[str, bool]:
        liked = set(liked)
        return {u: ((u in liked) != (u in self.contains_lies)) for u in uris}

    def contains_saved(self, uris: Iterable[str]) -> dict[str, bool]:
        uris = validate_track_uris(uris)
        self._enter("contains_saved", (tuple(uris),))
        v = self._view("contains")
        out: dict[str, bool] = {}
        for chunk in self._chunks(uris, LIBRARY_BATCH):
            self.batch_sizes.append(("contains_saved", len(chunk)))
            out.update(self._flags(chunk, v.liked))
        return out

    # ---------------------------------------------------------------- writers

    def add_playlist_items_batched(self, playlist_id: str, uris: Iterable[str], *, position: int | None = None) -> list[BatchOutcome]:
        self._guard_write("add playlist items")
        if not isinstance(playlist_id, str) or not PLAYLIST_ID_RE.match(playlist_id):
            raise ValueError("invalid playlist id")
        uris = validate_track_uris(uris)
        if position is not None and (not isinstance(position, int) or isinstance(position, bool) or position < 0):
            raise ValueError("position must be a non-negative integer")
        n = self._enter("add_playlist_items_batched", (playlist_id, tuple(uris), position))

        def commit(chunk: list[str]) -> str:
            if playlist_id not in self.items:
                raise SpotifyError("POST failed (HTTP 404): playlist not found", 404)
            real = [u for u in chunk if u not in self.phantom_adds]
            items = self.items[playlist_id]
            at = len(items) if position is None else min(position, len(items))
            items[at:at] = real
            for u in real:
                self.catalog.setdefault(u, make_track(int(u.rsplit(":", 1)[-1]) if u.rsplit(":", 1)[-1].isdigit() else 0))
            return self._next_snap()

        return self._run("add_playlist_items_batched", n, self._chunks(uris, PLAYLIST_BATCH), commit,
                         lambda: playlist_id in self.fail_playlists)

    def remove_playlist_items_batched(self, playlist_id: str, uris: Iterable[str], snapshot_id: str | None = None) -> list[BatchOutcome]:
        self._guard_write("remove playlist items")
        if not isinstance(playlist_id, str) or not PLAYLIST_ID_RE.match(playlist_id):
            raise ValueError("invalid playlist id")
        uris = validate_track_uris(uris)
        n = self._enter("remove_playlist_items_batched", (playlist_id, tuple(uris), snapshot_id))

        def commit(chunk: list[str]) -> str:
            if playlist_id not in self.items:
                raise SpotifyError("DELETE failed (HTTP 404): playlist not found", 404)
            self.items[playlist_id] = [u for u in self.items[playlist_id] if u not in set(chunk)]
            return self._next_snap()

        return self._run("remove_playlist_items_batched", n, self._chunks(uris, PLAYLIST_BATCH), commit)

    def save_tracks_batched(self, uris: Iterable[str], *, allow_resave: bool = False) -> list[BatchOutcome]:
        self._guard_write("save tracks")
        uris = validate_track_uris(uris)
        if not allow_resave and uris:  # like the real writer: consults contains (lies included, lag excluded)
            flags = self._flags(uris, self.liked)
            uris = [u for u in uris if not flags[u]]
        n = self._enter("save_tracks_batched", (tuple(uris), allow_resave))

        def commit(chunk: list[str]) -> None:
            for u in chunk:
                self.put_uris.append(u)
                if u not in self.catalog:
                    self.catalog[u] = make_track(int(u.rsplit(":", 1)[-1]) if u.rsplit(":", 1)[-1].isdigit() else 0)
                self.added[u] = self._tick()  # re-saving resets added_at
                if u not in self.liked:
                    self.liked.append(u)
            self._sort_liked()
            return None

        return self._run("save_tracks_batched", n, self._chunks(uris, LIBRARY_BATCH), commit)

    def remove_saved_tracks_batched(self, uris: Iterable[str]) -> list[BatchOutcome]:
        self._guard_write("remove saved tracks")
        uris = validate_track_uris(uris)
        n = self._enter("remove_saved_tracks_batched", (tuple(uris),))

        def commit(chunk: list[str]) -> None:
            for u in chunk:
                self.deleted_liked.append(u)
                if u not in self.ignore_removal and u in self.liked:
                    self.liked.remove(u)
            return None

        return self._run("remove_saved_tracks_batched", n, self._chunks(uris, LIBRARY_BATCH), commit)


# -------------------------------------------------------------------- helpers for tests


def build_world(n: int, playlists: Iterable[str] = ("P1",), *, base_age: float = 10, dry_run: bool = False) -> tuple[FakeSpotify, list[Track]]:
    """``n`` liked songs (Song 1 is the newest, then 10 days older each) and the given empty playlists."""
    fs = FakeSpotify(dry_run=dry_run)
    tracks = [make_track(i, age_days=base_age * i) for i in range(1, n + 1)]
    fs.set_liked(tracks)
    for pid in playlists:
        fs.add_playlist(pid)
    return fs, tracks


class JournalRecorder:
    """write_journal callback: records itself in the fake's call log, optionally raises."""

    def __init__(self, fake: FakeSpotify | None = None, raises: BaseException | None = None):
        self.fake, self.raises = fake, raises
        self.calls: list[list[dict[str, Any]]] = []
        self.liked_at_call: list[set[str]] = []
        self.playlists_at_call: list[dict[str, list[str]]] = []

    def __call__(self, journal: list[dict[str, Any]]) -> None:
        if self.fake is not None:
            self.fake.note("journal")
            self.liked_at_call.append(self.fake.liked_uris())
            self.playlists_at_call.append({k: list(v) for k, v in self.fake.items.items()})
        self.calls.append(list(journal))
        if self.raises is not None:
            raise self.raises


def client_factory(fake: FakeSpotify):
    """A stand-in for ``src.sync.SpotifyClient``: ``from_env`` hands out ``fake`` (recording the dry_run flag)."""

    class _Client:
        @classmethod
        def from_env(cls, *, dry_run: bool = True, environ=None, **kwargs):
            fake.constructed.append(dry_run)
            fake.dry_run = dry_run
            return fake

    return _Client
