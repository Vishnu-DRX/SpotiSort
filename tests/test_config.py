"""Unit tests for src/config.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config import ConfigError, load_config, parse_config
from src.models import Config, Rule

REPO_ROOT = Path(__file__).resolve().parent.parent


def mk_rule(**over):
    r = {"name": "R", "target_playlist": "P", "match": {"explicit": True}}
    r.update(over)
    return r


def errors_of(data) -> list[str]:
    with pytest.raises(ConfigError) as ei:
        parse_config(data)
    return ei.value.errors


def joined(data) -> str:
    return "\n".join(errors_of(data))


# ------------------------------------------------------------- valid / defaults

def test_example_config_loads():
    cfg = load_config(REPO_ROOT / "config.example.yaml")
    assert cfg.default_days_threshold == 14
    assert cfg.fallback_playlist is None
    by_name = {r.name: r for r in cfg.rules}
    assert len(by_name) == len(cfg.rules) >= 4
    jazz = by_name["Jazz to Jazz Vault"]
    chill = by_name["Favorite chill artists"]
    hip = by_name["Old hip-hop"]
    expl = by_name["Explicit filter example"]
    assert jazz.match == {"genre_contains": ["jazz"]}
    assert jazz.days_threshold == 7 and jazz.target_playlist == "Jazz Vault"
    assert chill.match == {"artist_in": ["Bonobo", "Tycho"]} and chill.days_threshold is None
    assert hip.match == {"genre_contains": ["hip hop", "rap"], "release_year_before": 2010}
    assert expl.match == {"explicit": False, "track_name_contains": "acoustic"}
    assert expl.create_missing_playlists is False


def test_full_config_parses_to_expected_config():
    data = {
        "default_days_threshold": 30,
        "fallback_playlist": "Misc",
        "rules": [
            {
                "name": "All keys",
                "enabled": False,
                "target_playlist": "Dest",
                "days_threshold": 0,
                "create_missing_playlists": True,
                "match": {
                    "artist_in": ["A"],
                    "genre_contains": ["g"],
                    "language_in": ["hindi"],
                    "release_year_before": 2010,
                    "release_year_after": 1990,
                    "explicit": True,
                    "track_name_contains": "t",
                    "album_name_contains": "a",
                },
            }
        ],
    }
    assert parse_config(data) == Config(
        default_days_threshold=30,
        fallback_playlist="Misc",
        rules=(
            Rule(
                name="All keys",
                target_playlist="Dest",
                enabled=False,
                days_threshold=0,
                create_missing_playlists=True,
                match=data["rules"][0]["match"],
            ),
        ),
    )


def test_defaults_for_empty_mapping():
    assert parse_config({}) == Config(14, None, ())


def test_none_document_gives_defaults():
    assert parse_config(None) == Config(14, None, ())


def test_rule_defaults():
    rule = parse_config({"rules": [mk_rule()]}).rules[0]
    assert rule.enabled is True
    assert rule.days_threshold is None
    assert rule.create_missing_playlists is False


def test_language_in_accepted():
    cfg = parse_config({"rules": [mk_rule(match={"language_in": ["hindi", "tamil"]})]})
    assert cfg.rules[0].match == {"language_in": ["hindi", "tamil"]}


def test_rules_returned_as_tuple_in_order():
    cfg = parse_config({"rules": [mk_rule(name="a"), mk_rule(name="b")]})
    assert isinstance(cfg.rules, tuple) and [r.name for r in cfg.rules] == ["a", "b"]


def test_fallback_playlist_accepts_string_and_none():
    assert parse_config({"fallback_playlist": "X"}).fallback_playlist == "X"
    assert parse_config({"fallback_playlist": None}).fallback_playlist is None


@pytest.mark.parametrize("value", [5, True, ["x"], ""])
def test_fallback_playlist_rejects_bad_types(value):
    assert "fallback_playlist" in joined({"fallback_playlist": value})


def test_rules_none_is_rejected_as_non_list():
    assert "'rules' must be a list" in joined({"rules": None})


def test_rules_not_a_list_rejected():
    assert "'rules' must be a list" in joined({"rules": {"a": 1}})


def test_release_year_boundaries_accepted():
    cfg = parse_config({"rules": [mk_rule(match={"release_year_before": 9999, "release_year_after": 1})]})
    assert cfg.rules[0].match == {"release_year_before": 9999, "release_year_after": 1}


# -------------------------------------------------------------------- loading

def test_load_config_from_tmp_file(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("default_days_threshold: 3\nrules:\n  - name: x\n    target_playlist: y\n"
                 "    match:\n      explicit: true\n", encoding="utf-8")
    cfg = load_config(p)
    assert cfg.default_days_threshold == 3 and cfg.rules[0].name == "x"


def test_load_config_accepts_str_path(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("default_days_threshold: 1\n", encoding="utf-8")
    assert load_config(str(p)).default_days_threshold == 1


def test_load_config_missing_file(tmp_path):
    with pytest.raises(ConfigError) as ei:
        load_config(tmp_path / "nope.yaml")
    assert "cannot read" in ei.value.errors[0]


def test_load_config_invalid_yaml(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("rules: [unclosed\n  - : :", encoding="utf-8")
    with pytest.raises(ConfigError) as ei:
        load_config(p)
    assert "not valid YAML" in ei.value.errors[0]


def test_load_config_empty_file_gives_defaults(tmp_path):
    p = tmp_path / "e.yaml"
    p.write_text("", encoding="utf-8")
    assert load_config(p) == Config()


def test_load_config_directory_is_config_error(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path)


def test_config_error_is_value_error_and_message_lists_errors():
    err = ConfigError(["one", "two"])
    assert isinstance(err, ValueError)
    assert "one" in str(err) and "two" in str(err) and err.errors == ["one", "two"]


# ------------------------------------------------------------ top-level errors

@pytest.mark.parametrize("doc", [[], "text", 5, [{"rules": []}]])
def test_top_level_not_mapping(doc):
    assert errors_of(doc) == ["top level must be a mapping"]


def test_unknown_top_level_key():
    assert "unknown top-level key 'bogus'" in joined({"bogus": 1})


@pytest.mark.parametrize("value", [-1, "14", True, 1.5, None])
def test_default_days_threshold_invalid(value):
    assert "default_days_threshold" in joined({"default_days_threshold": value})


def test_default_days_threshold_zero_ok():
    assert parse_config({"default_days_threshold": 0}).default_days_threshold == 0


# ----------------------------------------------------------------- rule errors

def test_rule_not_a_mapping():
    assert "rules[0]: must be a mapping" in joined({"rules": ["nope"]})


def test_unknown_rule_key_names_rule_index_and_name():
    msg = joined({"rules": [mk_rule(), mk_rule(name="Second", colour="red")]})
    assert "rules[1] ('Second')" in msg and "unknown key 'colour'" in msg


def test_unknown_match_key_names_rule():
    msg = joined({"rules": [mk_rule(name="Pop", match={"popularity_above": 50})]})
    assert "rules[0] ('Pop')" in msg and "unknown match key 'popularity_above'" in msg


def test_missing_name():
    r = mk_rule()
    del r["name"]
    msg = joined({"rules": [r]})
    assert "rules[0]" in msg and "'name' is required" in msg


@pytest.mark.parametrize("name", ["", "   ", 5, None])
def test_invalid_name(name):
    assert "'name' is required" in joined({"rules": [mk_rule(name=name)]})


def test_missing_target_playlist():
    r = mk_rule()
    del r["target_playlist"]
    msg = joined({"rules": [r]})
    assert "rules[0] ('R')" in msg and "'target_playlist' is required" in msg


@pytest.mark.parametrize("target", ["", "  ", 3, None, ["x"]])
def test_invalid_target_playlist(target):
    assert "'target_playlist'" in joined({"rules": [mk_rule(target_playlist=target)]})


@pytest.mark.parametrize("value", ["yes", 1, 0, None])
def test_enabled_must_be_bool(value):
    assert "'enabled' must be true or false" in joined({"rules": [mk_rule(enabled=value)]})


@pytest.mark.parametrize("value", ["yes", 1, None])
def test_create_missing_playlists_must_be_bool(value):
    assert "'create_missing_playlists'" in joined({"rules": [mk_rule(create_missing_playlists=value)]})


def test_create_missing_playlists_true_accepted():
    assert parse_config({"rules": [mk_rule(create_missing_playlists=True)]}).rules[0].create_missing_playlists


@pytest.mark.parametrize("value", [-1, True, False, "7", 2.5, [1]])
def test_rule_days_threshold_invalid(value):
    assert "'days_threshold' must be an integer >= 0" in joined({"rules": [mk_rule(days_threshold=value)]})


def test_rule_days_threshold_zero_accepted():
    assert parse_config({"rules": [mk_rule(days_threshold=0)]}).rules[0].days_threshold == 0


# ---------------------------------------------------------------- match errors

@pytest.mark.parametrize("match", [None, {}, [], "explicit", ["explicit"]])
def test_match_must_be_non_empty_mapping(match):
    assert "'match' must be a non-empty mapping" in joined({"rules": [mk_rule(match=match)]})


def test_match_missing():
    r = mk_rule()
    del r["match"]
    assert "'match' must be a non-empty mapping" in joined({"rules": [r]})


@pytest.mark.parametrize("key", ["release_year_before", "release_year_after"])
@pytest.mark.parametrize("value", ["2010", True, False, 0, 10000, -5, 2010.5, None])
def test_release_year_invalid(key, value):
    assert f"'{key}' must be a year" in joined({"rules": [mk_rule(match={key: value})]})


@pytest.mark.parametrize("value", ["true", "false", 1, 0, None, []])
def test_explicit_must_be_bool(value):
    assert "'explicit' must be true or false" in joined({"rules": [mk_rule(match={"explicit": value})]})


@pytest.mark.parametrize("key", ["artist_in", "genre_contains", "language_in"])
@pytest.mark.parametrize("value", ["jazz", [], [1], ["ok", 2], [""], ["  "], [None], None, {"a": 1}])
def test_list_keys_invalid(key, value):
    assert f"'{key}' must be a non-empty list" in joined({"rules": [mk_rule(match={key: value})]})


@pytest.mark.parametrize("key", ["track_name_contains", "album_name_contains"])
@pytest.mark.parametrize("value", ["", "   ", 5, None, ["x"]])
def test_str_keys_invalid(key, value):
    assert f"'{key}' must be a non-empty string" in joined({"rules": [mk_rule(match={key: value})]})


# ------------------------------------------------------------- multi / dupes

def test_duplicate_rule_names_case_insensitive():
    msg = joined({"rules": [mk_rule(name="Jazz"), mk_rule(name="jAZZ")]})
    assert "rules[1] ('jAZZ'): duplicate rule name" in msg


def test_distinct_names_not_duplicates():
    assert len(parse_config({"rules": [mk_rule(name="a"), mk_rule(name="b")]}).rules) == 2


def test_multiple_errors_all_reported():
    data = {
        "bogus": 1,
        "default_days_threshold": -1,
        "fallback_playlist": 5,
        "rules": [
            mk_rule(name="A", enabled="x"),
            mk_rule(name="B", days_threshold=True, match={"release_year_before": "x"}),
            {"match": {}},
            "not a rule",
        ],
    }
    errs = errors_of(data)
    text = "\n".join(errs)
    for needle in ["unknown top-level key 'bogus'", "default_days_threshold", "fallback_playlist",
                   "rules[0] ('A')", "rules[1] ('B')", "rules[2]", "rules[3]: must be a mapping"]:
        assert needle in text
    assert len(errs) >= 8


def test_multiple_errors_in_single_rule_all_reported():
    errs = errors_of({"rules": [{"name": "X", "colour": 1, "enabled": "no", "match": {"zzz": 1, "explicit": "y"}}]})
    text = "\n".join(errs)
    assert "unknown key 'colour'" in text
    assert "'target_playlist' is required" in text
    assert "'enabled'" in text
    assert "unknown match key 'zzz'" in text
    assert "'explicit'" in text


def test_config_error_message_contains_every_error():
    with pytest.raises(ConfigError) as ei:
        parse_config({"a": 1, "b": 2})
    for e in ei.value.errors:
        assert e in str(ei.value)


# ---- Phase 2 schema additions: language_playlists, enrichment, language normalisation

def _cfg(**extra):
    from src.config import parse_config

    return parse_config(extra)


def test_language_playlists_normalised():
    c = _cfg(language_playlists={"Chill Hindi": "hi", "Mallu": "Malayalam", "K": "kor"})
    assert c.language_playlists == {"Chill Hindi": "hindi", "Mallu": "malayalam", "K": "korean"}


def test_language_playlists_unknown_language_rejected():
    import pytest
    from src.config import ConfigError

    with pytest.raises(ConfigError, match="unknown language"):
        _cfg(language_playlists={"X": "klingon"})


def test_language_playlists_must_be_mapping():
    import pytest
    from src.config import ConfigError

    with pytest.raises(ConfigError):
        _cfg(language_playlists=["a"])


def test_enrichment_musicbrainz_flag():
    assert _cfg().musicbrainz is True
    assert _cfg(enrichment={"musicbrainz": False}).musicbrainz is False


def test_enrichment_rejects_unknown_key_and_bad_type():
    import pytest
    from src.config import ConfigError

    with pytest.raises(ConfigError):
        _cfg(enrichment={"lastfm": True})
    with pytest.raises(ConfigError):
        _cfg(enrichment={"musicbrainz": "yes"})


def test_language_in_is_normalised_through_alias_table():
    c = _cfg(rules=[{"name": "r", "target_playlist": "p", "match": {"language_in": ["hi", "MAL", "தமிழ்"]}}])
    assert c.rules[0].match["language_in"] == ["hindi", "malayalam", "tamil"]


def test_language_in_unknown_language_rejected():
    import pytest
    from src.config import ConfigError

    with pytest.raises(ConfigError, match="unknown language"):
        _cfg(rules=[{"name": "r", "target_playlist": "p", "match": {"language_in": ["elvish"]}}])
