"""Guarded apply flow (src/apply.py) against the in-memory simulated Spotify (tests/fakes.py). Fully offline."""

from __future__ import annotations

import random

import pytest

from fakes import FakeSpotify, JournalRecorder, build_world, make_move, make_track, uri
from src import apply as ap
from src import planner
from src.apply import (
    EXIT_FAILED,
    EXIT_MISMATCH,
    EXIT_OK,
    TooManyMoves,
    apply_moves,
)
from src.spotify_client import SpotifyError


def nosleep(_s):
    pass


def run(fs, moves, *, before=None, journal=None, max_moves=50, sleep=nosleep):
    j = journal if journal is not None else JournalRecorder(fs)
    b = set(fs.liked) if before is None else before
    res = apply_moves(fs, moves, liked_uris_before=b, write_journal=j, max_moves=max_moves, sleep=sleep)
    return res, j


def force_batch(monkeypatch, size):
    monkeypatch.setattr(ap, "insert_batches", lambda moves: planner.insert_batches(moves, batch_size=size))


def mv(tracks, pid="P1", **kw):
    return [make_move(t, pid, **kw) for t in tracks]


def uris_of(tracks):
    return [t.uri for t in tracks]


def safe(fs, uri_, pid):
    """The core invariant for one song: still liked OR in the playlist it went to."""
    return uri_ in fs.liked or uri_ in fs.items[pid]


# ---------------------------------------------------------------- happy path


def test_happy_path_end_state():
    fs, t = build_world(4)
    res, _ = run(fs, mv(t[:3]))
    assert res.exit_code == EXIT_OK and res.ok and res.errors == [] and res.aborted is None
    assert fs.liked == [uri(4)]
    assert fs.playlist_uris("P1") == [uri(1), uri(2), uri(3)]  # bottom append, newest liked first
    assert res.confirmed == res.removed == sorted(uris_of(t[:3]))
    assert res.still_liked == []


def test_happy_path_reconcile_dict():
    fs, t = build_world(4)
    res, _ = run(fs, mv(t[:3]))
    assert res.reconcile == {
        "liked_before": 4, "removed": 3, "expected_after": 1, "actual_after": 1,
        "new_likes_during_run": 0, "lost": 0, "resurrected": 0, "ok": True,
    }


def test_liked_before_and_after_counts():
    fs, t = build_world(6)
    res, _ = run(fs, mv(t[:2]))
    assert res.liked_before == 6 and res.liked_after == 4 == len(fs.liked)


def test_journal_entries_shape_and_content():
    fs, t = build_world(3)
    res, j = run(fs, mv(t[:2]))
    assert len(j.calls) == 1 and j.calls[0] == res.journal
    assert [e["uri"] for e in res.journal] == sorted(uris_of(t[:2]))
    for e in res.journal:
        assert set(e) == {"uri", "name", "artists", "original_added_at", "target_playlist_id", "already_in_target"}
        assert e["target_playlist_id"] == "P1" and e["original_added_at"]
    assert res.journal[0]["name"] == "Song 1" and res.journal[0]["artists"] == "Bonobo"


def test_batch_rows_are_reported():
    fs, t = build_world(3)
    res, _ = run(fs, mv(t))
    kinds = [(b["kind"], b["target"], b["size"], b["committed"]) for b in res.batches]
    assert kinds == [("add_to_playlist", "P1", 3, True), ("remove_from_liked", "liked", 3, True)]


def test_two_playlists_both_proceed():
    fs, t = build_world(4, ("P1", "P2"))
    res, _ = run(fs, mv(t[:2], "P1") + mv(t[2:], "P2"))
    assert res.ok and fs.liked == []
    assert set(fs.items["P1"]) == set(uris_of(t[:2])) and set(fs.items["P2"]) == set(uris_of(t[2:]))
    assert {j["target_playlist_id"] for j in res.journal} == {"P1", "P2"}


def test_empty_plan_touches_nothing():
    fs, _ = build_world(3)
    res, j = run(fs, [])
    assert res.ok and res.liked_before == res.liked_after == 3
    assert fs.calls == [] and j.calls == [] and res.journal == []


def test_plan_of_songs_no_longer_liked_is_skipped():
    fs, t = build_world(2)
    ghost = make_track(77)
    res, j = run(fs, mv([ghost]))
    assert res.ok and len(res.warnings) == 1 and fs.write_calls() == [] and j.calls == []
    assert fs.items["P1"] == [] and len(fs.liked) == 2


def test_only_liked_songs_are_moved():
    fs, t = build_world(3)
    ghost = make_track(77)
    res, _ = run(fs, mv([t[0], ghost, t[1]]))
    assert res.ok and len(res.warnings) == 1
    assert uri(77) not in fs.items["P1"] and set(fs.items["P1"]) == {uri(1), uri(2)}
    add_args = [a for n, a in fs.calls if n == "add_playlist_items_batched"]
    assert all(uri(77) not in a[1] for a in add_args)
    assert fs.liked == [uri(3)]


def test_unmentioned_liked_songs_are_never_touched():
    fs, t = build_world(6)
    run(fs, mv(t[:2]))
    removed_calls = [a for n, a in fs.calls if n == "remove_saved_tracks_batched"]
    assert set(removed_calls[0][0]) == {uri(1), uri(2)}
    assert set(fs.liked) == {uri(i) for i in range(3, 7)}


def test_max_moves_cap_raises_before_any_call():
    fs, t = build_world(5)
    j = JournalRecorder(fs)
    with pytest.raises(TooManyMoves):
        apply_moves(fs, mv(t[:3]), liked_uris_before=set(fs.liked), write_journal=j, max_moves=2, sleep=nosleep)
    assert fs.calls == [] and j.calls == [] and len(fs.liked) == 5


def test_max_moves_counts_planned_moves_even_if_not_liked():
    fs, t = build_world(1)
    with pytest.raises(TooManyMoves):
        run(fs, mv([t[0], make_track(70), make_track(71)]), max_moves=2)
    assert fs.calls == []


def test_exactly_max_moves_is_allowed():
    fs, t = build_world(3)
    res, _ = run(fs, mv(t), max_moves=3)
    assert res.ok and fs.liked == []


def test_default_cap_is_50():
    assert ap.DEFAULT_MAX_MOVES == 50
    fs, t = build_world(51)
    with pytest.raises(TooManyMoves):
        apply_moves(fs, mv(t), liked_uris_before=set(fs.liked), write_journal=JournalRecorder(fs), sleep=nosleep)
    assert fs.calls == []


def test_dry_run_client_refused():
    fs, t = build_world(2, dry_run=True)
    with pytest.raises(RuntimeError, match="dry-run"):
        run(fs, mv(t))
    assert fs.calls == [] and len(fs.liked) == 2


def test_client_without_dry_run_attribute_is_treated_as_dry_run():
    with pytest.raises(RuntimeError):
        apply_moves(object(), [], liked_uris_before=set(), write_journal=lambda j: None)


def test_non_track_uri_rejected_before_any_call():
    fs, t = build_world(2)
    bad = make_move(t[0], "P1")
    bad["uri"] = "spotify:album:" + "a" * 22
    with pytest.raises(ValueError):
        run(fs, [bad])
    assert fs.calls == []


# ---------------------------------------------------------------- already_in_target


def test_already_in_target_skips_add_but_still_removes():
    fs, t = build_world(3)
    fs.items["P1"].append(t[0].uri)
    res, _ = run(fs, mv([t[0]], already=True))
    assert res.ok and fs.count("add_playlist_items_batched") == 0
    assert fs.playlist_uris("P1") == [uri(1)] and uri(1) not in fs.liked


def test_already_in_target_mixed_adds_only_the_rest():
    fs, t = build_world(3)
    fs.items["P1"].append(t[0].uri)
    res, _ = run(fs, [make_move(t[0], "P1", already=True), make_move(t[1], "P1")])
    add_args = [a for n, a in fs.calls if n == "add_playlist_items_batched"]
    assert len(add_args) == 1 and add_args[0][1] == (uri(2),)
    assert res.ok and fs.liked == [uri(3)] and sorted(fs.items["P1"]) == [uri(1), uri(2)]


def test_stale_already_in_target_flag_is_not_trusted():
    fs, t = build_world(2)  # flag says it is there, playlist is empty
    res, j = run(fs, mv([t[0]], already=True))
    assert res.exit_code == EXIT_FAILED and uri(1) in fs.liked
    assert fs.count("remove_saved_tracks_batched") == 0 and j.calls == []
    assert any("not confirmed" in e for e in res.errors)


def test_duplicate_moves_are_refused_before_any_call():
    fs, t = build_world(3)
    with pytest.raises(ValueError, match="more than once"):
        run(fs, mv([t[0], t[0], t[1]]))
    assert fs.calls == [] and uri(1) in fs.liked


def test_duplicate_conflicting_moves_are_refused():
    fs, t = build_world(2, ("P1", "P2"))
    with pytest.raises(ValueError):
        run(fs, [make_move(t[0], "P2"), make_move(t[0], "P1")])
    assert fs.calls == []


# ---------------------------------------------------------------- ordering


def test_journal_written_before_first_remove():
    fs, t = build_world(3)
    run(fs, mv(t))
    assert fs.first("note:journal") < fs.first("remove_saved_tracks_batched")


def test_journal_sees_songs_still_liked_and_already_in_playlist():
    fs, t = build_world(3)
    _, j = run(fs, mv(t))
    assert j.liked_at_call[0] == {uri(1), uri(2), uri(3)}
    assert set(j.playlists_at_call[0]["P1"]) == {uri(1), uri(2), uri(3)}


def test_no_remove_before_song_confirmed_present_in_playlist():
    fs, t = build_world(3)
    seen = []

    def hook(f, uris):
        seen.append(uris)
        assert all(u in f.items["P1"] for u in uris)

    fs.hooks["remove_saved_tracks_batched"] = hook
    run(fs, mv(t))
    assert len(seen) == 1


def test_full_call_order():
    fs, t = build_world(2)
    run(fs, mv(t))
    order = [n for n in fs.names() if n != "contains_saved"]
    assert order == ["add_playlist_items_batched", "iter_playlist_items", "note:journal",
                     "remove_saved_tracks_batched", "iter_saved_tracks"]
    assert fs.first("remove_saved_tracks_batched") < fs.first("contains_saved")


def test_adds_before_any_remove_across_playlists():
    fs, t = build_world(4, ("P1", "P2"))
    run(fs, mv(t[:2], "P1") + mv(t[2:], "P2"))
    names = fs.names()
    last_add = max(i for i, n in enumerate(names) if n == "add_playlist_items_batched")
    assert last_add < names.index("note:journal") < names.index("remove_saved_tracks_batched")


def test_remove_called_once_with_only_confirmed_songs():
    fs, t = build_world(4)
    fs.phantom_adds.add(uri(2))
    run(fs, mv(t))
    rem = [a for n, a in fs.calls if n == "remove_saved_tracks_batched"]
    assert len(rem) == 1 and set(rem[0][0]) == {uri(1), uri(3), uri(4)}


# ---------------------------------------------------------------- add failures


def test_add_fails_for_one_playlist_others_proceed():
    fs, t = build_world(4, ("P1", "P2"))
    fs.fail_playlist("P1")
    res, _ = run(fs, mv(t[:2], "P1") + mv(t[2:], "P2"))
    assert res.exit_code == EXIT_FAILED
    assert {uri(1), uri(2)} <= fs.liked_uris() and fs.items["P1"] == []
    assert fs.liked_uris() == {uri(1), uri(2)} and set(fs.items["P2"]) == {uri(3), uri(4)}
    assert any("add to playlist failed" in e for e in res.errors)
    assert res.removed == sorted([uri(3), uri(4)])


def test_every_add_fails_nothing_removed_nothing_journaled():
    fs, t = build_world(3)
    fs.fail_every("add_playlist_items_batched")
    res, j = run(fs, mv(t))
    assert res.exit_code == EXIT_FAILED and res.removed == [] and res.confirmed == []
    assert fs.count("remove_saved_tracks_batched") == 0 and j.calls == []
    assert len(fs.liked) == 3 and res.liked_after == 3


def test_add_fails_midway_only_committed_songs_removed(monkeypatch):
    force_batch(monkeypatch, 3)
    fs, t = build_world(8)
    fs.fail_call("add_playlist_items_batched", 2)  # apply issues one add call per InsertBatch: chunk 2 fails
    res, _ = run(fs, mv(t[:7]))
    assert res.exit_code == EXIT_FAILED
    committed = set(fs.playlist_uris("P1"))
    assert {uri(1), uri(2), uri(3)} <= committed and not committed & {uri(4), uri(5), uri(6)}
    assert set(res.removed) == committed  # exactly the committed + confirmed songs left Liked Songs
    assert fs.liked_uris() == {uri(i) for i in range(1, 9)} - committed
    assert uri(4) in fs.liked and uri(5) in fs.liked and uri(6) in fs.liked
    assert [b["committed"] for b in res.batches if b["kind"] == "add_to_playlist"][:2] == [True, False]
    assert any("not confirmed" in e for e in res.errors)


def test_add_fails_midway_top_position_only_committed_removed(monkeypatch):
    force_batch(monkeypatch, 3)
    fs, t = build_world(8)
    fs.fail_call("add_playlist_items_batched", 2)
    res, _ = run(fs, mv(t[:7], position="top"))
    committed = set(fs.playlist_uris("P1"))
    assert uri(7) in committed and not committed & {uri(4), uri(5), uri(6)}  # call 1 = oldest chunk; call 2 failed
    assert set(res.removed) == committed and res.exit_code == EXIT_FAILED
    assert all(safe(fs, u, "P1") for u in uris_of(t))


def test_failed_add_chunk_stops_later_chunks_for_that_playlist(monkeypatch):
    force_batch(monkeypatch, 3)
    fs, t = build_world(8)
    fs.fail_call("add_playlist_items_batched", 2)
    run(fs, mv(t[:7]))
    assert fs.count("add_playlist_items_batched") == 2


def test_more_than_100_moves_real_batch_sizes():
    fs, t = build_world(130)
    res, _ = run(fs, mv(t), max_moves=200)
    assert res.ok and fs.liked == [] and len(fs.playlist_uris("P1")) == 130
    assert [s for n, s in fs.batch_sizes if n == "add_playlist_items_batched"] == [100, 30]
    assert [s for n, s in fs.batch_sizes if n == "remove_saved_tracks_batched"] == [40, 40, 40, 10]


def test_more_than_100_moves_second_add_batch_fails():
    fs, t = build_world(140)
    fs.fail_call("add_playlist_items_batched", 2)
    res, _ = run(fs, mv(t[:130]), max_moves=200)
    assert res.exit_code == EXIT_FAILED
    assert len(fs.playlist_uris("P1")) == 100 and len(res.removed) == 100
    assert len(fs.liked) == 40
    assert [s for n, s in fs.batch_sizes if n == "remove_saved_tracks_batched"] == [40, 40, 20]


def test_song_never_appears_in_playlist_is_not_removed():
    fs, t = build_world(4)
    fs.phantom_adds.add(uri(2))
    res, _ = run(fs, mv(t[:3]))
    assert res.exit_code == EXIT_FAILED
    assert uri(2) in fs.liked and uri(2) not in res.removed and uri(2) not in res.confirmed
    assert fs.liked_uris() == {uri(2), uri(4)}
    assert any("1 song(s) not confirmed" in e for e in res.errors)


def test_all_phantom_adds_nothing_confirmed():
    fs, t = build_world(3)
    fs.phantom_adds |= {uri(1), uri(2), uri(3)}
    res, j = run(fs, mv(t))
    assert res.exit_code == EXIT_FAILED and res.confirmed == [] and j.calls == []
    assert fs.count("remove_saved_tracks_batched") == 0 and len(fs.liked) == 3


# ---------------------------------------------------------------- read-after-write lag


@pytest.mark.parametrize("lag", [0, 1, 2, 3, 4])
def test_lag_within_poll_window_still_confirmed(lag):
    fs, t = build_world(3)
    fs.lag = lag
    sleeps = []
    res, _ = run(fs, mv(t), sleep=sleeps.append)
    assert res.ok and fs.liked == [] and len(sleeps) >= lag
    assert res.removed == sorted(uris_of(t))


@pytest.mark.parametrize("lag", [5, 6, 9])
def test_lag_longer_than_poll_not_confirmed_not_removed(lag):
    fs, t = build_world(3)
    fs.lag = lag
    fs.lag_kinds = {"playlist"}
    sleeps = []
    res, j = run(fs, mv(t), sleep=sleeps.append)
    assert res.exit_code == EXIT_FAILED and res.confirmed == [] and res.removed == []
    assert fs.count("remove_saved_tracks_batched") == 0 and j.calls == []
    assert len(fs.liked) == 3 and len(sleeps) == ap.POLL_TRIES - 1
    assert sorted(fs.playlist_uris("P1")) == sorted(uris_of(t))  # they were added; we just could not see it


@pytest.mark.parametrize("lag", [1, 3, 4])
def test_lag_on_contains_after_removal_resolves(lag):
    fs, t = build_world(3)
    fs.lag, fs.lag_kinds = lag, {"contains"}
    res, _ = run(fs, mv(t))
    assert res.ok and res.removed == sorted(uris_of(t)) and fs.liked == []


@pytest.mark.parametrize("lag", [5, 8])
def test_lag_on_contains_beyond_poll_never_loses_a_song(lag):
    fs, t = build_world(3)
    fs.lag, fs.lag_kinds = lag, {"contains"}
    res, _ = run(fs, mv(t))
    assert all(safe(fs, u, "P1") for u in uris_of(t))
    assert res.exit_code in (EXIT_OK, EXIT_MISMATCH)


# ---------------------------------------------------------------- journal failure


@pytest.mark.parametrize("exc", [OSError("disk full"), PermissionError("ro"), ValueError("bad"), RuntimeError("x")])
def test_journal_writer_raising_removes_nothing(exc):
    fs, t = build_world(3)
    j = JournalRecorder(fs, raises=exc)
    res, _ = run(fs, mv(t), journal=j)
    assert res.exit_code == EXIT_FAILED and res.aborted and "journal" in res.aborted
    assert fs.count("remove_saved_tracks_batched") == 0
    assert len(fs.liked) == 3 and res.removed == [] and res.liked_after == 3
    assert len(fs.playlist_uris("P1")) == 3  # added, harmless


# ---------------------------------------------------------------- removal failures / reconcile


def test_remove_batch_fails_songs_stay_liked_nothing_lost():
    fs, t = build_world(3)
    fs.fail_every("remove_saved_tracks_batched")
    res, _ = run(fs, mv(t))
    assert res.exit_code == EXIT_FAILED and res.removed == []
    assert res.still_liked == sorted(uris_of(t)) and len(fs.liked) == 3
    assert sorted(fs.playlist_uris("P1")) == sorted(uris_of(t))
    assert any("remove from Liked Songs failed" in e for e in res.errors)


def test_remove_fails_midway_first_batch_removed():
    fs, t = build_world(70)
    fs.fail_batch_of("remove_saved_tracks_batched", 2)
    res, _ = run(fs, mv(t[:60]), max_moves=100)
    assert res.exit_code == EXIT_FAILED
    assert len(res.removed) == 40 and len(res.still_liked) == 20
    assert len(fs.liked) == 30
    assert all(safe(fs, u, "P1") for u in uris_of(t))


def test_removal_ok_but_not_applied_and_contains_agrees_is_reported_as_still_liked():
    fs, t = build_world(3)
    fs.ignore_removal.add(uri(2))
    res, _ = run(fs, mv(t))
    assert res.still_liked == [uri(2)] and uri(2) not in res.removed
    assert uri(2) in fs.liked and uri(2) in fs.items["P1"]  # safe: in both places


def test_removal_ok_but_does_not_stick_is_resurrected_mismatch():
    fs, t = build_world(3)
    fs.ignore_removal.add(uri(2))
    fs.contains_lies.add(uri(2))  # contains says gone, the list still shows it
    res, _ = run(fs, mv(t))
    assert res.exit_code == EXIT_MISMATCH and res.reconcile["resurrected"] == 1 and not res.reconcile["ok"]
    assert uri(2) not in res.removed and res.still_liked == [uri(2)]
    assert uri(2) in fs.liked and uri(2) in fs.items["P1"]
    assert "removal did not stick" in res.aborted


def test_unrelated_song_vanishes_is_detected_and_re_added():
    fs, t = build_world(6)
    fs.vanish_after("remove_saved_tracks_batched", uri(5))
    res, _ = run(fs, mv(t[:2]))
    assert res.exit_code == EXIT_MISMATCH and res.reconcile["lost"] == 1 and not res.reconcile["ok"]
    assert uri(5) in fs.liked and uri(5) in fs.put_uris
    assert ("save_tracks_batched", ((uri(5),), False)) in fs.calls
    assert any(b["kind"] == "re_add_lost" and b["committed"] for b in res.batches)
    assert "vanished" in res.aborted


def test_vanished_song_cannot_be_re_added_is_reported():
    fs, t = build_world(6)
    fs.vanish_after("remove_saved_tracks_batched", uri(5))
    fs.fail_every("save_tracks_batched")
    res, _ = run(fs, mv(t[:2]))
    assert res.exit_code == EXIT_MISMATCH
    assert any("could not re-add" in e for e in res.errors)


def test_moved_song_vanishing_before_removal_is_harmless():
    fs, t = build_world(3)
    fs.vanish_after("add_playlist_items_batched", uri(1))
    res, _ = run(fs, mv(t))
    assert res.exit_code == EXIT_OK and res.reconcile["lost"] == 0
    assert uri(1) in fs.items["P1"] and uri(1) not in fs.liked


def test_contains_lies_song_is_liked_no_loss():
    fs, t = build_world(3)
    fs.contains_lies.add(uri(1))  # claims song 1 is still liked though it was removed
    res, _ = run(fs, mv(t))
    # the Liked Songs list is authoritative (contains() can lag): the removal is accepted, with a warning
    assert res.exit_code == EXIT_OK and any("disagreed" in w for w in res.warnings)
    assert all(safe(fs, u, "P1") for u in uris_of(t))


def test_new_like_during_run_is_not_a_mismatch():
    fs, t = build_world(4)
    fs.like_after("remove_saved_tracks_batched", make_track(50))
    res, _ = run(fs, mv(t[:3]))
    assert res.exit_code == EXIT_OK and res.reconcile["ok"]
    assert res.reconcile["new_likes_during_run"] == 1
    assert res.reconcile["expected_after"] == res.reconcile["actual_after"] == 2 == res.liked_after
    assert uri(50) in fs.liked


def test_new_like_during_adds_is_not_a_mismatch():
    fs, t = build_world(3)
    fs.like_after("add_playlist_items_batched", make_track(51))
    res, _ = run(fs, mv(t))
    assert res.ok and res.reconcile["new_likes_during_run"] == 1 and fs.liked == [uri(51)]


def test_contains_raising_after_removal_propagates_but_nothing_is_lost():
    fs, t = build_world(3)
    fs.raise_on["contains_saved"] = SpotifyError("boom")
    j = JournalRecorder(fs)
    with pytest.raises(SpotifyError):
        run(fs, mv(t), journal=j)
    assert len(j.calls) == 1 and all(safe(fs, u, "P1") for u in uris_of(t))


def test_playlist_read_failing_means_no_removal_and_no_journal():
    fs, t = build_world(3)
    fs.raise_on["iter_playlist_items"] = SpotifyError("500")
    j = JournalRecorder(fs)
    with pytest.raises(SpotifyError):
        run(fs, mv(t), journal=j)
    assert fs.count("remove_saved_tracks_batched") == 0 and j.calls == [] and len(fs.liked) == 3


# ---------------------------------------------------------------- position / ordering end to end


def _world_with_existing(n_liked=5):
    fs, t = build_world(n_liked)
    existing = [make_track(100 + i) for i in range(1, 4)]
    fs.add_playlist("P1", items=existing)
    return fs, t, uris_of(existing)


def test_top_insertion_across_batches_newest_first_existing_below(monkeypatch):
    force_batch(monkeypatch, 2)
    fs, t, ex = _world_with_existing()
    res, _ = run(fs, mv(t, position="top"))
    assert res.ok
    assert fs.playlist_uris("P1") == uris_of(t) + ex


def test_top_insertion_single_batch():
    fs, t, ex = _world_with_existing(3)
    run(fs, mv(t, position="top"))
    assert fs.playlist_uris("P1") == uris_of(t) + ex


def test_top_insertion_shuffled_plan_order_still_newest_first(monkeypatch):
    force_batch(monkeypatch, 2)
    fs, t, ex = _world_with_existing()
    moves = mv(t, position="top")
    random.Random(3).shuffle(moves)
    run(fs, moves)
    assert fs.playlist_uris("P1") == uris_of(t) + ex


def test_bottom_appends_newest_first_after_existing(monkeypatch):
    force_batch(monkeypatch, 2)
    fs, t, ex = _world_with_existing()
    run(fs, mv(t, position="bottom"))
    assert fs.playlist_uris("P1") == ex + uris_of(t)


def test_mixed_top_and_bottom_on_one_playlist():
    fs, t, ex = _world_with_existing(4)
    run(fs, mv(t[:2], position="top") + mv(t[2:], position="bottom"))
    assert fs.playlist_uris("P1") == uris_of(t[:2]) + ex + uris_of(t[2:])


def test_positions_sent_to_client():
    fs, t = build_world(4, ("P1", "P2"))
    run(fs, mv(t[:2], "P1", position="top") + mv(t[2:], "P2", position="bottom"))
    sent = {a[0]: a[2] for n, a in fs.calls if n == "add_playlist_items_batched"}
    assert sent == {"P1": 0, "P2": None}


def test_top_position_with_already_in_target_song_keeps_its_place():
    fs, t, ex = _world_with_existing(3)
    fs.items["P1"].append(t[0].uri)
    run(fs, [make_move(t[0], "P1", position="top", already=True), make_move(t[1], "P1", position="top")])
    assert fs.playlist_uris("P1") == [uri(2)] + ex + [uri(1)]


# ---------------------------------------------------------------- property: fault schedules never lose a song


def _random_scenario(seed, monkeypatch):
    rng = random.Random(seed)
    n = rng.randint(3, 12)
    pids = ["P1", "P2", "P3"][: rng.randint(1, 3)]
    fs, tracks = build_world(n, pids)
    for pid in pids:
        for k in range(rng.randint(0, 2)):
            ex = make_track(200 + 10 * len(fs.items[pid]) + k + 1)
            fs.catalog[ex.uri] = ex
            fs.items[pid].append(ex.uri)
    moves, target = [], {}
    for t in tracks:
        if rng.random() < 0.7:
            pid = rng.choice(pids)
            already = t.uri in fs.items[pid]
            if rng.random() < 0.1:
                already = True  # stale flag
            moves.append(make_move(t, pid, position=rng.choice(["top", "bottom"]), already=already))
            target[t.uri] = pid
    if rng.random() < 0.1:
        moves.append(make_move(make_track(900), pids[0]))  # not liked
    rng.shuffle(moves)
    if rng.random() < 0.6:
        force_batch(monkeypatch, rng.choice([1, 2, 3]))
    add, rem = "add_playlist_items_batched", "remove_saved_tracks_batched"
    if rng.random() < 0.25:
        fs.fail_call(add, rng.randint(1, 3))
    if rng.random() < 0.08:
        fs.fail_every(add)
    if rng.random() < 0.2:
        fs.fail_batch_of(add, rng.randint(1, 3))
    if rng.random() < 0.15:
        fs.fail_playlist(rng.choice(pids))
    if rng.random() < 0.1:
        fs.fail_every(rem)
    if rng.random() < 0.1:
        fs.fail_batch_of(rem, 1)
    if rng.random() < 0.4:
        fs.lag = rng.randint(1, 7)
        fs.lag_kinds = set(rng.sample(["saved", "playlist", "contains"], rng.randint(1, 3)))
    if rng.random() < 0.2:
        fs.phantom_adds |= {m["uri"] for m in rng.sample(moves, min(len(moves), 2))}
    if rng.random() < 0.1:
        fs.ignore_removal |= {t.uri for t in rng.sample(tracks, 1)}
    if rng.random() < 0.1:
        fs.contains_lies |= {t.uri for t in rng.sample(tracks, 1)}
    if rng.random() < 0.15:
        fs.like_after(rng.choice([add, rem]), make_track(950))
    raising = None
    if rng.random() < 0.05:
        raising = rng.choice(["contains_saved", "iter_saved_tracks", "iter_playlist_items"])
        fs.raise_on[raising] = SpotifyError("injected read failure")
    if (not raising and fs.lag <= 4 and not fs.contains_lies and not fs.ignore_removal
            and rem not in fs.fail_batches and rng.random() < 0.25):
        fs.vanish_after(rem, rng.choice(tracks).uri)
    journal = JournalRecorder(fs, raises=OSError("disk full") if rng.random() < 0.1 else None)
    return fs, tracks, moves, target, journal


@pytest.mark.parametrize("seed", range(250))
def test_property_no_liked_song_ends_in_neither_place(seed, monkeypatch):
    fs, tracks, moves, target, journal = _random_scenario(seed, monkeypatch)
    before = set(fs.liked)
    try:
        run(fs, moves, before=before, journal=journal)
    except SpotifyError:
        pass  # an injected read failure aborts the run; the invariant must still hold
    journaled = {e["uri"]: e["target_playlist_id"] for call in journal.calls for e in call}
    for u in before:
        if u in target:
            assert safe(fs, u, target[u]), f"seed {seed}: {u} is neither liked nor in {target[u]}"
        else:
            assert u in fs.liked, f"seed {seed}: unplanned song {u} left Liked Songs"
    removed = before - fs.liked_uris()
    assert removed <= set(journaled), f"seed {seed}: removed songs without a journal entry"
    for u in removed:
        assert journaled[u] == target[u] and u in fs.items[target[u]]
    if journal.raises is not None:
        assert removed == set() and fs.count("remove_saved_tracks_batched") == 0
    if removed:
        assert fs.first("note:journal") < fs.first("remove_saved_tracks_batched")
