"""Unit tests for src/rules_engine.py using fabricated data (no I/O, no network)."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest

from src.models import Artist, Enrichment, Match, Rule, Track
from src.rules_engine import (
    DEFAULT_DAYS_THRESHOLD,
    age_days,
    evaluate,
    release_year,
    resolve_days_threshold,
)

NOW = datetime(2026, 9, 21, tzinfo=timezone.utc)


def days_ago(n: float) -> datetime:
    return NOW - timedelta(days=n)


def make_track(**kw) -> Track:
    base = dict(
        id="t1",
        uri="spotify:track:t1",
        name="Some Song",
        artists=(Artist("a1", "Bonobo"),),
        album_name="Some Album",
        release_date="2005-06-01",
        release_date_precision="day",
        explicit=False,
        added_at=days_ago(30),
    )
    base.update(kw)
    return Track(**base)


def rule(match, name="r", target="P", **kw) -> Rule:
    return Rule(name=name, target_playlist=target, match=match, **kw)


def run(track, rules, enrichment=None, default=14):
    return evaluate(track, enrichment, rules, NOW, default)


# ---------------------------------------------------------------- artist_in

def test_artist_in_matches_exact_name():
    assert run(make_track(), [rule({"artist_in": ["Bonobo"]})]) is not None


@pytest.mark.parametrize("wanted", ["bonobo", "BONOBO", "  Bonobo  "])
def test_artist_in_case_and_whitespace_insensitive(wanted):
    assert run(make_track(), [rule({"artist_in": [wanted]})]) is not None


def test_artist_in_matches_second_credited_artist():
    t = make_track(artists=(Artist("a1", "Someone"), Artist("a2", "Tycho")))
    m = run(t, [rule({"artist_in": ["Tycho"]})])
    assert m is not None and m.matched["artist_in"] == "Tycho"


@pytest.mark.parametrize("wanted", ["Bono", "Bonobo Band", "onobo"])
def test_artist_in_no_substring_matching(wanted):
    assert run(make_track(), [rule({"artist_in": [wanted]})]) is None


def test_artist_in_no_artists_on_track():
    assert run(make_track(artists=()), [rule({"artist_in": ["Bonobo"]})]) is None


def test_artist_in_reports_first_hit_in_wanted_order():
    m = run(make_track(), [rule({"artist_in": ["Nobody", "bonobo"]})])
    assert m.matched["artist_in"] == "bonobo"


# ------------------------------------------------------------ genre_contains

def test_genre_contains_substring():
    e = Enrichment(genres=("acid jazz",))
    m = run(make_track(), [rule({"genre_contains": ["jazz"]})], e)
    assert m is not None and m.matched["genre_contains"] == "jazz"


def test_genre_contains_case_insensitive():
    e = Enrichment(genres=("Nu Jazz",))
    assert run(make_track(), [rule({"genre_contains": ["JAZZ"]})], e) is not None


def test_genre_contains_matches_any_of_multiple_genres():
    e = Enrichment(genres=("rock", "trip hop", "electronic"))
    assert run(make_track(), [rule({"genre_contains": ["hip hop", "trip"]})], e) is not None


def test_genre_contains_no_hit():
    e = Enrichment(genres=("rock",))
    assert run(make_track(), [rule({"genre_contains": ["jazz"]})], e) is None


def test_genre_contains_empty_genres():
    assert run(make_track(), [rule({"genre_contains": ["jazz"]})], Enrichment()) is None


def test_genre_contains_none_enrichment():
    assert run(make_track(), [rule({"genre_contains": ["jazz"]})], None) is None


def test_genre_contains_blank_wanted_never_matches():
    e = Enrichment(genres=("jazz",))
    assert run(make_track(), [rule({"genre_contains": ["  "]})], e) is None


# ---------------------------------------------------------------- language_in

@pytest.mark.parametrize("lang,wanted", [("hindi", "Hindi"), ("Malayalam", "malayalam"), ("ta", " TA ")])
def test_language_in_case_insensitive(lang, wanted):
    e = Enrichment(language=lang)
    m = run(make_track(), [rule({"language_in": [wanted]})], e)
    assert m is not None and m.matched["language_in"] == lang


def test_language_in_none_language():
    assert run(make_track(), [rule({"language_in": ["hindi"]})], Enrichment(language=None)) is None


def test_language_in_none_enrichment():
    assert run(make_track(), [rule({"language_in": ["hindi"]})], None) is None


def test_language_in_not_in_list():
    assert run(make_track(), [rule({"language_in": ["hindi", "tamil"]})], Enrichment(language="english")) is None


# ------------------------------------------------- release_year_before / after

def test_release_year_before_strict_boundary_equal_fails():
    t = make_track(release_date="2010-01-01")
    assert run(t, [rule({"release_year_before": 2010})]) is None


def test_release_year_before_one_below_passes():
    t = make_track(release_date="2009-12-31")
    m = run(t, [rule({"release_year_before": 2010})])
    assert m is not None and m.matched["release_year_before"] == 2009


def test_release_year_after_strict_boundary_equal_fails():
    t = make_track(release_date="2010-01-01")
    assert run(t, [rule({"release_year_after": 2010})]) is None


def test_release_year_after_one_above_passes():
    t = make_track(release_date="2011-01-01")
    m = run(t, [rule({"release_year_after": 2010})])
    assert m is not None and m.matched["release_year_after"] == 2011


@pytest.mark.parametrize("key", ["release_year_before", "release_year_after"])
def test_release_year_keys_fail_when_date_missing(key):
    t = make_track(release_date=None, release_date_precision=None)
    assert run(t, [rule({key: 2000})]) is None


def test_release_year_before_and_after_together_as_range():
    r = rule({"release_year_after": 1999, "release_year_before": 2010})
    assert run(make_track(release_date="2005", release_date_precision="year"), [r]) is not None
    assert run(make_track(release_date="1999", release_date_precision="year"), [r]) is None
    assert run(make_track(release_date="2010", release_date_precision="year"), [r]) is None


# ------------------------------------------------------------ release_year()

@pytest.mark.parametrize(
    "date,precision,expected",
    [
        ("2005", "year", 2005),
        ("2005-06", "month", 2005),
        ("2005-06-15", "day", 2005),
        ("2005-06-15", "year", 2005),
        ("2005-06-15", "month", 2005),
        ("2005-06", None, 2005),
        ("2005", None, 2005),
        (" 2005-06-15 ", "day", 2005),
        (None, "day", None),
        ("", "day", None),
        ("abc", "year", None),
        ("05-06-15", "day", None),
        ("2005/06/15", "day", None),
        ("20050615", "day", None),
        ("2005-6-1", "day", None),
        ("2005-06-15T00:00", "day", None),
        ("2005", "month", None),  # shorter than declared precision
        ("2005", "day", None),
        ("2005-06", "day", None),
    ],
)
def test_release_year_helper(date, precision, expected):
    assert release_year(date, precision) == expected


def test_release_year_unknown_precision_treated_as_year():
    assert release_year("2005", "century") == 2005


# ------------------------------------------------------------------ explicit

def test_explicit_true_matches_explicit_track():
    assert run(make_track(explicit=True), [rule({"explicit": True})]) is not None


def test_explicit_true_rejects_clean_track():
    assert run(make_track(explicit=False), [rule({"explicit": True})]) is None


def test_explicit_false_matches_clean_track():
    m = run(make_track(explicit=False), [rule({"explicit": False})])
    assert m is not None and m.matched["explicit"] is False


def test_explicit_false_rejects_explicit_track():
    assert run(make_track(explicit=True), [rule({"explicit": False})]) is None


# ------------------------------------------- track_name / album_name contains

@pytest.mark.parametrize("wanted", ["acoustic", "ACOUSTIC", "Acou"])
def test_track_name_contains_case_insensitive_substring(wanted):
    t = make_track(name="My Acoustic Version")
    assert run(t, [rule({"track_name_contains": wanted})]) is not None


def test_track_name_contains_no_hit():
    assert run(make_track(name="Loud"), [rule({"track_name_contains": "quiet"})]) is None


@pytest.mark.parametrize("wanted", ["deluxe", "DELUXE", "lux"])
def test_album_name_contains_case_insensitive_substring(wanted):
    t = make_track(album_name="Greatest Hits (Deluxe)")
    assert run(t, [rule({"album_name_contains": wanted})]) is not None


def test_album_name_contains_empty_album():
    assert run(make_track(album_name=""), [rule({"album_name_contains": "hits"})]) is None


def test_name_contains_blank_wanted_never_matches():
    assert run(make_track(), [rule({"track_name_contains": "  "})]) is None
    assert run(make_track(), [rule({"album_name_contains": ""})]) is None


def test_unknown_match_key_never_matches():
    assert run(make_track(), [rule({"popularity_above": 50})]) is None


# ------------------------------------------------------------ AND-combination

def test_and_all_keys_pass():
    t = make_track(explicit=True, name="Night Drive")
    e = Enrichment(genres=("jazz",), language="english")
    r = rule({"artist_in": ["Bonobo"], "genre_contains": ["jazz"], "explicit": True,
              "track_name_contains": "drive", "language_in": ["english"]})
    m = run(t, [r], e)
    assert m is not None and set(m.matched) == set(r.match)


@pytest.mark.parametrize(
    "bad",
    [
        {"artist_in": ["Nobody"]},
        {"genre_contains": ["metal"]},
        {"explicit": True},
        {"release_year_before": 1990},
        {"language_in": ["french"]},
    ],
)
def test_and_one_failing_key_fails_rule(bad):
    good = {"artist_in": ["Bonobo"], "genre_contains": ["jazz"], "explicit": False,
            "release_year_before": 2010, "language_in": ["english"]}
    combined = {**good, **bad}
    e = Enrichment(genres=("jazz",), language="english")
    assert run(make_track(), [rule(good)], e) is not None
    assert run(make_track(), [rule(combined)], e) is None


# ------------------------------------------------------------------ precedence

def test_first_match_wins():
    r1 = rule({"artist_in": ["Bonobo"]}, name="first", target="A")
    r2 = rule({"artist_in": ["Bonobo"]}, name="second", target="B")
    assert run(make_track(), [r1, r2]).rule.name == "first"


def test_rule_order_matters():
    r1 = rule({"artist_in": ["Bonobo"]}, name="first")
    r2 = rule({"explicit": False}, name="second")
    assert run(make_track(), [r1, r2]).rule.name == "first"
    assert run(make_track(), [r2, r1]).rule.name == "second"


def test_disabled_rule_is_skipped():
    r1 = rule({"artist_in": ["Bonobo"]}, name="off", enabled=False)
    r2 = rule({"artist_in": ["Bonobo"]}, name="on")
    assert run(make_track(), [r1, r2]).rule.name == "on"


def test_only_disabled_rules_gives_none():
    assert run(make_track(), [rule({"artist_in": ["Bonobo"]}, enabled=False)]) is None


def test_no_rules_returns_none():
    assert run(make_track(), []) is None


def test_empty_match_rule_is_skipped_not_match_all():
    r1 = rule({}, name="empty")
    assert run(make_track(), [r1]) is None
    r2 = rule({"explicit": False}, name="real")
    assert run(make_track(), [r1, r2]).rule.name == "real"


def test_non_matching_earlier_rule_falls_to_later():
    r1 = rule({"artist_in": ["Nobody"]}, name="no")
    r2 = rule({"artist_in": ["Bonobo"]}, name="yes")
    assert run(make_track(), [r1, r2]).rule.name == "yes"


# --------------------------------------------------------- days threshold / age

def test_default_threshold_constant_is_14():
    assert DEFAULT_DAYS_THRESHOLD == 14


def test_default_threshold_used_when_rule_has_none():
    r = rule({"explicit": False})
    assert run(make_track(added_at=days_ago(13.9)), [r]) is None
    assert run(make_track(added_at=days_ago(14.1)), [r]) is not None


def test_default_threshold_argument_is_configurable():
    r = rule({"explicit": False})
    t = make_track(added_at=days_ago(5))
    assert run(t, [r], default=3) is not None
    assert run(t, [r], default=10) is None


def test_default_threshold_falls_back_to_module_default():
    r = rule({"explicit": False})
    assert evaluate(make_track(added_at=days_ago(10)), None, [r], NOW) is None
    assert evaluate(make_track(added_at=days_ago(15)), None, [r], NOW) is not None


def test_rule_threshold_lower_lets_younger_track_match():
    r = rule({"explicit": False}, days_threshold=3)
    assert run(make_track(added_at=days_ago(5)), [r]) is not None


def test_rule_threshold_higher_blocks_track():
    r = rule({"explicit": False}, days_threshold=60)
    assert run(make_track(added_at=days_ago(30)), [r]) is None


def test_age_exactly_equal_to_threshold_matches():
    r = rule({"explicit": False}, days_threshold=14)
    m = run(make_track(added_at=days_ago(14)), [r])
    assert m is not None and m.age_days == 14


def test_zero_threshold_matches_brand_new_track():
    r = rule({"explicit": False}, days_threshold=0)
    assert run(make_track(added_at=NOW), [r]) is not None


def test_added_at_none_never_matches():
    r = rule({"explicit": False}, days_threshold=0)
    assert run(make_track(added_at=None), [r]) is None


def test_too_young_match_blocks_later_rules_no_fall_through():
    r1 = rule({"explicit": False}, name="slow", days_threshold=30)
    r2 = rule({"explicit": False}, name="fast", days_threshold=7)
    assert run(make_track(added_at=days_ago(10)), [r1, r2]) is None


def test_first_match_reports_too_young_match_with_threshold():
    from src.rules_engine import first_match

    r1 = rule({"explicit": False}, name="slow", days_threshold=30)
    m = first_match(make_track(added_at=days_ago(10)), None, [r1], NOW)
    assert m.rule.name == "slow" and m.aged is False and m.threshold == 30


def test_first_match_none_when_no_conditions_match():
    from src.rules_engine import first_match

    assert first_match(make_track(added_at=days_ago(10)), None, [rule({"explicit": True})], NOW) is None


def test_age_days_helper_fractional():
    assert age_days(make_track(added_at=NOW - timedelta(hours=12)), NOW) == pytest.approx(0.5)


def test_age_days_helper_none():
    assert age_days(make_track(added_at=None), NOW) is None


def test_resolve_days_threshold_helper():
    assert resolve_days_threshold(rule({}, days_threshold=3), 14) == 3
    assert resolve_days_threshold(rule({}, days_threshold=0), 14) == 0
    assert resolve_days_threshold(rule({}), 14) == 14


# ----------------------------------------------------------------- Match result

def test_match_result_contents():
    t = make_track(added_at=days_ago(20), release_date="2001", release_date_precision="year")
    r = rule({"artist_in": ["bonobo"], "release_year_before": 2010, "explicit": False},
             name="combo", target="Dest")
    m = run(t, [r])
    assert isinstance(m, Match)
    assert m.rule is r
    assert m.matched == {"artist_in": "bonobo", "release_year_before": 2001, "explicit": False}
    assert m.age_days == pytest.approx(20)


# --------------------------------------------------------------- purity / mixed

def test_evaluate_does_not_mutate_inputs():
    t = make_track()
    e = Enrichment(genres=("jazz",), language="english")
    rules = [rule({"genre_contains": ["jazz"], "artist_in": ["Bonobo"]})]
    t0, e0, r0 = copy.deepcopy(t), copy.deepcopy(e), copy.deepcopy(rules)
    run(t, rules, e)
    assert t == t0 and e == e0 and rules == r0


def test_missing_enrichment_still_allows_artist_and_year_conditions():
    r_genre = rule({"genre_contains": ["jazz"]}, name="genre")
    r_lang = rule({"language_in": ["hindi"]}, name="lang")
    r_art = rule({"artist_in": ["Bonobo"], "release_year_before": 2010}, name="artist")
    m = run(make_track(), [r_genre, r_lang, r_art], None)
    assert m.rule.name == "artist"


def test_missing_enrichment_makes_combined_genre_and_artist_rule_fail():
    r = rule({"artist_in": ["Bonobo"], "genre_contains": ["jazz"]})
    assert run(make_track(), [r], None) is None


def test_naive_datetimes_are_treated_as_utc():
    track = make_track(added_at=datetime(2026, 9, 1))  # naive
    assert age_days(track, NOW) == pytest.approx(20)
    assert age_days(make_track(added_at=days_ago(3)), datetime(2026, 9, 21)) == pytest.approx(3)


# ---------------------------------------------------------------- explain()

from src.rules_engine import explain  # noqa: E402


def ex(track, rules, enrichment=None, default=14):
    return explain(track, enrichment, rules, NOW, default)


def results(tr):
    return [e["result"] for e in tr["trace"]]


BON = {"artist_in": ["Bonobo"]}
TYC = {"artist_in": ["Tycho"]}


def test_explain_matched():
    tr = ex(make_track(added_at=days_ago(30)), [rule(BON, "a")])
    assert results(tr) == ["matched"] and tr["decided_by"] == "a"


def test_explain_matched_too_young():
    tr = ex(make_track(added_at=days_ago(3)), [rule(BON, "a")])
    assert results(tr) == ["matched_too_young"] and tr["decided_by"] == "a"


def test_explain_age_boundary_exact_threshold_is_matched():
    assert results(ex(make_track(added_at=days_ago(14)), [rule(BON)])) == ["matched"]
    assert results(ex(make_track(added_at=days_ago(13.9)), [rule(BON)])) == ["matched_too_young"]


def test_explain_no_added_at_is_too_young_and_age_none():
    tr = ex(make_track(added_at=None), [rule(BON)])
    assert results(tr) == ["matched_too_young"] and tr["age_days"] is None


def test_explain_failed_and_decided_by_none():
    tr = ex(make_track(), [rule(TYC, "a")])
    assert results(tr) == ["failed"] and tr["decided_by"] is None


def test_explain_not_reached_variants():
    rules = [rule(BON, "a"), rule(BON, "b"), rule(TYC, "c")]
    tr = ex(make_track(), rules)
    assert results(tr) == ["matched", "not_reached_but_would_match", "not_reached"]


def test_explain_too_young_still_shadows_later_rules():
    tr = ex(make_track(added_at=days_ago(1)), [rule(BON, "a"), rule(BON, "b")])
    assert results(tr) == ["matched_too_young", "not_reached_but_would_match"]


def test_explain_skipped_disabled_and_empty():
    rules = [rule(BON, "off", enabled=False), rule({}, "empty"), rule(BON, "on")]
    tr = ex(make_track(), rules)
    assert results(tr) == ["skipped_disabled", "skipped_empty", "matched"]
    assert tr["trace"][0]["conditions"] == [] and tr["trace"][1]["conditions"] == []
    assert tr["trace"][0]["enabled"] is False and tr["decided_by"] == "on"


def test_explain_disabled_with_empty_match_is_disabled():
    assert results(ex(make_track(), [rule({}, enabled=False)])) == ["skipped_disabled"]


def test_explain_skipped_rules_after_decision_stay_skipped():
    tr = ex(make_track(), [rule(BON, "a"), rule(BON, "b", enabled=False), rule({}, "c")])
    assert results(tr) == ["matched", "skipped_disabled", "skipped_empty"]


def test_explain_per_condition_passed_and_actual():
    t = make_track(release_date="2005-06-01")
    tr = ex(t, [rule({"artist_in": ["Bonobo"], "release_year_before": 2000, "explicit": False}, "a")])
    conds = {c["key"]: c for c in tr["trace"][0]["conditions"]}
    assert conds["artist_in"] == {"key": "artist_in", "wanted": ["Bonobo"], "actual": ["Bonobo"], "passed": True}
    assert conds["release_year_before"]["passed"] is False and conds["release_year_before"]["actual"] == 2005
    assert conds["explicit"]["passed"] is True and conds["explicit"]["actual"] is False
    assert results(tr) == ["failed"]


def test_explain_evaluates_all_conditions_after_first_failure():
    tr = ex(make_track(), [rule({"artist_in": ["Nobody"], "explicit": False})])
    assert [c["passed"] for c in tr["trace"][0]["conditions"]] == [False, True]


def test_explain_genre_and_language_actuals():
    e = Enrichment(genres=("Trip Hop", "jazz"), language="english")
    tr = ex(make_track(), [rule({"genre_contains": ["hop"], "language_in": ["ENGLISH"]})], e)
    c = tr["trace"][0]["conditions"]
    assert c[0]["actual"] == ["Trip Hop", "jazz"] and c[0]["passed"]
    assert c[1]["actual"] == "english" and c[1]["passed"]


def test_explain_missing_enrichment_conditions_fail():
    tr = ex(make_track(), [rule({"language_in": ["english"]})], None)
    c = tr["trace"][0]["conditions"][0]
    assert c["actual"] is None and c["passed"] is False


def test_explain_unknown_key_fails():
    tr = ex(make_track(), [rule({"bogus": 1})])
    assert results(tr) == ["failed"] and tr["trace"][0]["conditions"][0]["passed"] is False


def test_explain_thresholds_per_rule_and_default():
    tr = ex(make_track(added_at=days_ago(10)), [rule(TYC, "a", days_threshold=3), rule(BON, "b"), rule(BON, "c", days_threshold=5)], default=30)
    assert [e["threshold_days"] for e in tr["trace"]] == [3, 30, 5]
    assert results(tr) == ["failed", "matched_too_young", "not_reached_but_would_match"]


def test_explain_per_rule_threshold_overrides_default():
    assert results(ex(make_track(added_at=days_ago(10)), [rule(BON, days_threshold=5)], default=30)) == ["matched"]


def test_explain_age_days_value_and_naive_now():
    tr = ex(make_track(added_at=days_ago(2.5)), [rule(BON)])
    assert tr["age_days"] == pytest.approx(2.5)


def test_explain_no_rules():
    assert ex(make_track(), []) == {"trace": [], "decided_by": None, "age_days": pytest.approx(30)}


def test_explain_agrees_with_first_match():
    from src.rules_engine import first_match
    rules = [rule(TYC, "a"), rule(BON, "b"), rule(BON, "c")]
    tr = ex(make_track(), rules)
    assert tr["decided_by"] == first_match(make_track(), None, rules, NOW).rule.name
