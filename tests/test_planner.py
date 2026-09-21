"""Unit tests for src/planner.py using fabricated data (no I/O, no network)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.models import Artist, Config, Enrichment, Playlist, Rule, Track
from src.planner import FALLBACK_RULE, build_plan, decide, resolve_target, targets_needed

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def days_ago(n: float) -> datetime:
    return NOW - timedelta(days=n)


def track(n=1, artist="Bonobo", age=30, **kw) -> Track:
    base = dict(
        id=f"t{n}", uri=f"spotify:track:t{n}", name=f"Song {n}",
        artists=(Artist(f"a-{artist}", artist),), album_name="Album",
        release_date="2005-06-01", release_date_precision="day", explicit=False,
        added_at=days_ago(age) if age is not None else None,
    )
    base.update(kw)
    return Track(**base)


def pl(name, id=None, owned=True, collaborative=False) -> Playlist:
    return Playlist(id=id or f"id-{name}", name=name, owner_id="me" if owned else "other",
                    owned=owned, collaborative=collaborative)


def rule(match, name="r", target="P", **kw) -> Rule:
    return Rule(name=name, target_playlist=target, match=match, **kw)


def cfg(*rules, default=14, fallback=None) -> Config:
    return Config(default_days_threshold=default, fallback_playlist=fallback, rules=tuple(rules))


BONOBO = {"artist_in": ["Bonobo"]}


# ------------------------------------------------------------------ decide()

def test_decide_move_when_matched_and_old():
    d = decide(track(age=30), None, cfg(rule(BONOBO, "chill", "Chill")), NOW)
    assert d.kind == "move" and d.rule_name == "chill" and d.target_name == "Chill"
    assert d.matched == {"artist_in": "Bonobo"}
    assert d.threshold == 14 and d.age_days == pytest.approx(30)


def test_decide_too_young_when_matched_but_recent():
    d = decide(track(age=3), None, cfg(rule(BONOBO)), NOW)
    assert d.kind == "too_young" and d.rule_name == "r" and d.threshold == 14


def test_decide_too_young_does_not_fall_through_to_broader_rule():
    narrow = rule(BONOBO, "narrow", "Narrow", days_threshold=60)
    broad = rule({"release_year_before": 2010}, "broad", "Broad", days_threshold=1)
    d = decide(track(age=30), None, cfg(narrow, broad), NOW)
    assert d.kind == "too_young" and d.rule_name == "narrow"


def test_decide_no_match():
    d = decide(track(artist="Other"), None, cfg(rule(BONOBO)), NOW)
    assert d.kind == "no_match" and d.rule_name is None and d.age_days == pytest.approx(30)


def test_decide_no_rules_no_match():
    assert decide(track(), None, cfg(), NOW).kind == "no_match"


def test_decide_fallback_used_for_old_unmatched():
    d = decide(track(artist="Other", age=20), None, cfg(rule(BONOBO), fallback="Misc"), NOW)
    assert d.kind == "move" and d.rule_name == FALLBACK_RULE and d.target_name == "Misc"
    assert d.create_missing is False and d.threshold == 14 and d.matched == {}


def test_decide_fallback_not_used_for_young_unmatched():
    d = decide(track(artist="Other", age=5), None, cfg(rule(BONOBO), fallback="Misc"), NOW)
    assert d.kind == "no_match"


def test_decide_fallback_boundary_exactly_threshold():
    d = decide(track(artist="Other", age=14), None, cfg(fallback="Misc"), NOW)
    assert d.kind == "move"


def test_decide_fallback_not_used_for_too_young_matched():
    d = decide(track(age=3), None, cfg(rule(BONOBO), fallback="Misc"), NOW)
    assert d.kind == "too_young"


def test_decide_fallback_ignored_with_only_rule():
    d = decide(track(artist="Other", age=99), None, cfg(rule(BONOBO, "a"), fallback="Misc"), NOW, only_rule="a")
    assert d.kind == "no_match"


def test_decide_fallback_ignores_rule_threshold_uses_default():
    d = decide(track(artist="Other", age=10), None,
               cfg(rule(BONOBO, days_threshold=1), fallback="Misc", default=14), NOW)
    assert d.kind == "no_match"


def test_decide_fallback_needs_added_at():
    d = decide(track(artist="Other", age=None), None, cfg(fallback="Misc"), NOW)
    assert d.kind == "no_match" and d.age_days is None


def test_decide_only_rule_matching_rule_moves_case_insensitive():
    d = decide(track(), None, cfg(rule(BONOBO, "Chill")), NOW, only_rule="cHILL")
    assert d.kind == "move"


def test_decide_only_rule_excludes_other_rules_moves():
    a = rule({"artist_in": ["Nobody"]}, "a", "A")
    b = rule(BONOBO, "b", "B")
    assert decide(track(), None, cfg(a, b), NOW, only_rule="a").kind == "no_match"


def test_decide_only_rule_respects_earlier_rule_precedence():
    a = rule(BONOBO, "a", "A")
    b = rule(BONOBO, "b", "B")
    assert decide(track(), None, cfg(a, b), NOW, only_rule="b").kind == "no_match"


def test_decide_only_rule_too_young_of_selected_rule_is_too_young():
    a = rule(BONOBO, "a", "A")
    assert decide(track(age=2), None, cfg(a), NOW, only_rule="a").kind == "too_young"


def test_decide_per_rule_threshold_override():
    r = rule(BONOBO, days_threshold=3)
    assert decide(track(age=5), None, cfg(r, default=14), NOW).kind == "move"
    assert decide(track(age=5), None, cfg(rule(BONOBO), default=14), NOW).kind == "too_young"


def test_decide_disabled_rule_ignored_and_next_used():
    off = rule(BONOBO, "off", "Off", enabled=False)
    on = rule(BONOBO, "on", "On")
    assert decide(track(), None, cfg(off, on), NOW).rule_name == "on"


def test_decide_missing_added_at_never_moves():
    d = decide(track(age=None), None, cfg(rule(BONOBO)), NOW)
    assert d.kind == "too_young" and d.age_days is None


def test_decide_language_rule_uses_enrichment():
    r = rule({"language_in": ["hindi"]})
    assert decide(track(), Enrichment(language="hindi"), cfg(r), NOW).kind == "move"
    assert decide(track(), Enrichment(language="tamil"), cfg(r), NOW).kind == "no_match"


def test_decide_genre_rule_uses_enrichment():
    r = rule({"genre_contains": ["jazz"]})
    d = decide(track(), Enrichment(genres=("Nu Jazz",)), cfg(r), NOW)
    assert d.kind == "move" and d.matched == {"genre_contains": "jazz"}


def test_decide_missing_enrichment_makes_genre_and_language_false():
    assert decide(track(), None, cfg(rule({"genre_contains": ["jazz"]})), NOW).kind == "no_match"
    assert decide(track(), None, cfg(rule({"language_in": ["hindi"]})), NOW).kind == "no_match"
    assert decide(track(), Enrichment(), cfg(rule({"language_in": ["hindi"]})), NOW).kind == "no_match"


def test_decide_create_missing_flag_propagates():
    d = decide(track(), None, cfg(rule(BONOBO, create_missing_playlists=True)), NOW)
    assert d.create_missing is True


# ------------------------------------------------------------- resolve_target()

def test_resolve_exact_owned():
    p = pl("Chill")
    assert resolve_target("Chill", [p]) == (p, None, None)


def test_resolve_case_and_whitespace_variants():
    p = pl("Chill Vibes")
    for name in ("chill vibes", "CHILL VIBES", "  Chill Vibes  "):
        assert resolve_target(name, [p])[0] is p


def test_resolve_playlist_name_with_padding_matches_query():
    p = pl("  Chill ")
    assert resolve_target("chill", [p])[0] is p


def test_resolve_inner_whitespace_is_not_collapsed():
    assert resolve_target("Chill  Vibes", [pl("Chill Vibes")])[1] == "missing"


def test_resolve_collaborative_not_owned_ok():
    p = pl("Collab", owned=False, collaborative=True)
    assert resolve_target("Collab", [p])[0] is p


def test_resolve_followed_only_is_not_writable():
    p, problem, warning = resolve_target("Theirs", [pl("Theirs", owned=False)])
    assert p is None and problem == "not_writable" and "followed" in warning


def test_resolve_missing():
    p, problem, warning = resolve_target("Nope", [pl("Other")])
    assert p is None and problem == "missing" and "Nope" in warning


def test_resolve_empty_playlist_list_missing():
    assert resolve_target("X", [])[1] == "missing"


def test_resolve_ambiguous_two_usable():
    p, problem, warning = resolve_target("Dup", [pl("Dup", "1"), pl("dup", "2", owned=False, collaborative=True)])
    assert p is None and problem == "ambiguous" and "2" in warning


def test_resolve_followed_same_name_prefers_owned():
    mine, theirs = pl("Mix", "mine"), pl("Mix", "theirs", owned=False)
    assert resolve_target("Mix", [theirs, mine])[0] is mine


# ------------------------------------------------------------------ build_plan()

def plan_for(tracks, config, playlists, enrichments=None, membership=None, **kw):
    return build_plan(tracks, enrichments or {}, config, NOW, playlists, membership, **kw)


def test_plan_move_records_explanation():
    t = track(1, age=30)
    p = plan_for([t], cfg(rule(BONOBO, "chill", "Chill", days_threshold=7)), [pl("Chill", "pid")])
    (m,) = p.moves
    assert m["rule"] == "chill" and m["matched"] == {"artist_in": "Bonobo"}
    assert m["age_days"] == 30.0 and m["threshold_days"] == 7
    assert m["playlist"] == "Chill" and m["playlist_id"] == "pid"
    assert m["uri"] == t.uri and m["track"] == "Song 1" and m["artist"] == "Bonobo"
    assert m["original_added_at"] == t.added_at.isoformat()
    assert p.evaluated == 1 and p.skipped_no_match == 0


def test_plan_artist_joined_for_multiple_artists():
    t = track(1, artists=(Artist("1", "Bonobo"), Artist("2", "Cinna")))
    p = plan_for([t], cfg(rule(BONOBO)), [pl("P")])
    assert p.moves[0]["artist"] == "Bonobo, Cinna"


def test_plan_already_in_target_flag_from_membership():
    t1, t2 = track(1), track(2)
    p = plan_for([t1, t2], cfg(rule(BONOBO)), [pl("P", "pid")], membership={"pid": {t1.uri}})
    flags = {m["uri"]: m["already_in_target"] for m in p.moves}
    assert flags == {t1.uri: True, t2.uri: False}


def test_plan_membership_of_other_playlist_does_not_count():
    t = track(1)
    p = plan_for([t], cfg(rule(BONOBO)), [pl("P", "pid")], membership={"other": {t.uri}})
    assert p.moves[0]["already_in_target"] is False


def test_plan_missing_playlist_entry_and_warning():
    p = plan_for([track()], cfg(rule(BONOBO, "r", "Ghost")), [pl("Other")])
    assert p.moves == []
    (s,) = p.skipped_playlist_missing
    assert s == {"track": "Song 1", "target_playlist": "Ghost", "rule": "r", "reason": "missing", "would_create": False}
    assert len(p.warnings) == 1 and "Ghost" in p.warnings[0]


def test_plan_would_create_only_when_flag_and_missing():
    p = plan_for([track()], cfg(rule(BONOBO, "r", "Ghost", create_missing_playlists=True)), [])
    assert p.skipped_playlist_missing[0]["would_create"] is True


def test_plan_would_create_false_when_not_writable_even_with_flag():
    r = rule(BONOBO, "r", "Theirs", create_missing_playlists=True)
    p = plan_for([track()], cfg(r), [pl("Theirs", owned=False)])
    s = p.skipped_playlist_missing[0]
    assert s["reason"] == "not_writable" and s["would_create"] is False


def test_plan_would_create_false_when_ambiguous():
    r = rule(BONOBO, "r", "Dup", create_missing_playlists=True)
    p = plan_for([track()], cfg(r), [pl("Dup", "1"), pl("Dup", "2")])
    assert p.skipped_playlist_missing[0]["reason"] == "ambiguous"
    assert p.skipped_playlist_missing[0]["would_create"] is False


def test_plan_warnings_deduplicated_per_name():
    ts = [track(i) for i in range(5)]
    p = plan_for(ts, cfg(rule(BONOBO, "r", "Ghost")), [])
    assert len(p.skipped_playlist_missing) == 5 and len(p.warnings) == 1


def test_plan_distinct_missing_names_each_warn():
    r1 = rule({"artist_in": ["A"]}, "r1", "Ghost1")
    r2 = rule({"artist_in": ["B"]}, "r2", "Ghost2")
    p = plan_for([track(1, "A"), track(2, "B"), track(3, "A")], cfg(r1, r2), [])
    assert len(p.warnings) == 2


def test_plan_limit_caps_moves_and_takes_oldest_first():
    ts = [track(1, age=20), track(2, age=90), track(3, age=50), track(4, age=70)]
    p = plan_for(ts, cfg(rule(BONOBO)), [pl("P")], limit=2)
    assert [m["uri"] for m in p.moves] == ["spotify:track:t2", "spotify:track:t4"]
    assert p.evaluated == 4


def test_plan_limit_zero_yields_no_moves():
    p = plan_for([track()], cfg(rule(BONOBO)), [pl("P")], limit=0)
    assert p.moves == []


def test_plan_limit_larger_than_candidates():
    p = plan_for([track(1), track(2)], cfg(rule(BONOBO)), [pl("P")], limit=50)
    assert len(p.moves) == 2


def test_plan_limit_does_not_count_missing_targets():
    r1 = rule({"artist_in": ["A"]}, "r1", "Ghost")
    r2 = rule({"artist_in": ["B"]}, "r2", "P")
    ts = [track(1, "A", age=100), track(2, "B", age=50)]
    p = plan_for(ts, cfg(r1, r2), [pl("P")], limit=1)
    assert len(p.moves) == 1 and len(p.skipped_playlist_missing) == 1


def test_plan_moves_sorted_oldest_first_without_limit():
    ts = [track(1, age=20), track(2, age=90), track(3, age=50)]
    p = plan_for(ts, cfg(rule(BONOBO)), [pl("P")])
    assert [m["uri"] for m in p.moves] == ["spotify:track:t2", "spotify:track:t3", "spotify:track:t1"]


def test_plan_since_filter_keeps_on_or_after():
    ts = [track(1, age=100), track(2, age=40), track(3, age=20)]
    p = plan_for(ts, cfg(rule(BONOBO)), [pl("P")], since=days_ago(40))
    assert {m["uri"] for m in p.moves} == {"spotify:track:t2", "spotify:track:t3"}
    assert p.evaluated == 2


def test_plan_since_excludes_tracks_without_added_at():
    p = plan_for([track(1, age=None), track(2)], cfg(rule(BONOBO)), [pl("P")], since=days_ago(500))
    assert p.evaluated == 1


def test_plan_no_match_counter():
    ts = [track(1), track(2, "Other"), track(3, "Another")]
    p = plan_for(ts, cfg(rule(BONOBO)), [pl("P")])
    assert p.skipped_no_match == 2 and len(p.moves) == 1 and p.evaluated == 3


def test_plan_too_young_list():
    p = plan_for([track(1, age=3)], cfg(rule(BONOBO, "chill")), [pl("P")])
    assert p.moves == []
    assert p.skipped_too_young == [
        {"track": "Song 1", "artist": "Bonobo", "rule": "chill", "age_days": 3.0, "threshold_days": 14}
    ]


def test_plan_too_young_track_without_artists():
    t = track(1, age=3, artists=())
    p = plan_for([t], cfg(rule({"track_name_contains": "song"})), [pl("P")])
    assert p.skipped_too_young[0]["artist"] == ""


def test_plan_tracks_without_added_at_never_moved_even_with_fallback():
    p = plan_for([track(1, age=None)], cfg(rule(BONOBO), fallback="P"), [pl("P")])
    assert p.moves == []
    p2 = plan_for([track(2, "Other", age=None)], cfg(fallback="P"), [pl("P")])
    assert p2.moves == [] and p2.skipped_no_match == 1


def test_plan_tracks_without_added_at_sorted_last_and_counted():
    ts = [track(1, age=None), track(2, age=30)]
    p = plan_for(ts, cfg(rule(BONOBO)), [pl("P")])
    assert p.evaluated == 2 and len(p.moves) == 1 and len(p.skipped_too_young) == 1


def test_plan_enrichment_missing_for_track_makes_genre_rule_false():
    r = rule({"genre_contains": ["jazz"]})
    p = plan_for([track(1), track(2)], cfg(r), [pl("P")], enrichments={"t1": Enrichment(genres=("jazz",))})
    assert [m["uri"] for m in p.moves] == ["spotify:track:t1"]
    assert p.skipped_no_match == 1


def test_plan_language_rule_driven_by_enrichment():
    r = rule({"language_in": ["malayalam"]}, "ml", "ML")
    en = {"t1": Enrichment(language="malayalam"), "t2": Enrichment(language="hindi")}
    p = plan_for([track(1), track(2), track(3)], cfg(r), [pl("ML")], enrichments=en)
    assert [m["uri"] for m in p.moves] == ["spotify:track:t1"]
    assert p.moves[0]["matched"] == {"language_in": "malayalam"}
    assert p.skipped_no_match == 2


def test_plan_genre_rule_driven_by_enrichment():
    r = rule({"genre_contains": ["hip hop"]}, "hh", "HH")
    p = plan_for([track(1)], cfg(r), [pl("HH")], enrichments={"t1": Enrichment(genres=("Hip Hop", "rap"))})
    assert p.moves[0]["matched"] == {"genre_contains": "hip hop"}


def test_plan_fallback_move_recorded():
    p = plan_for([track(1, "Other", age=30)], cfg(rule(BONOBO), fallback="Misc"), [pl("Misc", "m")])
    assert p.moves[0]["rule"] == FALLBACK_RULE and p.moves[0]["playlist_id"] == "m"
    assert p.moves[0]["matched"] == {}


def test_plan_fallback_missing_playlist_never_would_create():
    p = plan_for([track(1, "Other", age=30)], cfg(fallback="Misc"), [])
    assert p.skipped_playlist_missing[0]["would_create"] is False
    assert p.skipped_playlist_missing[0]["rule"] == FALLBACK_RULE


def test_plan_per_rule_threshold_override():
    r1 = rule({"artist_in": ["A"]}, "fast", "P", days_threshold=2)
    r2 = rule({"artist_in": ["B"]}, "slow", "P")
    p = plan_for([track(1, "A", age=5), track(2, "B", age=5)], cfg(r1, r2, default=14), [pl("P")])
    assert [m["rule"] for m in p.moves] == ["fast"]
    assert [s["rule"] for s in p.skipped_too_young] == ["slow"]


def test_plan_disabled_rules_ignored():
    p = plan_for([track()], cfg(rule(BONOBO, enabled=False)), [pl("P")])
    assert p.moves == [] and p.skipped_no_match == 1


def test_plan_only_rule_limits_moves_to_that_rule():
    a = rule({"artist_in": ["A"]}, "a", "PA")
    b = rule({"artist_in": ["B"]}, "b", "PB")
    p = plan_for([track(1, "A"), track(2, "B")], cfg(a, b), [pl("PA"), pl("PB")], only_rule="b")
    assert [m["rule"] for m in p.moves] == ["b"] and p.skipped_no_match == 1


def test_plan_empty_input():
    p = plan_for([], cfg(rule(BONOBO)), [])
    assert p.evaluated == 0 and p.moves == [] and p.warnings == []


def test_plan_accepts_generator_input():
    p = plan_for((track(i) for i in range(3)), cfg(rule(BONOBO)), [pl("P")])
    assert p.evaluated == 3


def test_plan_moves_to_owned_when_followed_duplicate_exists():
    p = plan_for([track()], cfg(rule(BONOBO, "r", "Mix")), [pl("Mix", "theirs", owned=False), pl("Mix", "mine")])
    assert p.moves[0]["playlist_id"] == "mine" and p.warnings == []


# --------------------------------------------------------------- targets_needed()

def test_targets_needed_only_resolved_move_playlists():
    a = rule({"artist_in": ["A"]}, "a", "PA")
    b = rule({"artist_in": ["B"]}, "b", "PB")
    c = rule({"artist_in": ["C"]}, "c", "Ghost")
    d = rule({"artist_in": ["D"]}, "d", "PD")
    ts = [track(1, "A"), track(2, "B", age=2), track(3, "C"), track(4, "Z"), track(5, "D", age=1)]
    pls = [pl("PA", "ida"), pl("PB", "idb"), pl("PD", "idd")]
    assert targets_needed(ts, {}, cfg(a, b, c, d), NOW, pls) == {"ida"}


def test_targets_needed_respects_only_rule():
    a = rule({"artist_in": ["A"]}, "a", "PA")
    b = rule({"artist_in": ["B"]}, "b", "PB")
    ts = [track(1, "A"), track(2, "B")]
    pls = [pl("PA", "ida"), pl("PB", "idb")]
    assert targets_needed(ts, {}, cfg(a, b), NOW, pls, only_rule="b") == {"idb"}


def test_targets_needed_empty_when_nothing_moves():
    assert targets_needed([track(age=1)], {}, cfg(rule(BONOBO)), NOW, [pl("P")]) == set()


def test_targets_needed_includes_fallback_playlist():
    ts = [track(1, "Other", age=30)]
    assert targets_needed(ts, {}, cfg(fallback="Misc"), NOW, [pl("Misc", "m")]) == {"m"}


def test_targets_needed_ignores_ambiguous_and_followed():
    r = rule(BONOBO, "r", "Dup")
    assert targets_needed([track()], {}, cfg(r), NOW, [pl("Dup", "1"), pl("Dup", "2")]) == set()
    assert targets_needed([track()], {}, cfg(r), NOW, [pl("Dup", "1", owned=False)]) == set()
