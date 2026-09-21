"""The *_batched writers of SpotifyClient (per-batch outcomes, position, snapshot chaining) over a fake HTTP session."""

from __future__ import annotations

import json

import pytest

from src import spotify_client as sc
from src.spotify_client import BatchOutcome, DryRunError, SpotifyClient, SpotifyError

API = sc.API_BASE
PL = "PL1"
ITEMS = f"/playlists/{PL}/items"


def uri(n: int) -> str:
    return "spotify:track:" + f"{n:022d}"


def uris(n: int, start: int = 1) -> list[str]:
    return [uri(i) for i in range(start, start + n)]


class FakeResponse:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.text = json.dumps(body) if body is not None else ""
        self.content = self.text.encode()

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


class FakeSession:
    def __init__(self, routes=None):
        self.routes = routes or {}
        self.calls = []  # (method, url, kwargs)

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        path = url[len(API):] if url.startswith(API) else url
        route = self.routes.get((method, path))
        if route is None:
            return FakeResponse(404, {"error": {"status": 404, "message": f"no route {method} {path}"}})
        if callable(route):
            return route(method, url, kwargs)
        if isinstance(route, list):
            return route.pop(0) if len(route) > 1 else route[0]
        return route

    def api(self, method=None):
        return [c for c in self.calls if c[1].startswith(API) and (method is None or c[0] == method)]


def make(routes=None, *, dry_run=False):
    routes = dict(routes or {})
    routes.setdefault(("POST", sc.TOKEN_URL), FakeResponse(200, {"access_token": "AT-fake-access-token-1234567890"}))
    session = FakeSession(routes)
    return SpotifyClient("cid", "RT-fake-refresh-token-abcdefghij", session=session, sleep=lambda s: None,
                         dry_run=dry_run), session


def snap_ok(n):
    return FakeResponse(201, {"snapshot_id": f"snap{n}"})


def boom():
    return FakeResponse(500, {"error": {"status": 500, "message": "server exploded"}})


def not_liked(_m, url, kwargs):
    n = len(kwargs["params"]["uris"].split(","))
    return FakeResponse(200, [False] * n)


# ------------------------------------------------------------ playlist add


def test_add_batches_of_100_all_committed_with_snapshots():
    client, session = make({("POST", ITEMS): [snap_ok(1), snap_ok(2), snap_ok(3)]})
    outs = client.add_playlist_items_batched(PL, uris(250))
    assert [len(o.uris) for o in outs] == [100, 100, 50] and all(o.ok and o.error is None for o in outs)
    assert [o.snapshot for o in outs] == ["snap1", "snap2", "snap3"]
    assert [u for o in outs for u in o.uris] == uris(250)  # partition, order preserved
    bodies = [c[2]["json"] for c in session.api("POST")]
    assert [len(b["uris"]) for b in bodies] == [100, 100, 50]


def test_add_failure_in_batch_2_of_3_skips_batch_3_and_keeps_batch_1():
    client, session = make({("POST", ITEMS): [snap_ok(1), boom()]})
    outs = client.add_playlist_items_batched(PL, uris(250))  # must not raise
    assert [o.ok for o in outs] == [True, False, False]
    assert outs[0].snapshot == "snap1" and len(outs[0].uris) == 100
    assert "500" in outs[1].error and len(outs[1].uris) == 100
    assert "skipped" in outs[2].error and len(outs[2].uris) == 50
    assert len(session.api("POST")) == 2  # batch 3 was never sent


def test_add_failure_in_first_batch_skips_the_rest():
    client, session = make({("POST", ITEMS): boom()})
    outs = client.add_playlist_items_batched(PL, uris(150))
    assert [o.ok for o in outs] == [False, False] and len(session.api("POST")) == 1


def test_failed_batch_outcome_carries_last_good_snapshot():
    client, _ = make({("POST", ITEMS): [snap_ok(1), boom()]})
    outs = client.add_playlist_items_batched(PL, uris(200))
    assert outs[1].snapshot == "snap1" and outs[0].snapshot == "snap1"


def test_add_empty_makes_no_request():
    client, session = make()
    assert client.add_playlist_items_batched(PL, []) == [] and session.calls == []


def test_add_sends_uris_in_json_body():
    client, session = make({("POST", ITEMS): snap_ok(1)})
    client.add_playlist_items_batched(PL, uris(2))
    (call,) = session.api("POST")
    assert call[2]["json"] == {"uris": uris(2)} and "params" in call[2] and not call[2]["params"]


def test_auth_failure_is_a_failed_outcome_not_an_exception():
    routes = {("POST", ITEMS): FakeResponse(401, {"error": {"message": "expired"}})}
    client, _ = make(routes)
    outs = client.add_playlist_items_batched(PL, uris(3))
    assert [o.ok for o in outs] == [False] and "401" in outs[0].error


def test_playlist_403_is_a_failed_outcome():
    client, _ = make({("POST", ITEMS): FakeResponse(403, {"error": {"message": "Forbidden"}})})
    (o,) = client.add_playlist_items_batched(PL, uris(2))
    assert not o.ok and "403" in o.error and o.uris == tuple(uris(2))


# ------------------------------------------------------------ position


def test_position_zero_is_sent_in_every_batch_body():
    client, session = make({("POST", ITEMS): snap_ok(1)})
    client.add_playlist_items_batched(PL, uris(150), position=0)
    bodies = [c[2]["json"] for c in session.api("POST")]
    assert len(bodies) == 2 and all(b["position"] == 0 for b in bodies)


def test_position_positive_is_sent():
    client, session = make({("POST", ITEMS): snap_ok(1)})
    client.add_playlist_items_batched(PL, uris(2), position=7)
    assert session.api("POST")[0][2]["json"]["position"] == 7


def test_position_omitted_when_not_given():
    client, session = make({("POST", ITEMS): snap_ok(1)})
    client.add_playlist_items_batched(PL, uris(2))
    client.add_playlist_items_batched(PL, uris(2), position=None)
    assert all("position" not in c[2]["json"] for c in session.api("POST"))


@pytest.mark.parametrize("bad", [-1, True, False, "0", 1.5, 0.0, [0]])
def test_bad_position_raises_before_any_request(bad):
    client, session = make({("POST", ITEMS): snap_ok(1)})
    with pytest.raises(ValueError, match="position"):
        client.add_playlist_items_batched(PL, uris(3), position=bad)
    assert session.calls == []


def test_position_on_legacy_wrapper():
    client, session = make({("POST", ITEMS): snap_ok(1)})
    client.add_playlist_items(PL, uris(2), position=0)
    assert session.api("POST")[0][2]["json"]["position"] == 0


# ------------------------------------------------------------ playlist remove + snapshot chaining


def test_remove_chains_snapshot_from_previous_write():
    client, session = make({("DELETE", ITEMS): [FakeResponse(200, {"snapshot_id": "s1"}),
                                                 FakeResponse(200, {"snapshot_id": "s2"}),
                                                 FakeResponse(200, {"snapshot_id": "s3"})]})
    outs = client.remove_playlist_items_batched(PL, uris(250), snapshot_id="s0")
    bodies = [c[2]["json"] for c in session.api("DELETE")]
    assert [b["snapshot_id"] for b in bodies] == ["s0", "s1", "s2"]
    assert [len(b["items"]) for b in bodies] == [100, 100, 50]
    assert bodies[0]["items"][0] == {"uri": uri(1)}
    assert [o.snapshot for o in outs] == ["s1", "s2", "s3"]


def test_remove_without_initial_snapshot_omits_it_in_first_body():
    client, session = make({("DELETE", ITEMS): [FakeResponse(200, {"snapshot_id": "s1"}),
                                                 FakeResponse(200, {"snapshot_id": "s2"})]})
    client.remove_playlist_items_batched(PL, uris(150))
    b1, b2 = [c[2]["json"] for c in session.api("DELETE")]
    assert "snapshot_id" not in b1 and b2["snapshot_id"] == "s1"


def test_remove_failure_mid_way_keeps_snapshot_and_skips_rest():
    client, session = make({("DELETE", ITEMS): [FakeResponse(200, {"snapshot_id": "s1"}), boom()]})
    outs = client.remove_playlist_items_batched(PL, uris(250), snapshot_id="s0")
    assert [o.ok for o in outs] == [True, False, False]
    assert outs[1].snapshot == "s1" and len(session.api("DELETE")) == 2


def test_remove_response_without_snapshot_keeps_previous_one():
    client, session = make({("DELETE", ITEMS): [FakeResponse(200, {"snapshot_id": "s1"}), FakeResponse(200, {})]})
    outs = client.remove_playlist_items_batched(PL, uris(150))
    assert [o.snapshot for o in outs] == ["s1", "s1"]


# ------------------------------------------------------------ library save / remove


def test_remove_saved_batches_of_40_uris_in_query_string():
    client, session = make({("DELETE", "/me/library"): FakeResponse(200)})
    outs = client.remove_saved_tracks_batched(uris(100))
    assert [len(o.uris) for o in outs] == [40, 40, 20] and all(o.ok for o in outs)
    calls = session.api("DELETE")
    assert [len(c[2]["params"]["uris"].split(",")) for c in calls] == [40, 40, 20]
    assert all(c[2].get("json") is None for c in calls)


def test_remove_saved_failure_in_batch_2_of_3():
    client, session = make({("DELETE", "/me/library"): [FakeResponse(200), boom()]})
    outs = client.remove_saved_tracks_batched(uris(100))
    assert [o.ok for o in outs] == [True, False, False]
    assert len(outs[0].uris) == 40 and "skipped" in outs[2].error and len(session.api("DELETE")) == 2


def test_save_tracks_batched_skips_already_liked_and_batches_40():
    def contains(_m, url, kwargs):
        chunk = kwargs["params"]["uris"].split(",")
        return FakeResponse(200, [u == uri(1) for u in chunk])  # only song 1 is liked

    client, session = make({("GET", "/me/library/contains"): contains, ("PUT", "/me/library"): FakeResponse(200)})
    outs = client.save_tracks_batched(uris(50))
    assert [len(o.uris) for o in outs] == [40, 9]
    assert uri(1) not in [u for o in outs for u in o.uris]
    assert all(len(c[2]["params"]["uris"].split(",")) <= 40 for c in session.api("GET"))


def test_save_tracks_batched_allow_resave_skips_contains():
    client, session = make({("PUT", "/me/library"): FakeResponse(200)})
    outs = client.save_tracks_batched(uris(3), allow_resave=True)
    assert [len(o.uris) for o in outs] == [3] and session.api("GET") == []


def test_save_tracks_batched_everything_already_liked_sends_no_put():
    client, session = make({("GET", "/me/library/contains"): lambda m, u, k: FakeResponse(200, [True] * len(k["params"]["uris"].split(",")))})
    assert client.save_tracks_batched(uris(5)) == [] and session.api("PUT") == []


def test_save_failure_in_batch_2_of_3():
    client, session = make({("GET", "/me/library/contains"): not_liked, ("PUT", "/me/library"): [FakeResponse(200), boom()]})
    outs = client.save_tracks_batched(uris(100))
    assert [o.ok for o in outs] == [True, False, False] and len(session.api("PUT")) == 2


def test_save_empty_makes_no_request():
    client, session = make()
    assert client.save_tracks_batched([]) == [] and session.calls == []


# ------------------------------------------------------------ legacy wrappers


def test_legacy_add_returns_last_snapshot():
    client, _ = make({("POST", ITEMS): [snap_ok(1), snap_ok(2)]})
    assert client.add_playlist_items(PL, uris(150)) == "snap2"


def test_legacy_add_empty_returns_none():
    client, session = make()
    assert client.add_playlist_items(PL, []) is None and session.calls == []


def test_legacy_add_raises_on_first_failure():
    client, session = make({("POST", ITEMS): [snap_ok(1), boom()]})
    with pytest.raises(SpotifyError, match="500"):
        client.add_playlist_items(PL, uris(250))
    assert len(session.api("POST")) == 2


def test_legacy_remove_playlist_items_return_values():
    client, _ = make({("DELETE", ITEMS): [FakeResponse(200, {"snapshot_id": "s1"}), FakeResponse(200, {"snapshot_id": "s2"})]})
    assert client.remove_playlist_items(PL, uris(150), "s0") == "s2"
    assert client.remove_playlist_items(PL, [], "keep") == "keep"


def test_legacy_remove_playlist_items_raises_on_failure():
    client, _ = make({("DELETE", ITEMS): boom()})
    with pytest.raises(SpotifyError):
        client.remove_playlist_items(PL, uris(3))


def test_legacy_save_tracks_returns_uris_sent():
    client, _ = make({("GET", "/me/library/contains"): lambda m, u, k: FakeResponse(200, [u_ == uri(2) for u_ in k["params"]["uris"].split(",")]),
                      ("PUT", "/me/library"): FakeResponse(200)})
    assert client.save_tracks([uri(1), uri(2), uri(3)]) == [uri(1), uri(3)]


def test_legacy_save_tracks_raises_on_failure():
    client, _ = make({("GET", "/me/library/contains"): not_liked, ("PUT", "/me/library"): boom()})
    with pytest.raises(SpotifyError):
        client.save_tracks(uris(3))


def test_legacy_remove_saved_tracks_returns_none_and_raises_on_failure():
    ok, _ = make({("DELETE", "/me/library"): FakeResponse(200)})
    assert ok.remove_saved_tracks(uris(41)) is None
    bad, _ = make({("DELETE", "/me/library"): [FakeResponse(200), boom()]})
    with pytest.raises(SpotifyError):
        bad.remove_saved_tracks(uris(41))


# ------------------------------------------------------------ dry-run refusal


WRITERS = [
    ("add_playlist_items_batched", lambda c: c.add_playlist_items_batched(PL, uris(2))),
    ("add_playlist_items_batched(position)", lambda c: c.add_playlist_items_batched(PL, uris(2), position=0)),
    ("remove_playlist_items_batched", lambda c: c.remove_playlist_items_batched(PL, uris(2))),
    ("save_tracks_batched", lambda c: c.save_tracks_batched(uris(2))),
    ("save_tracks_batched(resave)", lambda c: c.save_tracks_batched(uris(2), allow_resave=True)),
    ("remove_saved_tracks_batched", lambda c: c.remove_saved_tracks_batched(uris(2))),
    ("add_playlist_items", lambda c: c.add_playlist_items(PL, uris(2))),
    ("remove_playlist_items", lambda c: c.remove_playlist_items(PL, uris(2))),
    ("save_tracks", lambda c: c.save_tracks(uris(2))),
    ("remove_saved_tracks", lambda c: c.remove_saved_tracks(uris(2))),
]


@pytest.mark.parametrize("name,call", WRITERS, ids=[w[0] for w in WRITERS])
def test_dry_run_client_refuses_every_writer_with_zero_http_calls(name, call):
    client, session = make(dry_run=True)
    with pytest.raises(DryRunError):
        call(client)
    assert session.calls == []


def test_dry_run_still_allows_reads():
    client, session = make({("GET", "/me/library/contains"): FakeResponse(200, [True, False])}, dry_run=True)
    assert client.contains_saved(uris(2)) == {uri(1): True, uri(2): False}
    assert [c[0] for c in session.api()] == ["GET"]


# ------------------------------------------------------------ input validation before any call


BAD_URIS = ["spotify:album:" + "a" * 22, "spotify:episode:" + "a" * 22, "spotify:playlist:" + "a" * 22,
            "spotify:user:someone", "garbage", "spotify:track:short", "", None, 7]


@pytest.mark.parametrize("bad", BAD_URIS)
@pytest.mark.parametrize("which", ["add", "remove_pl", "save", "remove_saved"])
def test_non_track_uris_rejected_before_any_call(which, bad):
    client, session = make()
    call = {
        "add": lambda u: client.add_playlist_items_batched(PL, u),
        "remove_pl": lambda u: client.remove_playlist_items_batched(PL, u),
        "save": lambda u: client.save_tracks_batched(u),
        "remove_saved": lambda u: client.remove_saved_tracks_batched(u),
    }[which]
    with pytest.raises(ValueError):
        call(uris(3) + [bad])  # a single bad entry poisons the whole call: nothing partial is sent
    assert session.calls == []


@pytest.mark.parametrize("bad_id", ["", "has space", "a/b", "x" * 65, None, 5])
def test_invalid_playlist_id_rejected_before_any_call(bad_id):
    client, session = make()
    with pytest.raises(ValueError):
        client.add_playlist_items_batched(bad_id, uris(1))
    with pytest.raises(ValueError):
        client.remove_playlist_items_batched(bad_id, uris(1))
    assert session.calls == []


def test_batch_outcome_is_immutable():
    o = BatchOutcome(("a",), True)
    with pytest.raises(Exception):
        o.ok = False  # type: ignore[misc]
    assert o.error is None and o.snapshot is None
