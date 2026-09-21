"""Unit tests for planner.insert_batches (ordering of playlist inserts, master decision 14)."""

from __future__ import annotations

import pytest

from src.planner import InsertBatch, insert_batches


def mv(n, pid="p1", pos="bottom", added=None):
    return {"uri": f"u{n}", "playlist_id": pid, "target_position": pos,
            "original_added_at": added if added is not None else f"2026-01-{n:02d}T00:00:00+00:00"}


def simulate(batches, initial=()):
    """Apply batches to per-playlist lists the way Spotify's add-items(position) does."""
    pls: dict[str, list[str]] = {}
    for b in batches:
        cur = pls.setdefault(b.playlist_id, list(initial))
        if b.position is None:
            cur.extend(b.uris)
        else:
            cur[b.position:b.position] = list(b.uris)
    return pls


def test_empty():
    assert insert_batches([]) == []


def test_single_move_bottom():
    assert insert_batches([mv(1)]) == [InsertBatch("p1", ("u1",), None)]


def test_single_move_top():
    assert insert_batches([mv(1, pos="top")]) == [InsertBatch("p1", ("u1",), 0)]


def test_missing_target_position_defaults_bottom():
    m = {"uri": "u1", "playlist_id": "p1", "original_added_at": "2026-01-01"}
    assert insert_batches([m])[0].position is None


def test_bottom_appends_newest_first_in_order():
    moves = [mv(n) for n in (1, 2, 3, 4, 5)]
    batches = insert_batches(moves, batch_size=2)
    assert all(b.position is None for b in batches)
    assert [b.uris for b in batches] == [("u5", "u4"), ("u3", "u2"), ("u1",)]
    assert simulate(batches)["p1"] == ["u5", "u4", "u3", "u2", "u1"]


def test_top_oldest_chunk_first_at_position_zero():
    moves = [mv(n, pos="top") for n in (1, 2, 3, 4, 5)]
    batches = insert_batches(moves, batch_size=2)
    assert [b.position for b in batches] == [0, 0, 0]
    assert [b.uris for b in batches] == [("u1",), ("u3", "u2"), ("u5", "u4")]


def test_top_final_order_newest_to_oldest_then_existing_untouched():
    moves = [mv(n, pos="top") for n in (1, 2, 3, 4, 5)]
    for size in (1, 2, 3, 4, 5, 100):
        final = simulate(insert_batches(moves, batch_size=size), initial=["x1", "x2"])["p1"]
        assert final == ["u5", "u4", "u3", "u2", "u1", "x1", "x2"], size


def test_top_input_order_irrelevant():
    moves = [mv(n, pos="top") for n in (3, 1, 5, 2, 4)]
    final = simulate(insert_batches(moves, batch_size=2), initial=["x"])["p1"]
    assert final == ["u5", "u4", "u3", "u2", "u1", "x"]


def test_bottom_input_order_irrelevant():
    moves = [mv(n) for n in (3, 1, 5, 2, 4)]
    assert simulate(insert_batches(moves, batch_size=2), initial=["x"])["p1"] == ["x", "u5", "u4", "u3", "u2", "u1"]


def test_groups_per_playlist():
    moves = [mv(1, "a"), mv(2, "b"), mv(3, "a"), mv(4, "b")]
    batches = insert_batches(moves, batch_size=10)
    assert len(batches) == 2
    by = {b.playlist_id: b for b in batches}
    assert by["a"].uris == ("u3", "u1") and by["b"].uris == ("u4", "u2")


def test_groups_per_position_same_playlist():
    moves = [mv(1, pos="top"), mv(2, pos="bottom"), mv(3, pos="top"), mv(4, pos="bottom")]
    batches = insert_batches(moves)
    assert len(batches) == 2
    by = {b.position: b for b in batches}
    assert by[0].uris == ("u3", "u1") and by[None].uris == ("u4", "u2")


def test_mixed_positions_final_order():
    moves = [mv(1, pos="top"), mv(2, pos="bottom"), mv(3, pos="top"), mv(4, pos="bottom")]
    final = simulate(insert_batches(moves), initial=["x"])["p1"]
    assert final.index("u3") < final.index("u1") < final.index("x")
    assert final.index("x") < final.index("u4") < final.index("u2")


def test_default_batch_size_is_100():
    moves = [{"uri": f"u{n}", "playlist_id": "p", "original_added_at": f"2026-{1 + n // 28:02d}-{1 + n % 28:02d}"}
             for n in range(250)]
    assert [len(b.uris) for b in insert_batches(moves)] == [100, 100, 50]


@pytest.mark.parametrize("count,sizes", [(99, [99]), (100, [100]), (101, [100, 1]), (200, [100, 100]), (201, [100, 100, 1])])
def test_batch_boundaries_bottom(count, sizes):
    moves = [{"uri": f"u{n}", "playlist_id": "p", "original_added_at": f"{1000 + n}"} for n in range(count)]
    assert [len(b.uris) for b in insert_batches(moves)] == sizes


@pytest.mark.parametrize("count,sizes", [(100, [100]), (101, [1, 100]), (201, [1, 100, 100])])
def test_batch_boundaries_top_oldest_chunk_first(count, sizes):
    moves = [{"uri": f"u{n}", "playlist_id": "p", "target_position": "top", "original_added_at": f"{1000 + n}"}
             for n in range(count)]
    batches = insert_batches(moves)
    assert [len(b.uris) for b in batches] == sizes
    assert all(b.position == 0 for b in batches)
    final = simulate(batches)["p"]
    assert final == [f"u{n}" for n in reversed(range(count))]


def test_uris_are_tuples_and_batch_frozen():
    b = insert_batches([mv(1)])[0]
    assert isinstance(b.uris, tuple)
    with pytest.raises(Exception):
        b.position = 3  # type: ignore[misc]


def test_missing_added_at_sorted_as_oldest():
    moves = [mv(1, added=""), mv(2)]
    moves[0]["original_added_at"] = None
    assert insert_batches(moves)[0].uris == ("u2", "u1")


def test_every_uri_emitted_once():
    moves = [mv(n, pid=f"p{n % 3}", pos="top" if n % 2 else "bottom") for n in range(1, 20)]
    uris = [u for b in insert_batches(moves, batch_size=2) for u in b.uris]
    assert sorted(uris) == sorted(m["uri"] for m in moves)


def test_two_playlists_top_simulated_independently():
    moves = [mv(n, pid="a" if n % 2 else "b", pos="top") for n in range(1, 9)]
    res = simulate(insert_batches(moves, batch_size=1))
    assert res["a"] == ["u7", "u5", "u3", "u1"] and res["b"] == ["u8", "u6", "u4", "u2"]
