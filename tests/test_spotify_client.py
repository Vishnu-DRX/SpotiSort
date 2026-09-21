"""Client behaviour against a fake HTTP session (offline)."""

from __future__ import annotations

import json
import logging

import pytest

from src import spotify_client as sc
from src.spotify_client import DryRunError, SpotifyClient, SpotifyError

FAKE_ACCESS = "AT-fake-access-token-1234567890"
FAKE_REFRESH = "RT-fake-refresh-token-abcdefghij"
FAKE_SECRET = "CS-fake-client-secret-zzzzzzzz"
API = sc.API_BASE


def uri(n: int) -> str:
    return "spotify:track:" + f"{n:022d}"


class FakeResponse:
    def __init__(self, status=200, body=None, headers=None, text=None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.text = text if text is not None else (json.dumps(body) if body is not None else "")
        self.content = self.text.encode()

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


class FakeSession:
    """Routes by (method, path). A route value is a response, a list (consumed in order) or a callable."""

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

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def on_api(self):
        return [c for c in self.calls if c[1].startswith(API)]


def token_ok():
    return FakeResponse(200, {"access_token": FAKE_ACCESS, "expires_in": 3600})


def make(routes=None, **kw):
    routes = dict(routes or {})
    routes.setdefault(("POST", sc.TOKEN_URL), token_ok())
    session = FakeSession(routes)
    sleeps = []
    client = SpotifyClient("cid", FAKE_REFRESH, session=session, sleep=sleeps.append, **kw)
    return client, session, sleeps


# ------------------------------------------------------------ auth / retry behaviour


def test_refresh_uses_client_id_only_without_secret():
    client, session, _ = make({("GET", "/me"): FakeResponse(200, {"id": "me"})})
    assert client.me_id == "me"
    _, url, kw = session.calls[0]
    assert url == sc.TOKEN_URL
    assert kw["data"] == {"grant_type": "refresh_token", "refresh_token": FAKE_REFRESH, "client_id": "cid"}
    assert "Authorization" not in kw["headers"]
    assert session.calls[1][2]["headers"]["Authorization"] == f"Bearer {FAKE_ACCESS}"


def test_refresh_uses_basic_auth_when_secret_present():
    session = FakeSession({("POST", sc.TOKEN_URL): token_ok(), ("GET", "/me"): FakeResponse(200, {"id": "me"})})
    client = SpotifyClient("cid", FAKE_REFRESH, FAKE_SECRET, session=session)
    client.me_id
    assert session.calls[0][2]["headers"]["Authorization"].startswith("Basic ")


def test_401_triggers_single_refresh_then_retry():
    routes = {
        ("POST", sc.TOKEN_URL): [token_ok(), FakeResponse(200, {"access_token": "AT-second-token-9999"})],
        ("GET", "/me"): [FakeResponse(401, {"error": {"message": "expired"}}), FakeResponse(200, {"id": "me"})],
    }
    client, session, _ = make(routes)
    assert client.me_id == "me"
    tokens = [c for c in session.calls if c[1] == sc.TOKEN_URL]
    assert len(tokens) == 2
    assert session.calls[-1][2]["headers"]["Authorization"] == "Bearer AT-second-token-9999"


def test_persistent_401_fails_after_one_refresh():
    client, session, _ = make({("GET", "/me"): FakeResponse(401, {"error": {"message": "nope"}})})
    with pytest.raises(SpotifyError) as exc:
        client.me_id
    assert exc.value.status == 401
    assert len([c for c in session.calls if c[1] == sc.TOKEN_URL]) == 2


def test_429_honours_retry_after_and_retries():
    routes = {
        ("GET", "/me"): [
            FakeResponse(429, headers={"Retry-After": "7"}),
            FakeResponse(429, headers={"Retry-After": "2"}),
            FakeResponse(200, {"id": "me"}),
        ]
    }
    client, _, sleeps = make(routes)
    assert client.me_id == "me"
    assert sleeps == [7.0, 2.0]


def test_429_gives_up_after_max_retries():
    client, session, sleeps = make({("GET", "/me"): FakeResponse(429, headers={"Retry-After": "1"})})
    with pytest.raises(SpotifyError) as exc:
        client.me_id
    assert exc.value.status == 429
    assert len(sleeps) == sc.MAX_RETRIES
    assert len(session.on_api()) == sc.MAX_RETRIES + 1


def test_429_missing_header_defaults_to_one_second():
    client, _, sleeps = make({("GET", "/me"): [FakeResponse(429), FakeResponse(200, {"id": "m"})]})
    client.me_id
    assert sleeps == [1.0]


def test_429_absurd_retry_after_is_an_error_not_a_sleep():
    client, _, sleeps = make({("GET", "/me"): FakeResponse(429, headers={"Retry-After": "99999"})})
    with pytest.raises(SpotifyError):
        client.me_id
    assert sleeps == []


def test_token_refresh_failure_raises():
    client, _, _ = make({("POST", sc.TOKEN_URL): FakeResponse(400, {"error": "invalid_grant"})})
    with pytest.raises(SpotifyError, match="token refresh failed"):
        client.me_id


# ------------------------------------------------------------ paging & normalising


def paged_routes(load_fixture):
    def saved(method, url, kw):
        page = load_fixture("saved_tracks_page1.json" if kw["params"]["offset"] == 0 else "saved_tracks_page2.json")
        return FakeResponse(200, page)

    def playlists(method, url, kw):
        page = load_fixture("playlists_page1.json" if kw["params"]["offset"] == 0 else "playlists_page2.json")
        return FakeResponse(200, page)

    return {
        ("GET", "/me/tracks"): saved,
        ("GET", "/me/playlists"): playlists,
        ("GET", "/me"): FakeResponse(200, {"id": "me_user"}),
        ("GET", "/playlists/abc123/items"): FakeResponse(200, load_fixture("playlist_items_page.json")),
    }


def test_saved_tracks_paging_and_skipping(load_fixture):
    client, session, _ = make(paged_routes(load_fixture))
    tracks = list(client.iter_saved_tracks())
    assert len(tracks) == 60  # 63 entries: null, local and episode skipped
    assert client.skipped_entries == 3
    assert all(t.uri.startswith("spotify:track:") and t.added_at.tzinfo for t in tracks)
    limits = {c[2]["params"]["limit"] for c in session.on_api()}
    assert limits == {50}
    assert [c[2]["params"]["offset"] for c in session.on_api()] == [0, 50]


def test_track_normalisation_fields(load_fixture):
    client, _, _ = make(paged_routes(load_fixture))
    t = next(client.iter_saved_tracks())
    assert t.name and t.artists and t.artists[0].name
    assert t.release_date_precision in {"year", "month", "day"}
    assert t.isrc and isinstance(t.explicit, bool)


def test_playlists_classified_owned_collab_followed(load_fixture):
    client, session, _ = make(paged_routes(load_fixture))
    pls = list(client.iter_my_playlists())
    assert len(pls) == 53
    assert sum(p.owned for p in pls) == 29
    assert sum(p.collaborative and not p.owned for p in pls) == 3
    usable = [p for p in pls if p.usable]
    assert len(usable) == 32
    assert all(p.items_total is not None for p in pls)
    assert {c[2]["params"]["limit"] for c in session.on_api() if c[1].endswith("/playlists")} == {50}


def test_playlist_items_use_item_key_and_skip_junk(load_fixture):
    client, session, _ = make(paged_routes(load_fixture))
    tracks = list(client.iter_playlist_items("abc123"))
    assert len(tracks) == 5
    assert client.skipped_entries == 3
    assert session.on_api()[-1][2]["params"]["limit"] == 100


def test_playlist_id_is_validated():
    client, _, _ = make()
    with pytest.raises(ValueError):
        list(client.iter_playlist_items("../../me/library"))


@pytest.mark.parametrize(
    "obj",
    [
        None,
        {"type": "episode", "uri": uri(1)},
        {"type": "track", "is_local": True, "uri": uri(1)},
        {"type": "track", "uri": "spotify:local:a:b:c:1"},
        {"type": "track", "uri": "spotify:album:" + "a" * 22},
        {"type": "track"},
    ],
)
def test_track_from_api_rejects_non_tracks(obj):
    assert sc.track_from_api(obj) is None


# ------------------------------------------------------------ writes: shapes, batching, validation


def writable(routes=None):
    return make(routes, dry_run=False)


def test_add_playlist_items_shape_and_batching():
    calls = []

    def add(method, url, kw):
        calls.append(kw["json"])
        return FakeResponse(201, {"snapshot_id": f"s{len(calls)}"})

    client, session, _ = writable({("POST", "/playlists/pl1/items"): add})
    snap = client.add_playlist_items("pl1", [uri(i) for i in range(250)])
    assert [len(c["uris"]) for c in calls] == [100, 100, 50]
    assert all(set(c) == {"uris"} for c in calls)
    assert snap == "s3"


def test_remove_playlist_items_shape_and_snapshot_chaining():
    bodies = []

    def rm(method, url, kw):
        bodies.append(kw["json"])
        return FakeResponse(200, {"snapshot_id": f"s{len(bodies)}"})

    client, _, _ = writable({("DELETE", "/playlists/pl1/items"): rm})
    client.remove_playlist_items("pl1", [uri(i) for i in range(150)], snapshot_id="prev")
    assert bodies[0]["snapshot_id"] == "prev"
    assert bodies[1]["snapshot_id"] == "s1"  # chained from the previous write, not a GET
    assert bodies[0]["items"][0] == {"uri": uri(0)}
    assert [len(b["items"]) for b in bodies] == [100, 50]


def test_remove_playlist_items_without_snapshot_omits_key():
    client, session, _ = writable({("DELETE", "/playlists/pl1/items"): FakeResponse(200, {})})
    client.remove_playlist_items("pl1", [uri(1)])
    assert "snapshot_id" not in session.on_api()[-1][2]["json"]


def test_library_calls_use_query_string_never_body_and_batch_40():
    seen = []

    def lib(method, url, kw):
        seen.append((method, kw.get("params"), kw.get("json")))
        return FakeResponse(200, None, text="")

    client, _, _ = writable({("DELETE", "/me/library"): lib})
    client.remove_saved_tracks([uri(i) for i in range(85)])
    assert [len(p["uris"].split(",")) for _, p, _ in seen] == [40, 40, 5]
    assert all(j is None and m == "DELETE" for m, _, j in seen)


def test_contains_saved_batches_and_maps():
    def contains(method, url, kw):
        n = len(kw["params"]["uris"].split(","))
        assert n <= 40
        return FakeResponse(200, [i % 2 == 0 for i in range(n)])

    client, session, _ = make({("GET", "/me/library/contains"): contains})  # dry-run OK: read-only
    result = client.contains_saved([uri(i) for i in range(45)])
    assert len(result) == 45 and result[uri(0)] is True and result[uri(1)] is False
    assert len(session.on_api()) == 2


def test_contains_saved_rejects_bad_length_response():
    client, _, _ = make({("GET", "/me/library/contains"): FakeResponse(200, [True])})
    with pytest.raises(SpotifyError):
        client.contains_saved([uri(1), uri(2)])


def test_save_tracks_skips_already_liked_to_protect_added_at():
    puts = []

    def lib(method, url, kw):
        puts.append(kw["params"]["uris"])
        return FakeResponse(200, None, text="")

    def contains(method, url, kw):
        return FakeResponse(200, [u == uri(1) for u in kw["params"]["uris"].split(",")])

    client, _, _ = writable({("PUT", "/me/library"): lib, ("GET", "/me/library/contains"): contains})
    sent = client.save_tracks([uri(1), uri(2)])
    assert sent == [uri(2)] and puts == [uri(2)]


def test_save_tracks_allow_resave_skips_contains_check():
    client, session, _ = writable({("PUT", "/me/library"): FakeResponse(200, None, text="")})
    client.save_tracks([uri(1)], allow_resave=True)
    assert [c[0] for c in session.on_api()] == ["PUT"]


@pytest.mark.parametrize(
    "bad",
    [
        "spotify:album:" + "a" * 22,
        "spotify:playlist:" + "a" * 22,
        "spotify:user:someone",
        "spotify:track:short",
        "https://open.spotify.com/track/" + "a" * 22,
        "a" * 22,
        "",
        "spotify:local:a:b:c:1",
    ],
)
@pytest.mark.parametrize("method", ["save_tracks", "remove_saved_tracks", "add_playlist_items", "contains_saved"])
def test_only_track_uris_are_ever_sent(method, bad):
    client, session, _ = writable()
    args = ("pl1", [uri(1), bad]) if method == "add_playlist_items" else ([uri(1), bad],)
    with pytest.raises(ValueError):
        getattr(client, method)(*args)
    assert session.on_api() == []  # nothing sent, not even the valid half


# ------------------------------------------------------------ dry-run guarantee (criterion 3)


def test_dry_run_is_default():
    client, _, _ = make()
    assert client.dry_run is True


WRITE_CALLS = [
    ("add_playlist_items", ("pl1", [uri(1)])),
    ("add_playlist_items", ("pl1", [])),
    ("remove_playlist_items", ("pl1", [uri(1)])),
    ("save_tracks", ([uri(1)],)),
    ("save_tracks", ([uri(1)], )),
    ("remove_saved_tracks", ([uri(1)],)),
    ("remove_saved_tracks", ([],)),
]


@pytest.mark.parametrize("method,args", WRITE_CALLS)
def test_dry_run_refuses_every_write_and_makes_no_http_call(method, args):
    client, session, _ = make()
    with pytest.raises(DryRunError):
        getattr(client, method)(*args)
    assert session.calls == []


def test_dry_run_low_level_request_refuses_non_get():
    client, session, _ = make()
    for m in ("POST", "PUT", "DELETE", "PATCH"):
        with pytest.raises(DryRunError):
            client._request(m, "/me/library")
    assert session.calls == []


def test_full_read_workflow_in_dry_run_sees_only_gets_on_api(load_fixture):
    """Every read path in dry-run: the API host only ever receives GET (token refresh is the sole POST)."""
    routes = paged_routes(load_fixture)
    routes[("GET", "/me/library/contains")] = lambda m, u, kw: FakeResponse(200, [False] * len(kw["params"]["uris"].split(",")))
    client, session, _ = make(routes)
    list(client.iter_saved_tracks())
    list(client.iter_my_playlists())
    list(client.iter_playlist_items("abc123"))
    client.contains_saved([uri(1), uri(2)])
    assert {c[0] for c in session.on_api()} == {"GET"}
    non_get = [c for c in session.calls if c[0] != "GET"]
    assert all(c[1] == sc.TOKEN_URL for c in non_get)


# ------------------------------------------------------------ secrets never leak (criterion 4)


def echoing_routes():
    """Server errors that echo every secret back, like a misbehaving proxy might."""
    echo = f"bad request: token={FAKE_ACCESS} refresh_token={FAKE_REFRESH} client_secret={FAKE_SECRET} Bearer {FAKE_ACCESS}"
    return {
        ("GET", "/me"): FakeResponse(400, None, text=echo),
        ("GET", "/me/tracks"): FakeResponse(500, {"error": {"message": echo}}),
        ("POST", sc.TOKEN_URL): FakeResponse(200, {"access_token": FAKE_ACCESS}),
    }


def test_exceptions_never_contain_secrets(caplog):
    caplog.set_level(logging.DEBUG)
    session = FakeSession(echoing_routes())
    client = SpotifyClient("cid", FAKE_REFRESH, FAKE_SECRET, session=session, sleep=lambda s: None)
    for action in (lambda: client.me_id, lambda: list(client.iter_saved_tracks())):
        with pytest.raises(SpotifyError) as exc:
            action()
        text = str(exc.value) + repr(exc.value)
        for secret in (FAKE_ACCESS, FAKE_REFRESH, FAKE_SECRET):
            assert secret not in text
    assert FAKE_ACCESS not in caplog.text and FAKE_REFRESH not in caplog.text and FAKE_SECRET not in caplog.text


def test_token_endpoint_errors_never_contain_secrets():
    echo = f"invalid refresh_token={FAKE_REFRESH} for secret {FAKE_SECRET}"
    session = FakeSession({("POST", sc.TOKEN_URL): FakeResponse(400, None, text=echo)})
    client = SpotifyClient("cid", FAKE_REFRESH, FAKE_SECRET, session=session)
    with pytest.raises(SpotifyError) as exc:
        client.refresh_access_token()
    assert FAKE_REFRESH not in str(exc.value) and FAKE_SECRET not in str(exc.value)


def test_network_exception_message_is_scrubbed():
    import requests

    class Boom(FakeSession):
        def request(self, method, url, **kw):
            raise requests.ConnectionError(f"failed with {FAKE_REFRESH}")

    client = SpotifyClient("cid", FAKE_REFRESH, session=Boom())
    with pytest.raises(SpotifyError) as exc:
        client.refresh_access_token()
    assert FAKE_REFRESH not in str(exc.value)


def test_debug_logging_of_a_full_run_has_no_tokens(caplog, load_fixture):
    caplog.set_level(logging.DEBUG)
    client, _, _ = make(paged_routes(load_fixture))
    list(client.iter_saved_tracks())
    assert FAKE_ACCESS not in caplog.text and FAKE_REFRESH not in caplog.text
    assert "Authorization" not in caplog.text


@pytest.mark.parametrize(
    "text",
    [
        f"Authorization: Bearer {FAKE_ACCESS}",
        f'{{"access_token": "{FAKE_ACCESS}"}}',
        f"refresh_token={FAKE_REFRESH}&x=1",
        f"client_secret: {FAKE_SECRET}",
        f"code=AQB-some-auth-code&state=1",
        f"code_verifier={FAKE_REFRESH}",
    ],
)
def test_scrub_removes_token_shapes(text):
    out = sc.scrub(text)
    for secret in (FAKE_ACCESS, FAKE_REFRESH, FAKE_SECRET, "AQB-some-auth-code"):
        assert secret not in out
    assert "[REDACTED]" in out


def test_scrub_removes_explicit_values():
    assert "hunter22" not in sc.scrub("value hunter22 here", ["hunter22"])


# ------------------------------------------------------------ from_env


def test_from_env_requires_vars_and_names_only_the_names():
    with pytest.raises(SpotifyError) as exc:
        SpotifyClient.from_env(environ={"SPOTIFY_CLIENT_ID": "x"})
    assert "SPOTIFY_REFRESH_TOKEN" in str(exc.value)


def test_from_env_builds_client_dry_run_by_default():
    c = SpotifyClient.from_env(environ={"SPOTIFY_CLIENT_ID": "x", "SPOTIFY_REFRESH_TOKEN": "y"})
    assert c.dry_run is True and c._client_secret is None


# ------------------------------------------------------------ live (skipped unless SPOTISORT_LIVE=1)


@pytest.mark.live
def test_live_smoke_counts():
    sc.load_env()
    counts = sc.smoke(SpotifyClient.from_env(dry_run=True))
    assert counts["liked"] > 0


def test_save_tracks_sends_nothing_when_everything_already_liked():
    client, session, _ = writable(
        {("GET", "/me/library/contains"): lambda m, u, kw: FakeResponse(200, [True] * len(kw["params"]["uris"].split(",")))}
    )
    assert client.save_tracks([uri(1), uri(2)]) == []
    assert [c[0] for c in session.on_api()] == ["GET"]


def test_smoke_output_is_counts_only(load_fixture, monkeypatch, capsys):
    routes = paged_routes(load_fixture)
    client, _, _ = make(routes)
    monkeypatch.setenv("SPOTISORT_LIVE", "1")
    monkeypatch.setattr(sc.SpotifyClient, "from_env", classmethod(lambda cls, **kw: client))
    assert sc.main(["--smoke", "--env", "missing.env"]) == 0
    out = capsys.readouterr().out
    assert all(line.split(": ")[1].isdigit() for line in out.strip().splitlines())
    assert "liked: 60" in out and "owned_playlists: 29" in out and "collaborative_playlists: 3" in out
