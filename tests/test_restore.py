"""--restore: journal loading and restore_from_log against the in-memory simulated Spotify. Offline."""

from __future__ import annotations

import json

import pytest

from fakes import BASE_NOW, FakeSpotify, JournalRecorder, build_world, make_move, make_track, uri
from src.apply import EXIT_FAILED, EXIT_OK, apply_moves, load_journal, restore_from_log


def nosleep(_s):
    pass


def entry(n, pid="P1"):
    return {"uri": uri(n), "name": f"Song {n}", "artists": "Bonobo", "original_added_at": "2026-01-01T00:00:00+00:00",
            "target_playlist_id": pid}


def write_log(tmp_path, journal, name="log.json"):
    p = tmp_path / name
    p.write_text(json.dumps({"journal": journal}), encoding="utf-8")
    return p


def restore(fs, path, **kw):
    return restore_from_log(fs, path, sleep=nosleep, **kw)


def restore_world(tmp_path, *, liked=(), in_playlist=(1, 2, 3), pids=("P1",)):
    """Songs `in_playlist` sit in P1, journaled; those in `liked` are (re)liked already."""
    fs = FakeSpotify()
    for pid in pids:
        fs.add_playlist(pid)
    for n in in_playlist:
        t = make_track(n, age_days=10 * n)
        fs.catalog[t.uri] = t
        fs.items["P1"].append(t.uri)
    fs.set_liked([make_track(n, age_days=10 * n) for n in liked])
    path = write_log(tmp_path, [entry(n) for n in in_playlist])
    return fs, path


# ---------------------------------------------------------------- load_journal


def test_load_journal_returns_entries(tmp_path):
    p = write_log(tmp_path, [entry(1), entry(2)])
    assert [e["uri"] for e in load_journal(p)] == [uri(1), uri(2)]


def test_load_journal_accepts_empty_journal(tmp_path):
    assert load_journal(write_log(tmp_path, [])) == []


def test_load_journal_missing_file(tmp_path):
    with pytest.raises(OSError):
        load_journal(tmp_path / "nope.json")


def test_load_journal_invalid_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_journal(p)


@pytest.mark.parametrize("payload", [{}, {"journal": None}, {"journal": "x"}, {"journal": {"a": 1}}, [1, 2], "str"])
def test_load_journal_without_a_journal_list(tmp_path, payload):
    p = tmp_path / "log.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="no journal"):
        load_journal(p)


@pytest.mark.parametrize("bad_entry", [5, "spotify:track:" + "a" * 22, None, {"name": "no uri"}])
def test_load_journal_entry_without_uri(tmp_path, bad_entry):
    with pytest.raises(ValueError, match="without a uri"):
        load_journal(write_log(tmp_path, [entry(1), bad_entry]))


@pytest.mark.parametrize("bad_uri", [
    "not-a-uri", "spotify:album:" + "a" * 22, "spotify:episode:" + "a" * 22, "spotify:playlist:" + "a" * 22,
    "spotify:track:short", "spotify:track:" + "a" * 22 + "x", "", None, 12,
])
def test_load_journal_rejects_bad_uris(tmp_path, bad_uri):
    e = entry(1)
    e["uri"] = bad_uri
    with pytest.raises(ValueError):
        load_journal(write_log(tmp_path, [e]))


def test_one_bad_uri_rejects_the_whole_journal(tmp_path):
    bad = entry(2)
    bad["uri"] = "spotify:album:" + "a" * 22
    with pytest.raises(ValueError):
        load_journal(write_log(tmp_path, [entry(1), bad]))


# ---------------------------------------------------------------- restore behaviour


def test_restore_re_adds_songs_not_liked(tmp_path):
    fs, p = restore_world(tmp_path)
    res = restore(fs, p)
    assert res.exit_code == EXIT_OK and res.errors == []
    assert fs.liked_uris() == {uri(1), uri(2), uri(3)}
    assert res.confirmed == [uri(1), uri(2), uri(3)] and res.liked_before == 0 and res.liked_after == 3
    assert fs.playlist_uris("P1") == [uri(1), uri(2), uri(3)]  # playlist untouched by default


def test_restore_does_not_re_save_songs_already_liked(tmp_path):
    fs, p = restore_world(tmp_path, liked=(2,))
    before_added = fs.added[uri(2)]
    res = restore(fs, p)
    assert res.ok
    assert uri(2) not in fs.put_uris and sorted(fs.put_uris) == [uri(1), uri(3)]
    saves = [a for n, a in fs.calls if n == "save_tracks_batched"]
    assert len(saves) == 1 and set(saves[0][0]) == {uri(1), uri(3)}
    assert fs.added[uri(2)] == before_added  # its added_at was not reset
    assert fs.liked_uris() == {uri(1), uri(2), uri(3)}


def test_restore_when_everything_is_liked_makes_no_write_calls(tmp_path):
    fs, p = restore_world(tmp_path, liked=(1, 2, 3))
    res = restore(fs, p)
    assert res.ok and fs.write_calls() == [] and fs.put_uris == []


def test_restore_is_idempotent(tmp_path):
    fs, p = restore_world(tmp_path)
    restore(fs, p)
    puts = list(fs.put_uris)
    res = restore(fs, p)
    assert res.ok and fs.put_uris == puts


def test_restore_resets_added_at_to_now_journal_keeps_original(tmp_path):
    fs, p = restore_world(tmp_path)
    restore(fs, p)
    assert all(fs.added[uri(n)] > BASE_NOW for n in (1, 2, 3))
    assert load_journal(p)[0]["original_added_at"] == "2026-01-01T00:00:00+00:00"


def test_restore_empty_journal_is_a_noop(tmp_path):
    fs, _ = restore_world(tmp_path, in_playlist=())
    res = restore(fs, write_log(tmp_path, [], "empty.json"))
    assert res.ok and fs.write_calls() == []


def test_restore_remove_from_targets_off_by_default(tmp_path):
    fs, p = restore_world(tmp_path)
    restore(fs, p)
    assert fs.count("remove_playlist_items_batched") == 0
    assert len(fs.playlist_uris("P1")) == 3


def test_restore_remove_from_targets_on_when_asked(tmp_path):
    fs, p = restore_world(tmp_path)
    res = restore(fs, p, remove_from_targets=True)
    assert res.ok and fs.playlist_uris("P1") == [] and fs.liked_uris() == {uri(1), uri(2), uri(3)}
    assert any(b["kind"] == "remove_from_target" and b["target"] == "P1" and b["committed"] for b in res.batches)


def test_restore_removes_from_each_journaled_playlist(tmp_path):
    fs, _ = restore_world(tmp_path, in_playlist=(1,), pids=("P1", "P2"))
    t2 = make_track(2, age_days=20)
    fs.catalog[t2.uri] = t2
    fs.items["P2"].append(t2.uri)
    p = write_log(tmp_path, [entry(1, "P1"), entry(2, "P2")], "two.json")
    res = restore(fs, p, remove_from_targets=True)
    assert res.ok and fs.items["P1"] == [] and fs.items["P2"] == []
    assert {b["target"] for b in res.batches if b["kind"] == "remove_from_target"} == {"P1", "P2"}


def test_remove_from_targets_only_removes_journaled_songs(tmp_path):
    fs, p = restore_world(tmp_path)
    other = make_track(500)
    fs.catalog[other.uri] = other
    fs.items["P1"].append(other.uri)
    restore(fs, p, remove_from_targets=True)
    assert fs.playlist_uris("P1") == [uri(500)]


# ---------------------------------------------------------------- failures / refusal


def test_restore_save_failure_is_reported_and_targets_are_kept(tmp_path):
    fs, p = restore_world(tmp_path)
    fs.fail_every("save_tracks_batched")
    res = restore(fs, p, remove_from_targets=True)
    assert res.exit_code == EXIT_FAILED
    assert any("restore failed" in e for e in res.errors) and any("still not in Liked Songs" in e for e in res.errors)
    assert fs.count("remove_playlist_items_batched") == 0  # never strip the playlist while songs are not back
    assert len(fs.playlist_uris("P1")) == 3 and fs.liked == []


def test_restore_partial_save_failure_keeps_playlist_copy(tmp_path):
    fs, p = restore_world(tmp_path, in_playlist=tuple(range(1, 46)))
    fs.fail_batch_of("save_tracks_batched", 2)  # 45 songs => batches of 40 + 5
    res = restore(fs, p, remove_from_targets=True)
    assert res.exit_code == EXIT_FAILED and len(fs.liked) == 40
    assert len(fs.playlist_uris("P1")) == 45
    assert len(res.confirmed) == 40


def test_restore_remove_from_target_failure_is_reported(tmp_path):
    fs, p = restore_world(tmp_path)
    fs.fail_every("remove_playlist_items_batched")
    res = restore(fs, p, remove_from_targets=True)
    assert res.exit_code == EXIT_FAILED and any("could not remove from target" in e for e in res.errors)
    assert fs.liked_uris() == {uri(1), uri(2), uri(3)} and len(fs.playlist_uris("P1")) == 3


def test_restore_contains_lag_within_poll(tmp_path):
    fs, p = restore_world(tmp_path)
    fs.lag, fs.lag_kinds = 3, {"contains"}
    res = restore(fs, p)
    assert res.ok and len(res.confirmed) == 3


def test_restore_contains_lag_beyond_poll_reports_missing_and_keeps_playlist(tmp_path):
    fs, p = restore_world(tmp_path)
    fs.lag, fs.lag_kinds = 8, {"contains"}
    res = restore(fs, p, remove_from_targets=True)
    assert res.exit_code == EXIT_FAILED and fs.count("remove_playlist_items_batched") == 0
    assert len(fs.playlist_uris("P1")) == 3


def test_restore_refuses_dry_run_client(tmp_path):
    fs, p = restore_world(tmp_path)
    fs.dry_run = True
    with pytest.raises(RuntimeError, match="dry-run"):
        restore(fs, p)
    assert fs.calls == []


def test_restore_bad_journal_makes_no_calls(tmp_path):
    fs, _ = restore_world(tmp_path)
    bad = entry(1)
    bad["uri"] = "spotify:album:" + "a" * 22
    with pytest.raises(ValueError):
        restore(fs, write_log(tmp_path, [bad], "bad.json"))
    assert fs.calls == []


def test_remove_from_targets_keeps_songs_that_were_in_the_playlist_before_the_run(tmp_path):
    fs, t = build_world(2)
    fs.items["P1"].append(t[0].uri)  # song 1 was already in the playlist before we ran
    j = JournalRecorder(fs)
    res = apply_moves(fs, [make_move(t[0], "P1", already=True), make_move(t[1], "P1")],
                      liked_uris_before=set(fs.liked), write_journal=j, sleep=nosleep)
    log = tmp_path / "log.json"
    log.write_text(json.dumps({"journal": res.journal}), encoding="utf-8")
    restore(fs, log, remove_from_targets=True)
    assert uri(1) in fs.playlist_uris("P1")


def test_journal_entry_without_target_playlist_is_rejected_cleanly(tmp_path):
    e = entry(1)
    del e["target_playlist_id"]
    fs, _ = restore_world(tmp_path)
    p = write_log(tmp_path, [e], "nt.json")
    try:
        restore(fs, p, remove_from_targets=True)
    except ValueError:
        return  # a clean, early rejection is the desired behaviour
    raise AssertionError("expected ValueError")


# ---------------------------------------------------------------- round trip apply -> restore


def _apply_to_log(fs, moves, tmp_path):
    j = JournalRecorder(fs)
    res = apply_moves(fs, moves, liked_uris_before=set(fs.liked), write_journal=j, sleep=nosleep)
    p = tmp_path / "run.json"
    p.write_text(json.dumps({"journal": res.journal}), encoding="utf-8")
    return res, p


def test_round_trip_apply_then_restore_returns_songs_to_liked(tmp_path):
    fs, t = build_world(5)
    res, log = _apply_to_log(fs, [make_move(x, "P1") for x in t[:3]], tmp_path)
    assert res.ok and len(fs.liked) == 2
    r = restore(fs, log)
    assert r.ok and fs.liked_uris() == {uri(i) for i in range(1, 6)}
    assert len(fs.playlist_uris("P1")) == 3  # not removed without the flag
    assert r.liked_before == 2 and r.liked_after == 5


def test_round_trip_with_remove_from_targets_leaves_playlist_clean(tmp_path):
    fs, t = build_world(5)
    _, log = _apply_to_log(fs, [make_move(x, "P1", position="top") for x in t[:3]], tmp_path)
    r = restore(fs, log, remove_from_targets=True)
    assert r.ok and fs.playlist_uris("P1") == [] and len(fs.liked) == 5


def test_round_trip_only_touches_journaled_songs(tmp_path):
    fs, t = build_world(5)
    _, log = _apply_to_log(fs, [make_move(x, "P1") for x in t[:2]], tmp_path)
    restore(fs, log, remove_from_targets=True)
    assert set(fs.put_uris) == {uri(1), uri(2)}
