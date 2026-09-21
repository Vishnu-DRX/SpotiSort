"""Offline tests for src/analyze.py: profiling, rule inference, draft rendering and the end-to-end CLI."""

from __future__ import annotations

import pytest
import yaml

from src import analyze
from src.analyze import (
    ARTIST_SHARE,
    EXPLICIT_HIGH,
    MIN_TRACKS,
    Profile,
    analyze_playlist,
    dominant_language,
    infer_rule,
    render_draft,
)
from src.config import parse_config
from src.models import Artist, Enrichment, Playlist, Track
from src.spotify_client import SpotifyError


# ------------------------------------------------------------------ helpers

def trk(n=1, artist="Bonobo", year="2005", precision="year", explicit=False, **kw) -> Track:
    base = dict(
        id=f"t{n}", uri=f"spotify:track:t{n}", name=f"Song {n}",
        artists=(Artist(f"a-{artist}", artist),), album_name="Album",
        release_date=year, release_date_precision=precision, explicit=explicit,
    )
    base.update(kw)
    return Track(**base)


def enr(genres=(), language=None) -> Enrichment:
    return Enrichment(genres=tuple(genres), language=language)


def prof(name="Mix", tracks=20, **kw) -> Profile:
    return Profile(name=name, tracks=tracks, **kw)


def roundtrip(text: str):
    data = yaml.safe_load(text)
    return data, parse_config(data)


# ------------------------------------------------------------------ analyze_playlist

def test_empty_playlist_profile():
    p = analyze_playlist("Empty", [], {})
    assert p.tracks == 0 and p.top_genres == [] and p.top_artists == []
    assert p.languages == {} and p.explicit_ratio == 0.0
    assert p.year_p10 is None and p.year_p90 is None and p.year_median is None


def test_top_artists_counted_and_ordered():
    tracks = [trk(i, "A") for i in range(3)] + [trk(10 + i, "B") for i in range(2)] + [trk(20, "C")]
    p = analyze_playlist("X", tracks, {})
    assert p.top_artists == [("A", 3), ("B", 2), ("C", 1)]


def test_top_artists_capped_at_five():
    tracks = [trk(i, f"Artist{i}") for i in range(8)]
    assert len(analyze_playlist("X", tracks, {}).top_artists) == 5


def test_multi_artist_track_credits_every_artist():
    t = trk(1, artists=(Artist("1", "A"), Artist("2", "B")))
    p = analyze_playlist("X", [t], {})
    assert dict(p.top_artists) == {"A": 1, "B": 1}


def test_blank_artist_name_ignored():
    t = trk(1, artists=(Artist("1", ""), Artist("2", "B")))
    assert analyze_playlist("X", [t], {}).top_artists == [("B", 1)]


def test_top_genres_and_genre_tracks():
    tracks = [trk(i) for i in range(4)]
    en = {"t0": enr(["jazz", "bebop"]), "t1": enr(["jazz"]), "t2": enr(["rock"]), "t3": enr()}
    p = analyze_playlist("X", tracks, en)
    assert p.genre_tracks == 3
    assert p.top_genres[0] == ("jazz", 2)
    assert dict(p.top_genres) == {"jazz": 2, "bebop": 1, "rock": 1}


def test_duplicate_genre_within_one_track_counted_once():
    p = analyze_playlist("X", [trk(1)], {"t1": enr(["jazz", "jazz"])})
    assert p.top_genres == [("jazz", 1)]


def test_language_counts():
    tracks = [trk(i) for i in range(5)]
    en = {"t0": enr(language="hindi"), "t1": enr(language="hindi"), "t2": enr(language="tamil"),
          "t3": enr(language=None)}
    p = analyze_playlist("X", tracks, en)
    assert p.languages == {"hindi": 2, "tamil": 1}
    assert p.language_tracks == 3
    assert next(iter(p.languages)) == "hindi"


def test_explicit_ratio_rounded():
    tracks = [trk(1, explicit=True), trk(2), trk(3)]
    assert analyze_playlist("X", tracks, {}).explicit_ratio == 0.333


def test_missing_enrichment_gives_no_genres_or_languages():
    p = analyze_playlist("X", [trk(1), trk(2)], {})
    assert p.top_genres == [] and p.genre_tracks == 0 and p.languages == {}


def test_enrichment_keyed_by_id_only_matches_own_track():
    p = analyze_playlist("X", [trk(1), trk(2)], {"other": enr(["jazz"], "hindi")})
    assert p.genre_tracks == 0 and p.language_tracks == 0


def test_year_percentiles_year_precision():
    tracks = [trk(i, year=str(2000 + i)) for i in range(11)]  # 2000..2010
    p = analyze_playlist("X", tracks, {})
    assert (p.year_p10, p.year_median, p.year_p90) == (2001, 2005, 2009)


def test_year_percentiles_mixed_precisions():
    tracks = [
        trk(1, year="1999", precision="year"),
        trk(2, year="2001-05", precision="month"),
        trk(3, year="2003-07-19", precision="day"),
    ]
    p = analyze_playlist("X", tracks, {})
    assert (p.year_p10, p.year_median, p.year_p90) == (1999, 2001, 2003)


def test_missing_and_bad_dates_ignored():
    tracks = [trk(1, year=None, precision=None), trk(2, year="", precision=None),
              trk(3, year="garbage", precision="year"), trk(4, year="2010", precision="year")]
    p = analyze_playlist("X", tracks, {})
    assert p.year_p10 == p.year_p90 == p.year_median == 2010


def test_all_dates_missing_leaves_years_none():
    p = analyze_playlist("X", [trk(1, year=None, precision=None)], {})
    assert p.year_p10 is None and p.year_p90 is None


def test_single_track_percentiles():
    p = analyze_playlist("X", [trk(1, year="1985")], {})
    assert (p.year_p10, p.year_median, p.year_p90) == (1985, 1985, 1985)


# ------------------------------------------------------------------ dominant_language

def test_dominant_language_at_exact_threshold():
    assert dominant_language(prof(tracks=10, languages={"hindi": 7})) == ("hindi", 0.7)


def test_dominant_language_just_below_threshold():
    assert dominant_language(prof(tracks=100, languages={"hindi": 69})) is None


def test_dominant_language_share_uses_all_tracks_not_tagged():
    # 7 of 7 tagged, but only 7 of 20 tracks overall
    assert dominant_language(prof(tracks=20, languages={"hindi": 7}, language_tracks=7)) is None


def test_dominant_language_empty_cases():
    assert dominant_language(prof(tracks=0, languages={"hindi": 1})) is None
    assert dominant_language(prof(tracks=10, languages={})) is None


# ------------------------------------------------------------------ infer_rule

def test_too_few_tracks_skipped_with_reason():
    rule, reason = infer_rule(prof(tracks=MIN_TRACKS - 1, languages={"hindi": 9}))
    assert rule is None and str(MIN_TRACKS - 1) in reason and "too few" in reason


def test_exactly_min_tracks_allowed():
    rule, _ = infer_rule(prof(tracks=MIN_TRACKS, languages={"hindi": MIN_TRACKS}))
    assert rule is not None


def test_no_pattern_skipped():
    rule, reason = infer_rule(prof(tracks=20))
    assert rule is None and "no distinguishing pattern" in reason


def test_language_signal_alone():
    rule, _ = infer_rule(prof(tracks=20, languages={"tamil": 15}))
    assert rule.match == {"language_in": ["tamil"]}
    assert rule.target == "Mix" and rule.name == "Mix (inferred)"
    assert "75% of tracks are tamil" in rule.rationale


def test_language_below_threshold_gives_no_rule():
    rule, _ = infer_rule(prof(tracks=20, languages={"tamil": 13}))
    assert rule is None


def test_genre_signal_alone_picks_top_two_over_share():
    p = prof(tracks=20, genre_tracks=20, top_genres=[("jazz", 12), ("bebop", 9), ("rock", 8)])
    rule, _ = infer_rule(p)
    assert rule.match == {"genre_contains": ["jazz", "bebop"]}


def test_genre_only_second_below_share_excluded():
    p = prof(tracks=20, genre_tracks=20, top_genres=[("jazz", 12), ("bebop", 7)])
    assert infer_rule(p)[0].match == {"genre_contains": ["jazz"]}


def test_genre_share_boundary_exact_40_percent():
    p = prof(tracks=20, genre_tracks=10, top_genres=[("jazz", 4)])
    assert infer_rule(p)[0].match == {"genre_contains": ["jazz"]}


def test_genre_just_below_share_no_rule():
    p = prof(tracks=20, genre_tracks=10, top_genres=[("jazz", 3)])
    assert infer_rule(p)[0] is None


def test_genre_needs_min_genre_tagged_tracks():
    p = prof(tracks=20, genre_tracks=MIN_TRACKS - 1, top_genres=[("jazz", 9)])
    assert infer_rule(p)[0] is None


def test_artist_group_signal_alone():
    p = prof(tracks=20, top_artists=[("A", 4), ("B", 3), ("C", 1)])  # 7/20 = 35%
    rule, _ = infer_rule(p)
    assert rule.match == {"artist_in": ["A", "B"]}


def test_artist_needs_three_tracks_each():
    p = prof(tracks=10, top_artists=[("A", 2), ("B", 2), ("C", 2)])
    assert infer_rule(p)[0] is None


def test_artist_coverage_below_30_percent_no_rule():
    p = prof(tracks=20, top_artists=[("A", 3), ("B", 2)])  # 3/20 = 15%
    assert infer_rule(p)[0] is None


def test_artist_coverage_boundary_exact():
    tracks = 10
    n = int(tracks * ARTIST_SHARE)  # 3 of 10 = exactly 30%
    rule, _ = infer_rule(prof(tracks=tracks, top_artists=[("A", n)]))
    assert rule.match == {"artist_in": ["A"]}


def test_artist_only_top_three_considered():
    p = prof(tracks=30, top_artists=[("A", 3), ("B", 3), ("C", 3), ("D", 3), ("E", 3)])
    assert infer_rule(p)[0].match["artist_in"] == ["A", "B", "C"]


def test_era_alone_is_not_a_rule():
    rule, reason = infer_rule(prof(tracks=20, year_p10=1995, year_p90=2005, year_median=2000))
    assert rule is None and "no distinguishing pattern" in reason


def test_era_refines_existing_signal_with_offsets():
    rule, _ = infer_rule(prof(tracks=20, languages={"tamil": 15}, year_p10=1995, year_p90=2005))
    assert rule.match == {"language_in": ["tamil"], "release_year_after": 1994, "release_year_before": 2006}
    assert "released 1995-2005" in rule.rationale


def test_era_span_boundary_15_ok_16_not():
    base = dict(tracks=20, languages={"tamil": 15})
    assert "release_year_after" in infer_rule(prof(year_p10=2000, year_p90=2015, **base))[0].match
    assert "release_year_after" not in infer_rule(prof(year_p10=2000, year_p90=2016, **base))[0].match


def test_era_single_year_cluster():
    rule, _ = infer_rule(prof(tracks=20, languages={"tamil": 15}, year_p10=2010, year_p90=2010))
    assert rule.match["release_year_after"] == 2009 and rule.match["release_year_before"] == 2011


def test_explicit_alone_is_not_a_rule():
    rule, reason = infer_rule(prof(tracks=20, explicit_ratio=1.0))
    assert rule is None and "no distinguishing pattern" in reason


def test_explicit_added_with_other_condition():
    rule, _ = infer_rule(prof(tracks=20, languages={"hindi": 18}, explicit_ratio=EXPLICIT_HIGH))
    assert rule.match == {"language_in": ["hindi"], "explicit": True}


def test_explicit_below_90_not_added():
    rule, _ = infer_rule(prof(tracks=20, languages={"hindi": 18}, explicit_ratio=0.89))
    assert "explicit" not in rule.match


def test_combined_signals_and_rationale():
    p = prof(name="Rap", tracks=20, languages={"hindi": 20}, genre_tracks=15,
             top_genres=[("hip hop", 12)], top_artists=[("Kendrick", 6)],
             year_p10=2012, year_p90=2020, explicit_ratio=0.95)
    rule, _ = infer_rule(p)
    assert set(rule.match) == {"language_in", "genre_contains", "artist_in",
                               "release_year_after", "release_year_before", "explicit"}
    assert rule.rationale.startswith('"Rap" inferred from 20 tracks:')
    assert rule.rationale.endswith("Review before enabling.")


# ------------------------------------------------------------------ render_draft

FULL = prof(name="Rap", tracks=20, languages={"hindi": 20}, genre_tracks=15,
            top_genres=[("hip hop", 12)], top_artists=[("Kendrick", 6)],
            year_p10=2012, year_p90=2020, explicit_ratio=0.95)
HINDI = prof(name="Chill Hindi", tracks=30, languages={"hindi": 27})
EMPTY_PATTERN = prof(name="Random", tracks=20)
SMALL = prof(name="Tiny", tracks=4, languages={"hindi": 4})

AWKWARD_NAMES = [
    'He said "hi"',
    "Back\\slash",
    "Rock: the 'best' of",
    "# not a comment",
    "Ünïcödé 音楽 🎵 മലയാളം हिन्दी",
    "  leading and trailing  ",
    "x" * 300,
    "line1\nline2",
    "tab\tsep\r\nCRLF",
    "- dash start",
    "[bracket] {brace}, comma",
    "null",
    "123",
    "true",
]


def _make(name):
    return prof(name=name, tracks=20, languages={"hindi": 18})


def test_render_parses_and_validates_basic():
    text = render_draft([FULL, HINDI, EMPTY_PATTERN, SMALL], skipped_followed=3, unreadable=["Locked"])
    data, cfg = roundtrip(text)
    assert [r.name for r in cfg.rules] == ["Rap (inferred)", "Chill Hindi (inferred)"]
    assert cfg.default_days_threshold == 14 and cfg.fallback_playlist is None


def test_every_rule_disabled():
    _, cfg = roundtrip(render_draft([FULL, HINDI, _make("Another")]))
    assert len(cfg.rules) == 3 and all(r.enabled is False for r in cfg.rules)


@pytest.mark.parametrize("name", AWKWARD_NAMES)
def test_awkward_playlist_names_roundtrip(name):
    data, cfg = roundtrip(render_draft([_make(name)]))
    rule = cfg.rules[0]
    assert rule.name == f"{name} (inferred)"
    assert rule.target_playlist == name
    assert cfg.language_playlists == ({name: "hindi"} if len(name) <= 200 else {})
    assert rule.enabled is False


@pytest.mark.parametrize("name", ["a b", "ab", "a b"])
def test_unicode_line_separator_names_roundtrip(name):
    _, cfg = roundtrip(render_draft([_make(name)]))
    assert cfg.rules[0].target_playlist == name


def test_very_long_name_skips_language_suggestion_but_keeps_valid_draft():
    # PyYAML rejects implicit keys > 1024 chars, so names > 200 chars get no language_playlists suggestion
    _, cfg = roundtrip(render_draft([_make("y" * 1500)]))
    assert cfg.language_playlists == {}
    assert cfg.rules[0].target_playlist == "y" * 1500


def test_awkward_names_in_unreadable_and_skipped_are_comments_only():
    text = render_draft([EMPTY_PATTERN.__class__(name="bad\nname: x", tracks=20)],
                        unreadable=['q"uote\nnew'])
    data, cfg = roundtrip(text)
    assert cfg.rules == ()
    for line in text.splitlines():
        if "bad" in line or "uote" in line:
            assert line.lstrip().startswith("#")


def test_language_playlists_only_for_dominant_and_min_tracks():
    data, cfg = roundtrip(render_draft([HINDI, SMALL, EMPTY_PATTERN, prof(name="Half", tracks=20, languages={"tamil": 10})]))
    assert cfg.language_playlists == {"Chill Hindi": "hindi"}


def test_english_is_never_suggested_nor_a_rule_on_its_own():
    text = render_draft([prof(name="Pop", tracks=20, languages={"english": 20})])
    data, cfg = roundtrip(text)
    assert data["language_playlists"] == {}
    assert cfg.rules == ()


def test_duplicate_playlist_names_give_one_language_suggestion():
    _, cfg = roundtrip(render_draft([HINDI, prof(name=HINDI.name.upper(), tracks=20, languages={"hindi": 20})]))
    assert list(cfg.language_playlists.values()) == ["hindi"] and len(cfg.language_playlists) == 1


def test_no_language_suggestions_gives_empty_mapping():
    text = render_draft([EMPTY_PATTERN])
    assert yaml.safe_load(text)["language_playlists"] == {}


def test_duplicate_names_case_insensitive_single_rule():
    text = render_draft([_make("Chill"), _make("chill"), _make("CHILL")])
    _, cfg = roundtrip(text)
    assert len(cfg.rules) == 1
    assert text.count("duplicate playlist name") == 2


def test_duplicate_name_still_valid_with_other_rules():
    _, cfg = roundtrip(render_draft([_make("A"), _make("a"), _make("B")]))
    assert [r.name for r in cfg.rules] == ["A (inferred)", "B (inferred)"]


def test_zero_rules_renders_empty_list_and_is_valid():
    text = render_draft([EMPTY_PATTERN, SMALL])
    data, cfg = roundtrip(text)
    assert data["rules"] == [] and "rules: []" in text and cfg.rules == ()


def test_no_profiles_at_all_is_valid():
    text = render_draft([])
    data, cfg = roundtrip(text)
    assert data["rules"] == [] and "Analysed 0 owned" in text


def test_rationale_comments_single_line():
    text = render_draft([_make("multi\nline\r\nname x")])
    lines = text.splitlines()
    idx = [i for i, l in enumerate(lines) if "inferred from" in l]
    assert len(idx) == 1 and lines[idx[0]].lstrip().startswith("# ")
    assert lines[idx[0] + 1].lstrip().startswith("- name:")


def test_skipped_playlists_listed_in_trailing_comments():
    text = render_draft([HINDI, EMPTY_PATTERN, SMALL], unreadable=["Locked"])
    tail = text[text.index("# ---- playlists without a drafted rule ----"):]
    assert '# skipped "Random": no distinguishing pattern' in tail
    assert '# skipped "Tiny": only 4 tracks' in tail
    assert '# unreadable (skipped): "Locked"' in tail
    assert all(l.startswith("#") for l in tail.splitlines())


def test_no_trailing_block_when_nothing_skipped():
    assert "playlists without a drafted rule" not in render_draft([HINDI])


def test_followed_count_header():
    text = render_draft([HINDI, FULL], skipped_followed=5)
    assert "# Analysed 2 owned/collaborative playlists; 5 followed playlists were skipped" in text


def test_output_ends_with_single_newline():
    text = render_draft([HINDI, EMPTY_PATTERN])
    assert text.endswith("\n") and not text.endswith("\n\n")


def test_rule_match_lists_rendered_as_yaml_lists():
    data, _ = roundtrip(render_draft([FULL]))
    m = data["rules"][0]["match"]
    assert m["genre_contains"] == ["hip hop"] and m["artist_in"] == ["Kendrick"]
    assert m["release_year_after"] == 2011 and m["release_year_before"] == 2021
    assert m["explicit"] is True and m["language_in"] == ["hindi"]


@pytest.mark.parametrize("prof_kw", [
    dict(languages={"malayalam": 19}),
    dict(genre_tracks=20, top_genres=[("k-pop", 15), ("dance: pop", 9)]),
    dict(top_artists=[("AC/DC", 9), ('The "Who"', 4)]),
    dict(languages={"hindi": 15}, year_p10=1970, year_p90=1980, explicit_ratio=0.0),
])
def test_varied_profiles_validate(prof_kw):
    _, cfg = roundtrip(render_draft([prof(name="P", tracks=20, **prof_kw)]))
    assert len(cfg.rules) == 1


# ------------------------------------------------------------------ end to end

MAL = "മലയാളം"  # Malayalam script


class FakeClient:
    instances: list = []
    read_ids: list = []
    dry_run = None

    def __init__(self, dry_run):
        self.dry_run = dry_run
        FakeClient.instances.append(self)

    @classmethod
    def from_env(cls, dry_run=True, **kw):
        return cls(dry_run)

    def iter_my_playlists(self):
        return iter([
            Playlist("mal", "Malayalam Mix", "me", True, False),
            Playlist("blank", "Blank Mix", "me", True, False),
            Playlist("followed", "Someone's Playlist", "other", False, False),
            Playlist("collab", "Collab Rock", "other", False, True),
            Playlist("test", "SpotiSort Test", "me", True, False),
            Playlist("locked", "Locked Away", "me", True, False),
        ])

    def iter_playlist_items(self, pid):
        FakeClient.read_ids.append(pid)
        if pid == "locked":
            raise SpotifyError("forbidden", status=403)
        if pid == "mal":
            return iter([trk(i, artist=f"Artist {i % 2}", year=str(2000 + i), name=f"{MAL} {i}",
                             album_name=MAL) for i in range(12)])
        return iter([trk(100 + i, artist=f"Z{i}", year=str(1950 + 5 * i)) for i in range(11)])


@pytest.fixture
def fake(monkeypatch):
    FakeClient.instances, FakeClient.read_ids = [], []
    monkeypatch.setattr(analyze, "SpotifyClient", FakeClient)
    monkeypatch.setattr(analyze, "load_env", lambda *a, **k: False)
    return FakeClient


def _argv(tmp_path, *extra):
    return ["--no-network", "--cache", str(tmp_path / "cache.json"), "--output", str(tmp_path / "draft.yaml"),
            "--config", str(tmp_path / "missing.yaml"), "--env", str(tmp_path / "missing.env"), *extra]


def test_main_end_to_end(fake, tmp_path, capsys):
    assert analyze.main(_argv(tmp_path)) == 0
    assert len(fake.instances) == 1 and fake.instances[0].dry_run is True
    assert "followed" not in fake.read_ids
    assert "test" not in fake.read_ids
    assert sorted(fake.read_ids) == ["blank", "collab", "locked", "mal"]

    text = (tmp_path / "draft.yaml").read_text(encoding="utf-8")
    data, cfg = roundtrip(text)
    assert "Analysed 3 owned/collaborative playlists; 1 followed playlists were skipped" in text
    assert '# unreadable (skipped): "Locked Away"' in text
    assert "SpotiSort Test" not in text
    assert all(r.enabled is False for r in cfg.rules)
    assert cfg.language_playlists == {"Malayalam Mix": "malayalam"}
    names = [r.name for r in cfg.rules]
    assert "Malayalam Mix (inferred)" in names
    out = capsys.readouterr().out
    assert "3 playlists analysed, 1 followed skipped, 1 unreadable" in out


def test_main_non_403_error_returns_1(fake, tmp_path, monkeypatch):
    def boom(self, pid):
        raise SpotifyError("server exploded", status=500)
    monkeypatch.setattr(FakeClient, "iter_playlist_items", boom)
    assert analyze.main(_argv(tmp_path)) == 1
    assert not (tmp_path / "draft.yaml").exists()


def test_main_invalid_config_returns_1(fake, tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("rules: 5\n", encoding="utf-8")
    argv = _argv(tmp_path)
    argv[argv.index("--config") + 1] = str(bad)
    assert analyze.main(argv) == 1
    assert fake.instances == []
