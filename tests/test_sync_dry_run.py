"""End-to-end offline runs of `python -m src.sync` (dry-run) with fake clients / a fake HTTP layer."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone

import pytest
import requests

from src import spotify_client as sc
from src import sync
from src.models import Artist, Playlist, Track

TODAY = datetime.now(timezone.utc).date().isoformat()
FAKE_ACCESS = "AT-fake-access-token-1234567890"
FAKE_REFRESH = "RT-fake-refresh-token-abcdefghij"
LOG_KEYS = {
    "date", "dry_run", "evaluated", "moved", "skipped_no_match", "skipped_too_young",
    "skipped_playlist_missing", "errors", "warnings", "journal", "http_audit", "runtime_seconds",
}


def days_ago(n):
    return datetime.now(timezone.utc) - timedelta(days=n)


def mk_track(n, artist, age):
    return Track(
        id=f"t{n}", uri=f"spotify:track:t{n}", name=f"Song {n}",
        artists=(Artist(f"a-{artist}", artist),), album_name="Album",
        release_date="2005-06-01", release_date_precision="day", added_at=days_ago(age),
    )


def mk_pl(name, id, owned=True):
    return Playlist(id=id, name=name, owner_id="me" if owned else "other", owned=owned, collaborative=False)


TRACKS = [
    mk_track(1, "Bonobo", 90),     # old  -> Chill
    mk_track(2, "Bonobo", 40),     # old  -> Chill
    mk_track(3, "Bonobo", 2),      # young
    mk_track(4, "Tycho", 60),      # old  -> Ghost (missing playlist)
    mk_track(5, "Nobody", 60),     # no match
    mk_track(6, "Bonobo", 20),     # old  -> Chill
]
PLAYLISTS = [mk_pl("Chill", "chill1"), mk_pl("Other", "other1")]

CONFIG = """\
default_days_threshold: 14
rules:
  - name: chill
    match:
      artist_in: ["Bonobo"]
    target_playlist: Chill
  - name: ghost
    match:
      artist_in: ["Tycho"]
    target_playlist: Ghost Playlist
"""


class FakeClient:
    instances: list = []
    calls: list = []
    tracks = TRACKS
    playlists = PLAYLISTS
    items = {"chill1": [TRACKS[0]]}

    def __init__(self, dry_run):
        self.dry_run = dry_run
        FakeClient.instances.append(self)

    @classmethod
    def from_env(cls, dry_run=True, session=None, **kw):
        cls.calls.append("from_env")
        return cls(dry_run)

    def iter_saved_tracks(self):
        FakeClient.calls.append("iter_saved_tracks")
        return iter(list(self.tracks))

    def iter_my_playlists(self):
        FakeClient.calls.append("iter_my_playlists")
        return iter(list(self.playlists))

    def iter_playlist_items(self, pid):
        FakeClient.calls.append(f"iter_playlist_items:{pid}")
        return iter(list(self.items.get(pid, [])))


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    FakeClient.instances, FakeClient.calls = [], []
    monkeypatch.setattr(sync, "SpotifyClient", FakeClient)
    monkeypatch.setattr(sync, "load_env", lambda *a, **k: False)


@pytest.fixture
def env(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(CONFIG, encoding="utf-8")
    return tmp_path, cfg


def argv(tmp_path, cfg, *extra):
    return [
        "--config", str(cfg), "--logs-dir", str(tmp_path / "logs"), "--cache", str(tmp_path / "cache.json"),
        "--no-network", "--env", str(tmp_path / "nonexistent.env"), *extra,
    ]


def run(tmp_path, cfg, *extra):
    return sync.main(argv(tmp_path, cfg, *extra))


def read_log(tmp_path):
    return json.loads((tmp_path / "logs" / f"{TODAY}.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ fake-client runs

def test_dry_run_writes_log_with_all_keys(env):
    tmp, cfg = env
    assert run(tmp, cfg) == 0
    log = read_log(tmp)
    assert LOG_KEYS <= set(log)
    assert log["date"] == TODAY and log["dry_run"] is True
    assert log["errors"] == []
    assert isinstance(log["runtime_seconds"], (int, float))
    assert isinstance(log["http_audit"], dict)


def test_counts_and_moves(env):
    tmp, cfg = env
    run(tmp, cfg)
    log = read_log(tmp)
    assert log["evaluated"] == 6
    assert sorted(m["uri"] for m in log["moved"]) == ["spotify:track:t1", "spotify:track:t2", "spotify:track:t6"]
    assert log["skipped_no_match"] == 1
    assert [s["track"] for s in log["skipped_too_young"]] == ["Song 3"]
    assert all(m["rule"] == "chill" and m["playlist_id"] == "chill1" for m in log["moved"])
    assert all(m["matched"] == {"artist_in": "Bonobo"} for m in log["moved"])


def test_moves_newest_first(env):
    tmp, cfg = env
    run(tmp, cfg)
    assert [m["uri"] for m in read_log(tmp)["moved"]] == ["spotify:track:t6", "spotify:track:t2", "spotify:track:t1"]


def test_journal_matches_moves_one_to_one(env):
    tmp, cfg = env
    run(tmp, cfg)
    log = read_log(tmp)
    assert len(log["journal"]) == len(log["moved"]) == 3
    for j, m in zip(log["journal"], log["moved"]):
        assert set(j) == {"uri", "name", "artists", "original_added_at", "target_playlist_id"}
        assert j["uri"] == m["uri"] and j["name"] == m["track"] and j["artists"] == m["artist"]
        assert j["original_added_at"] == m["original_added_at"] and j["original_added_at"]
        assert j["target_playlist_id"] == m["playlist_id"] == "chill1"


def test_already_in_target_flag_uses_playlist_contents(env):
    tmp, cfg = env
    run(tmp, cfg)
    flags = {m["uri"]: m["already_in_target"] for m in read_log(tmp)["moved"]}
    assert flags == {"spotify:track:t1": True, "spotify:track:t2": False, "spotify:track:t6": False}
    assert "iter_playlist_items:chill1" in FakeClient.calls
    assert "iter_playlist_items:other1" not in FakeClient.calls


def test_missing_playlist_recorded_warned_exit_zero(env, capsys):
    tmp, cfg = env
    assert run(tmp, cfg) == 0
    log = read_log(tmp)
    (s,) = log["skipped_playlist_missing"]
    assert s["target_playlist"] == "Ghost Playlist" and s["reason"] == "missing" and s["would_create"] is False
    assert any("Ghost Playlist" in w for w in log["warnings"])
    assert "Ghost Playlist" in capsys.readouterr().out


def test_stdout_summary_says_dry_run(env, capsys):
    tmp, cfg = env
    run(tmp, cfg)
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "no writes performed" in out
    assert "would move: 3" in out and "-> Chill: 3" in out
    assert f"{TODAY}.json" in out


def test_client_created_in_dry_run_mode(env):
    tmp, cfg = env
    run(tmp, cfg)
    assert len(FakeClient.instances) == 1 and FakeClient.instances[0].dry_run is True


def test_apply_without_selector_returns_2_and_does_nothing(env, capsys):
    tmp, cfg = env
    assert run(tmp, cfg, "--apply") == 2
    assert FakeClient.instances == [] and FakeClient.calls == []
    assert not (tmp / "logs").exists()
    err = capsys.readouterr().err
    assert "--apply" in err and "selector" in err


@pytest.mark.parametrize("content", [
    None,                                   # missing file
    "rules: [",                             # YAML syntax error
    "rules: not-a-list\n",                  # wrong type
    "bogus_key: 1\nrules: []\n",            # unknown top-level key
    "rules:\n  - name: x\n    target_playlist: P\n    match: {nope: 1}\n",  # unknown match key
])
def test_bad_config_returns_1_no_log(tmp_path, content, capsys):
    cfg = tmp_path / "config.yaml"
    if content is not None:
        cfg.write_text(content, encoding="utf-8")
    assert run(tmp_path, cfg) == 1
    assert not (tmp_path / "logs").exists()
    assert "error" in capsys.readouterr().err.lower()


def test_bad_since_returns_1(env, capsys):
    tmp, cfg = env
    assert run(tmp, cfg, "--since", "not-a-date") == 1
    assert not (tmp / "logs").exists()


def test_limit_flag_caps_moves_oldest_first(env):
    tmp, cfg = env
    assert run(tmp, cfg, "--limit", "2") == 0
    log = read_log(tmp)
    assert [m["uri"] for m in log["moved"]] == ["spotify:track:t2", "spotify:track:t1"]
    assert len(log["journal"]) == 2 and log["evaluated"] == 6


def test_since_flag_filters_candidates(env):
    tmp, cfg = env
    since = (datetime.now(timezone.utc) - timedelta(days=50)).date().isoformat()
    assert run(tmp, cfg, "--since", since) == 0
    log = read_log(tmp)
    assert sorted(m["uri"] for m in log["moved"]) == ["spotify:track:t2", "spotify:track:t6"]
    assert log["evaluated"] == 3  # t2 (40d), t3 (2d), t6 (20d); the 60/90-day tracks are excluded


def test_since_flag_evaluated_matches_added_at(env):
    tmp, cfg = env
    since = (datetime.now(timezone.utc) - timedelta(days=50)).date().isoformat()
    run(tmp, cfg, "--since", since)
    expected = sum(1 for t in TRACKS if t.added_at >= datetime.fromisoformat(since).replace(tzinfo=timezone.utc))
    assert read_log(tmp)["evaluated"] == expected


def test_rule_flag_restricts_to_named_rule(env):
    tmp, cfg = env
    assert run(tmp, cfg, "--rule", "GHOST") == 0
    log = read_log(tmp)
    assert log["moved"] == [] and log["journal"] == []
    assert len(log["skipped_playlist_missing"]) == 1
    assert log["skipped_no_match"] == 5
    assert "iter_playlist_items:chill1" not in FakeClient.calls


def test_rule_flag_selects_chill_only(env):
    tmp, cfg = env
    run(tmp, cfg, "--rule", "chill")
    log = read_log(tmp)
    assert len(log["moved"]) == 3 and log["skipped_playlist_missing"] == []


def test_fallback_playlist_and_rule_flag(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(CONFIG + "fallback_playlist: Other\n", encoding="utf-8")
    run(tmp_path, cfg)
    moved = {m["uri"]: m["rule"] for m in read_log(tmp_path)["moved"]}
    assert moved["spotify:track:t5"] == "(fallback_playlist)"
    run(tmp_path, cfg, "--rule", "chill")
    assert "spotify:track:t5" not in {m["uri"] for m in read_log(tmp_path)["moved"]}


def test_logs_dir_created_if_missing(env):
    tmp, cfg = env
    assert not (tmp / "logs").exists()
    run(tmp, cfg)
    assert (tmp / "logs" / f"{TODAY}.json").is_file()


def test_log_is_valid_utf8_json_with_non_ascii(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(CONFIG, encoding="utf-8")
    t = Track("tx", "spotify:track:tx", "Motoki 日本語", (Artist("a", "Bonobo"),), added_at=days_ago(50))
    FakeClient.tracks = [t]
    try:
        run(tmp_path, cfg)
    finally:
        FakeClient.tracks = TRACKS
    raw = (tmp_path / "logs" / f"{TODAY}.json").read_text(encoding="utf-8")
    assert "日本語" in raw and json.loads(raw)["moved"][0]["track"] == "Motoki 日本語"


def test_empty_library(env, capsys):
    tmp, cfg = env
    FakeClient.tracks = []
    try:
        assert run(tmp, cfg) == 0
    finally:
        FakeClient.tracks = TRACKS
    log = read_log(tmp)
    assert log["evaluated"] == 0 and log["moved"] == []
    assert "DRY RUN" in capsys.readouterr().out


def test_no_token_like_strings_in_log(env):
    tmp, cfg = env
    run(tmp, cfg)
    raw = (tmp / "logs" / f"{TODAY}.json").read_text(encoding="utf-8")
    for needle in (FAKE_ACCESS, FAKE_REFRESH, "Bearer", "Authorization", "refresh_token", "access_token"):
        assert needle not in raw
    assert not re.search(r"(AT|RT|CS)-[A-Za-z0-9-]{10,}", raw)


def test_only_expected_artifacts_written(env):
    tmp, cfg = env
    run(tmp, cfg)
    assert sorted(p.name for p in (tmp / "logs").iterdir()) == sorted([f"{TODAY}.json", "latest-plan.json", "runs.json"])


def test_musicbrainz_flag_is_not_used_with_no_network(env, monkeypatch):
    tmp, cfg = env

    def boom(*a, **k):
        raise AssertionError("MusicBrainz must not be constructed with --no-network")

    monkeypatch.setattr(sync, "MusicBrainz", boom)
    assert run(tmp, cfg) == 0


# ---------------------------------------------------- real SpotifyClient + fake HTTP layer

class Resp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body
        self.headers = {}
        self.text = json.dumps(body) if body is not None else ""
        self.content = self.text.encode()

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


@pytest.fixture
def http(monkeypatch, load_fixture):
    """Route every requests.Session.request (incl. sync.AuditSession's super call) to fixtures."""
    seen: list[tuple[str, str]] = []
    saved = [load_fixture("saved_tracks_page1.json"), load_fixture("saved_tracks_page2.json")]
    pls = [load_fixture("playlists_page1.json"), load_fixture("playlists_page2.json")]
    items = load_fixture("playlist_items_page.json")

    def fake_request(self, method, url, **kwargs):
        seen.append((method.upper(), url))
        if url == sc.TOKEN_URL:
            return Resp(200, {"access_token": FAKE_ACCESS, "expires_in": 3600})
        path = url[len(sc.API_BASE):] if url.startswith(sc.API_BASE) else None
        if path is None or method.upper() != "GET":
            return Resp(404, {"error": {"status": 404, "message": "unexpected"}})
        offset = (kwargs.get("params") or {}).get("offset", 0)
        if path == "/me":
            return Resp(200, {"id": "me_user"})
        if path == "/me/tracks":
            return Resp(200, saved[0 if offset == 0 else 1])
        if path == "/me/playlists":
            return Resp(200, pls[0 if offset == 0 else 1])
        if re.fullmatch(r"/playlists/[A-Za-z0-9]+/items", path):
            return Resp(200, items)
        return Resp(404, {"error": {"status": 404, "message": f"no route {path}"}})

    monkeypatch.setattr(requests.Session, "request", fake_request)
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "cid")
    monkeypatch.setenv("SPOTIFY_REFRESH_TOKEN", FAKE_REFRESH)
    monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)
    monkeypatch.setattr(sync, "SpotifyClient", sc.SpotifyClient)
    return seen


REAL_CONFIG = """\
default_days_threshold: 14
rules:
  - name: garden
    match:
      artist_in: ["GARDEN", "Falkerry"]
    target_playlist: Playlist 00
  - name: ghost
    match:
      artist_in: ["Kalandra"]
    target_playlist: Does Not Exist
  - name: followed
    match:
      artist_in: ["The Black Keys"]
    target_playlist: Playlist 02
"""


def test_real_client_full_run_only_gets(tmp_path, http, capsys):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(REAL_CONFIG, encoding="utf-8")
    assert run(tmp_path, cfg) == 0

    assert http, "expected some HTTP traffic"
    api_calls = [(m, u) for m, u in http if u.startswith(sc.API_BASE)]
    assert api_calls and all(m == "GET" for m, _ in api_calls)
    assert [(m, u) for m, u in http if m != "GET"] == [("POST", sc.TOKEN_URL)]

    log = read_log(tmp_path)
    assert log["dry_run"] is True and LOG_KEYS <= set(log)
    audit = log["http_audit"]
    assert audit["POST accounts.spotify.com"] == 1
    non_get_api = {k: v for k, v in audit.items() if k.endswith("api.spotify.com") and not k.startswith("GET")}
    assert non_get_api == {}
    assert audit["GET api.spotify.com"] >= 4
    assert set(audit) <= {"GET api.spotify.com", "POST accounts.spotify.com"}

    assert log["evaluated"] == 60
    assert {m["playlist"] for m in log["moved"]} == {"Playlist 00"}
    assert {m["artist"] for m in log["moved"]} <= {"GARDEN", "Falkerry"} and log["moved"]
    assert len(log["journal"]) == len(log["moved"])
    reasons = {s["target_playlist"]: s["reason"] for s in log["skipped_playlist_missing"]}
    assert reasons.get("Does Not Exist") == "missing"
    assert reasons.get("Playlist 02") == "not_writable"
    assert "DRY RUN" in capsys.readouterr().out


def test_real_client_log_has_no_secrets(tmp_path, http):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(REAL_CONFIG, encoding="utf-8")
    run(tmp_path, cfg)
    raw = (tmp_path / "logs" / f"{TODAY}.json").read_text(encoding="utf-8")
    for needle in (FAKE_ACCESS, FAKE_REFRESH, "Bearer", "cid"):
        assert needle not in raw


def test_real_client_apply_makes_no_http_calls(tmp_path, http):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(REAL_CONFIG, encoding="utf-8")
    assert run(tmp_path, cfg, "--apply") == 2
    assert http == [] and not (tmp_path / "logs").exists()
