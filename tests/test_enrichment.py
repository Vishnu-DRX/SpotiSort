"""MusicBrainz provider, rate limiter, cache, playlist-learned language, and the Enricher (offline)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.enrichment.cache import EnrichmentCache
from src.enrichment.enricher import Enricher
from src.enrichment.musicbrainz import (
    USER_AGENT,
    MusicBrainz,
    MusicBrainzError,
    RateLimiter,
    tags_to_genres,
)
from src.enrichment.playlist_language import LanguageMap, resolve_language_playlists
from src.models import Artist, Playlist, Track

# Recorded (trimmed) shapes from the live MusicBrainz API.
ISRC_HIT = {
    "isrc": "TCADP1828007",
    "recordings": [
        {
            "id": "db441619-b4a5-429a-9f60-b1390b0089eb",
            "title": "Back to You",
            "tags": [],
            "artist-credit": [
                {
                    "name": "Timecop1983",
                    "joinphrase": " feat. ",
                    "artist": {
                        "id": "3452247c-719a-4a77-8d98-bf55becb449a",
                        "name": "Timecop1983",
                        "country": "NL",
                        "tags": [
                            {"name": "synthwave", "count": 3},
                            {"name": "electronic", "count": 1},
                            {"name": "80s", "count": 0},
                        ],
                    },
                },
                {
                    "name": "The Bad Dreamers",
                    "joinphrase": "",
                    "artist": {"id": "107ab38b", "name": "The Bad Dreamers", "country": "US", "tags": []},
                },
            ],
        }
    ],
}
ARTIST_SEARCH = {
    "artists": [
        {"id": "aaa", "score": 100, "name": "Bonobo", "tags": [{"name": "downtempo", "count": 5}],
         "area": {"iso-3166-1-codes": ["GB"]}},
        {"id": "bbb", "score": 60, "name": "Bonobo Jr"},
    ]
}


class Resp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body, headers or {}

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, responder):
        self.responder, self.calls = responder, []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params, headers))
        return self.responder(url, params)


class FakeClock:
    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def make_mb(responder, clock=None):
    clock = clock or FakeClock()
    limiter = RateLimiter(1.0, clock.now, clock.sleep)
    return MusicBrainz(FakeSession(responder), limiter, sleep=clock.sleep), clock


def track(name="Song", artist="Timecop1983", artist_id="sp1", isrc="TCADP1828007", tid="t1", album="Alb", extra=()):
    artists = (Artist(artist_id, artist),) + tuple(Artist(i, n) for i, n in extra)
    return Track(id=tid, uri="spotify:track:" + tid.ljust(22, "x"), name=name, artists=artists, album_name=album, isrc=isrc)


# ---------------------------------------------------------------- rate limiter


def test_rate_limiter_enforces_one_second_spacing():
    clock = FakeClock()
    lim = RateLimiter(1.0, clock.now, clock.sleep)
    stamps = []
    for _ in range(5):
        lim.wait()
        stamps.append(clock.t)
    assert all(b - a >= 1.0 - 1e-9 for a, b in zip(stamps, stamps[1:]))


def test_rate_limiter_does_not_sleep_when_enough_time_passed():
    clock = FakeClock()
    lim = RateLimiter(1.0, clock.now, clock.sleep)
    lim.wait()
    clock.t += 5
    lim.wait()
    assert clock.sleeps == []


def test_musicbrainz_requests_are_spaced_at_least_one_second():
    mb, clock = make_mb(lambda u, p: Resp(200, ISRC_HIT))
    times = []
    orig = mb._session.get

    def spy(*a, **k):
        times.append(clock.t)
        return orig(*a, **k)

    mb._session.get = spy
    for _ in range(4):
        mb.artists_for_isrc("TCADP1828007")
    assert all(b - a >= 1.0 - 1e-9 for a, b in zip(times, times[1:]))


# ---------------------------------------------------------------- provider behaviour


def test_isrc_lookup_parses_credits_tags_and_country():
    mb, _ = make_mb(lambda u, p: Resp(200, ISRC_HIT))
    infos = mb.artists_for_isrc("TCADP1828007")
    assert [i.name for i in infos] == ["Timecop1983", "The Bad Dreamers"]
    assert infos[0].genres == ["synthwave", "electronic"]  # count 0 dropped, ordered by votes
    assert infos[0].country == "NL" and infos[0].via == "isrc"


def test_isrc_request_shape_and_user_agent():
    mb, _ = make_mb(lambda u, p: Resp(200, ISRC_HIT))
    mb.artists_for_isrc("TCADP1828007")
    url, params, headers = mb._session.calls[0]
    assert url.endswith("/isrc/TCADP1828007") and params["fmt"] == "json" and params["inc"] == "artists+tags"
    assert headers["User-Agent"] == USER_AGENT
    assert "SpotiSort/" in USER_AGENT and "github.com/Vishnu-DRX/SpotiSort" in USER_AGENT


def test_isrc_404_returns_none():
    mb, _ = make_mb(lambda u, p: Resp(404, {"error": "Not Found"}))
    assert mb.artists_for_isrc("XX0000000000") is None


def test_isrc_empty_recordings_returns_none():
    mb, _ = make_mb(lambda u, p: Resp(200, {"recordings": []}))
    assert mb.artists_for_isrc("XX0000000000") is None


def test_503_is_retried_with_backoff_then_succeeds():
    seq = [Resp(503, {}), Resp(503, {}), Resp(200, ISRC_HIT)]
    mb, clock = make_mb(lambda u, p: seq.pop(0))
    assert mb.artists_for_isrc("TCADP1828007") is not None
    assert mb.requests_made == 3 and mb.retries_503 == 2
    assert len([s for s in clock.sleeps if s >= 2.0]) == 2


def test_503_forever_raises_after_bounded_retries():
    mb, _ = make_mb(lambda u, p: Resp(503, {}))
    with pytest.raises(MusicBrainzError):
        mb.artists_for_isrc("TCADP1828007")
    assert mb.requests_made == 5


def test_retry_after_header_is_honoured():
    seq = [Resp(429, {}, {"Retry-After": "7"}), Resp(200, ISRC_HIT)]
    mb, clock = make_mb(lambda u, p: seq.pop(0))
    mb.artists_for_isrc("TCADP1828007")
    assert 7.0 in clock.sleeps


def test_unexpected_status_raises():
    mb, _ = make_mb(lambda u, p: Resp(500, {}))
    with pytest.raises(MusicBrainzError):
        mb.artists_for_isrc("TCADP1828007")


def test_search_artist_requires_score_and_exact_name():
    mb, _ = make_mb(lambda u, p: Resp(200, ARTIST_SEARCH))
    hit = mb.search_artist("bonobo")
    assert hit.mbid == "aaa" and hit.genres == ["downtempo"] and hit.country == "GB" and hit.via == "search"


def test_search_artist_rejects_low_score_and_name_mismatch():
    mb, _ = make_mb(lambda u, p: Resp(200, ARTIST_SEARCH))
    assert mb.search_artist("Bonobo Jr") is None  # only a score-60 hit
    assert mb.search_artist("Totally Different") is None


def test_search_query_escapes_quotes():
    mb, _ = make_mb(lambda u, p: Resp(200, {"artists": []}))
    mb.search_artist('Bad "Name"')
    assert '"Name"' not in mb._session.calls[0][1]["query"].split('artist:"', 1)[1][:-1]


def test_tags_to_genres_handles_garbage():
    assert tags_to_genres(None) == []
    assert tags_to_genres([{"name": "Rock", "count": 2}, {"name": "rock", "count": 1}, "x", {"count": 3}]) == ["rock"]
    assert len(tags_to_genres([{"name": f"g{i}", "count": 1} for i in range(20)])) == 5


# ---------------------------------------------------------------- cache


def test_cache_roundtrip_and_atomic_write(tmp_path):
    p = tmp_path / "sub" / "enrichment.json"
    c = EnrichmentCache(p)
    c.put_artist("a1", {"genres": ["rock"]})
    c.put_isrc("I1", {"hit": False, "credits": []})
    c.save()
    assert p.exists() and not list(p.parent.glob("*.tmp"))
    c2 = EnrichmentCache(p)
    assert c2.get_artist("a1")["genres"] == ["rock"] and c2.get_isrc("I1")["hit"] is False


def test_cache_entries_go_stale_after_90_days(tmp_path):
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    now = [t0]
    c = EnrichmentCache(tmp_path / "c.json", now=lambda: now[0])
    c.put_artist("a", {"genres": []})
    now[0] = t0 + timedelta(days=89)
    assert c.get_artist("a") is not None
    now[0] = t0 + timedelta(days=91)
    assert c.get_artist("a") is None


def test_cache_ignores_corrupt_or_wrong_version_file(tmp_path):
    p = tmp_path / "c.json"
    p.write_text("{not json", encoding="utf-8")
    assert EnrichmentCache(p).get_artist("x") is None
    p.write_text('{"version": 99, "artists": {"x": {"fetched_at": "2026-01-01T00:00:00+00:00"}}}', encoding="utf-8")
    assert EnrichmentCache(p).get_artist("x") is None


def test_cache_failed_save_leaves_previous_file_intact(tmp_path, monkeypatch):
    p = tmp_path / "c.json"
    c = EnrichmentCache(p)
    c.put_artist("a", {"genres": ["x"]})
    c.save()
    before = p.read_text(encoding="utf-8")
    c.put_artist("b", {"genres": ["y"]})
    monkeypatch.setattr("src.enrichment.cache.os.replace", lambda *a: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(OSError):
        c.save()
    assert p.read_text(encoding="utf-8") == before and not list(tmp_path.glob("*.tmp"))


# ---------------------------------------------------------------- playlist-learned language


def test_language_map_artist_majority_and_track_direct():
    m = LanguageMap()
    m.add_playlist([track(tid="a", artist_id="x"), track(tid="b", artist_id="x")], "hindi")
    m.add(track(tid="c", artist_id="x"), "tamil")  # 2 hindi vs 1 tamil: 66% > 60%
    assert m.artist_language("x") == "hindi"
    assert m.language_for(track(tid="zz", artist_id="x")) == "hindi"
    assert m.language_for(track(tid="c", artist_id="x")) == "tamil"  # its own membership wins


def test_language_map_split_vote_is_unknown():
    m = LanguageMap()
    m.add(track(tid="a", artist_id="x"), "hindi")
    m.add(track(tid="b", artist_id="x"), "tamil")
    assert m.artist_language("x") is None
    assert m.language_for(track(tid="new", artist_id="x")) is None


def test_language_map_unknown_artist_none():
    assert LanguageMap().language_for(track()) is None


def test_language_map_uses_any_credited_artist():
    m = LanguageMap()
    m.add(track(tid="a", artist_id="x"), "malayalam")
    assert m.language_for(track(tid="n", artist_id="other", extra=[("x", "X")])) == "malayalam"


def pl(pid, name, owned=True, collab=False):
    return Playlist(id=pid, name=name, owner_id="me" if owned else "o", owned=owned, collaborative=collab)


def test_resolve_language_playlists_owned_and_collab_only():
    playlists = [pl("1", "Chill Hindi"), pl("2", "Followed", owned=False), pl("3", "Mallu", owned=False, collab=True)]
    ids, warns = resolve_language_playlists({"chill hindi": "hindi", "Mallu": "malayalam", "Followed": "tamil", "Nope": "urdu"}, playlists)
    assert ids == {"1": "hindi", "3": "malayalam"}
    assert len(warns) == 2


def test_resolve_language_playlists_ambiguous_name_skipped():
    ids, warns = resolve_language_playlists({"Dup": "hindi"}, [pl("1", "Dup"), pl("2", "dup")])
    assert ids == {} and "ambiguous" in warns[0]


# ---------------------------------------------------------------- enricher


def isrc_router(calls):
    def responder(url, params):
        calls.append(url)
        if "/isrc/" in url:
            return Resp(200, ISRC_HIT)
        return Resp(200, ARTIST_SEARCH)

    return responder


def test_enricher_resolves_genres_via_isrc_and_caches(tmp_path):
    calls = []
    mb, _ = make_mb(isrc_router(calls))
    e = Enricher(EnrichmentCache(tmp_path / "c.json"), mb)
    r = e.resolve(track())
    assert r.genres == ("synthwave", "electronic") and "musicbrainz" in r.sources
    assert len(calls) == 1


def test_second_run_makes_zero_musicbrainz_calls(tmp_path):
    path = tmp_path / "c.json"
    calls = []
    mb, _ = make_mb(isrc_router(calls))
    e1 = Enricher(EnrichmentCache(path), mb)
    tracks = [track(tid="t1"), track(tid="t2", artist="Bonobo", artist_id="sp2", isrc="GBAAA0000001")]
    first = [e1.resolve(t) for t in tracks]
    e1.cache.save()
    n = len(calls)
    assert n > 0
    mb2, _ = make_mb(isrc_router(calls))
    e2 = Enricher(EnrichmentCache(path), mb2)
    second = [e2.resolve(t) for t in tracks]
    assert len(calls) == n and mb2.requests_made == 0
    assert first == second


def test_same_artist_on_many_tracks_is_looked_up_once(tmp_path):
    calls = []
    mb, _ = make_mb(isrc_router(calls))
    e = Enricher(EnrichmentCache(tmp_path / "c.json"), mb)
    for i in range(5):
        e.resolve(track(tid=f"t{i}", isrc=f"TCADP18280{i:02d}"))
    assert len(calls) == 1


def test_falls_back_to_artist_search_when_isrc_unknown(tmp_path):
    def responder(url, params):
        return Resp(404, {}) if "/isrc/" in url else Resp(200, ARTIST_SEARCH)

    mb, _ = make_mb(responder)
    e = Enricher(EnrichmentCache(tmp_path / "c.json"), mb)
    r = e.resolve(track(artist="Bonobo", artist_id="sp2"))
    assert r.genres == ("downtempo",)


def test_negative_result_is_cached(tmp_path):
    calls = []

    def responder(url, params):
        calls.append(url)
        return Resp(404, {}) if "/isrc/" in url else Resp(200, {"artists": []})

    mb, _ = make_mb(responder)
    e = Enricher(EnrichmentCache(tmp_path / "c.json"), mb)
    e.resolve(track())
    n = len(calls)
    assert e.resolve(track(tid="other")).genres == ()
    assert len(calls) == n


def test_musicbrainz_error_is_not_cached_as_negative(tmp_path):
    mb, _ = make_mb(lambda u, p: Resp(500, {}))
    e = Enricher(EnrichmentCache(tmp_path / "c.json"), mb)
    assert e.resolve(track()).genres == () and e.errors == 1
    assert e.cache.get_artist("sp1") is None


def test_disabled_musicbrainz_uses_cache_only(tmp_path):
    c = EnrichmentCache(tmp_path / "c.json")
    c.put_artist("sp1", {"genres": ["jazz"]})
    e = Enricher(c, None)
    assert e.resolve(track()).genres == ("jazz",)
    assert e.resolve(track(artist_id="unknown")).genres == ()


def test_language_order_playlist_beats_script(tmp_path):
    m = LanguageMap()
    m.add(track(tid="a", artist_id="sp9"), "tamil")
    e = Enricher(EnrichmentCache(tmp_path / "c.json"), None, m)
    r = e.resolve(track(name="केसरिया", artist_id="sp9", tid="z"))
    assert r.language == "tamil" and "playlist" in r.sources and "script" not in r.sources


def test_language_falls_back_to_script_then_none(tmp_path):
    e = Enricher(EnrichmentCache(tmp_path / "c.json"), None, LanguageMap())
    r = e.resolve(track(name="केसरिया", artist="Arijit", artist_id="q"))
    assert r.language == "hindi" and r.sources == ("script",)
    assert e.resolve(track(name="Plain English", artist_id="q2")).language is None


def test_track_without_artists_does_not_crash(tmp_path):
    t = Track(id="t", uri="spotify:track:" + "t" * 22, name="x", artists=())
    assert Enricher(EnrichmentCache(tmp_path / "c.json"), None).resolve(t).genres == ()


def test_lowercase_isrc_is_uppercased_for_musicbrainz():
    mb, _ = make_mb(lambda u, p: Resp(200, ISRC_HIT))
    mb.artists_for_isrc("tcadp1828007")
    assert mb._session.calls[0][0].endswith("/isrc/TCADP1828007")
