"""Unit tests for src/artifacts.py (dashboard run artifacts) using fabricated data; writes only to tmp_path."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src import artifacts
from src.artifacts import (
    atomic_write_json, build_latest_plan, config_hash, iso, run_entry, update_runs_index,
)
from src.models import Artist, Config, Enrichment, Playlist, Rule, Track

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
BON = {"artist_in": ["Bonobo"]}


def days_ago(n):
    return NOW - timedelta(days=n)


def trk(n, artist="Bonobo", age=30, **kw):
    base = dict(id=f"t{n}", uri=f"spotify:track:t{n}", name=f"Song {n}", artists=(Artist(f"a-{artist}", artist),),
                album_name="Album", release_date="2005-06-01", release_date_precision="day",
                added_at=days_ago(age) if age is not None else None)
    base.update(kw)
    return Track(**base)


def pl(name, id=None, owned=True, total=None):
    return Playlist(id=id or f"id-{name}", name=name, owner_id="me" if owned else "o", owned=owned,
                    collaborative=False, items_total=total)


PLAYLISTS = [pl("Chill", total=42), pl("Hindi", total=7), pl("Twin", "tw1"), pl("Twin", "tw2"), pl("Followed", owned=False)]


def R(name, match, target, **kw):
    return Rule(name=name, target_playlist=target, match=match, **kw)


RULES = (
    R("hindi", {"language_in": ["hindi"]}, "Hindi", target_position="top"),
    R("chill", {"artist_in": ["Bonobo"]}, "Chill"),
    R("chill2", {"artist_in": ["Bonobo"]}, "Chill"),          # shadowed by chill
    R("ghost", {"artist_in": ["Tycho"]}, "Ghost"),             # missing
    R("twin", {"artist_in": ["Dupe"]}, "Twin"),                # ambiguous
    R("ro", {"artist_in": ["Ro"]}, "Followed"),                # not_writable
    R("off", {"artist_in": ["Offy"]}, "Chill", enabled=False),
    R("dead", {"artist_in": ["Zzz"]}, "Chill"),
    R("slow", {"artist_in": ["Slowpoke"]}, "Chill", days_threshold=100),
)
CFG = Config(default_days_threshold=14, rules=RULES, english_default=True)


def plan(tracks, enr=None, cfg=CFG, **kw):
    return build_latest_plan(tracks, enr or {}, cfg, NOW, PLAYLISTS, **kw)


def by_id(p, n):
    return next(s for s in p["songs"] if s["uri"].endswith(f"t{n}"))


def rule_of(p, name):
    return next(r for r in p["rules"] if r["name"] == name)


# ------------------------------------------------------------------ helpers

def test_iso_and_hash():
    assert iso(None) is None
    assert iso(NOW) == "2026-09-21T12:00:00+00:00"
    assert iso(datetime(2026, 9, 21, 14, 0, tzinfo=timezone(timedelta(hours=2)))) == "2026-09-21T12:00:00+00:00"
    assert config_hash("a") == config_hash("a") and config_hash("a") != config_hash("b") and len(config_hash("a")) == 12


# ------------------------------------------------------------------ decisions

def test_decision_will_move():
    s = by_id(plan([trk(1)]), 1)
    assert s["decision"] == "will_move" and s["rule"] == "chill" and s["target_playlist"] == "Chill"
    assert s["target_status"] == "resolved" and "chill" in s["reason"]


def test_decision_too_young_and_eligible_on():
    s = by_id(plan([trk(1, age=4)]), 1)
    assert s["decision"] == "too_young" and s["eligible_on"] == iso(days_ago(4) + timedelta(days=14))
    assert "14 days" in s["reason"] and s["target_status"] is None


def test_eligible_on_uses_rule_threshold():
    s = by_id(plan([trk(1, "Slowpoke", age=10)]), 1)
    assert s["decision"] == "too_young" and s["eligible_on"] == iso(days_ago(10) + timedelta(days=100))


def test_eligible_on_also_set_for_will_move():
    s = by_id(plan([trk(1, age=30)]), 1)
    assert s["eligible_on"] == iso(days_ago(30) + timedelta(days=14))


def test_decision_no_match_fields_none():
    s = by_id(plan([trk(1, "Nobody")]), 1)
    assert s["decision"] == "no_match" and s["rule"] is None and s["target_playlist"] is None
    assert s["eligible_on"] is None and s["target_position"] is None and s["reason"] == "no enabled rule matched"


@pytest.mark.parametrize("artist,problem", [("Tycho", "missing"), ("Dupe", "ambiguous"), ("Ro", "not_writable")])
def test_decision_target_problem(artist, problem):
    s = by_id(plan([trk(1, artist)]), 1)
    assert s["decision"] == "target_problem" and s["target_status"] == problem and problem in s["reason"]
    assert s["target_playlist"] in ("Ghost", "Twin", "Followed")


def test_target_problem_too_young_stays_too_young():
    assert by_id(plan([trk(1, "Tycho", age=1)]), 1)["decision"] == "too_young"


def test_decision_blocked_by_withheld_weak_signal():
    e = {"t1": Enrichment(language="hindi", language_source="hint", language_confidence=0.6)}
    p = plan([trk(1, "Nobody")], e)
    s = by_id(p, 1)
    assert s["decision"] == "blocked" and "hindi" in s["reason"] and "hint" in s["reason"] and "unmeasured" in s["reason"]
    assert s["language"]["withheld"]["reason"] == "unmeasured" and s["language"]["used_for_rules"] is False
    assert s["language"]["value"] == "hindi" and s["language"]["source"] == "hint"
    assert p["counts"]["blocked"] == 1


def test_blocked_reason_below_90_percent():
    prec = {"by_signal": {"hint": {"hindi": {"predicted": 50, "precision": 0.5}}}}
    e = {"t1": Enrichment(language="hindi", language_source="hint")}
    s = by_id(plan([trk(1, "Nobody")], e, precision=prec), 1)
    assert s["decision"] == "blocked" and "below 90 percent" in s["reason"] and s["language"]["withheld"]["precision"] == 0.5


def test_blocked_too_young_counts_as_blocked():
    e = {"t1": Enrichment(language="hindi", language_source="hint")}
    assert by_id(plan([trk(1, "Nobody", age=1)], e), 1)["decision"] == "blocked"


def test_withheld_signal_without_would_be_match_is_no_match():
    e = {"t1": Enrichment(language="tamil", language_source="hint")}
    s = by_id(plan([trk(1, "Nobody")], e), 1)
    assert s["decision"] == "no_match" and s["language"]["withheld"] is not None


def test_qualified_signal_drives_rule():
    prec = {"by_signal": {"hint": {"hindi": {"predicted": 30, "precision": 0.95}}}}
    e = {"t1": Enrichment(language="hindi", language_source="hint", language_confidence=0.6)}
    s = by_id(plan([trk(1, "Nobody")], e, precision=prec), 1)
    assert s["decision"] == "will_move" and s["rule"] == "hindi" and s["language"]["used_for_rules"] is True
    assert s["language"]["withheld"] is None


def test_trusted_signal_without_precision_drives_rule():
    e = {"t1": Enrichment(language="hindi", language_source="script", language_confidence=0.9)}
    s = by_id(plan([trk(1, "Nobody")], e), 1)
    assert s["decision"] == "will_move" and s["target_position"] == "top"


def test_precision_none_blocks_country_default():
    e = {"t1": Enrichment(language="hindi", language_source="country_default")}
    assert by_id(plan([trk(1, "Nobody")], e), 1)["decision"] == "blocked"


# ------------------------------------------------------------------ counts / songs

def test_counts_sum_to_total():
    tracks = [trk(1), trk(2, age=2), trk(3, "Nobody"), trk(4, "Tycho"), trk(5, "Dupe")]
    p = plan(tracks)
    assert p["counts"] == {"will_move": 1, "too_young": 1, "no_match": 1, "target_problem": 2, "blocked": 0}
    assert sum(p["counts"].values()) == p["liked_total"] == 5


def test_songs_oldest_first_and_undated_last():
    p = plan([trk(1, age=5), trk(2, age=50), trk(3, age=None), trk(4, age=20)])
    assert [s["uri"][-2:] for s in p["songs"]] == ["t2", "t4", "t1", "t3"]
    assert p["songs"][-1]["added_at"] is None and p["songs"][-1]["age_days"] is None


def test_song_basic_fields():
    t = trk(1, artists=(Artist("a", "Bonobo"), Artist("b", "Feat")))
    s = plan([t])["songs"][0]
    assert s["title"] == "Song 1" and s["artists"] == ["Bonobo", "Feat"] and s["uri"] == "spotify:track:t1"
    assert s["added_at"] == iso(days_ago(30)) and s["age_days"] == 30.0


def test_target_position_propagates():
    e = {"t1": Enrichment(language="hindi", language_source="script")}
    p = plan([trk(1, "Nobody"), trk(2)], e)
    assert by_id(p, 1)["target_position"] == "top" and by_id(p, 2)["target_position"] == "bottom"


def test_language_and_genre_source_confidence():
    e = {"t1": Enrichment(genres=("jazz", "trip hop"), language="english", language_source="script", language_confidence=0.9,
                          genre_source="musicbrainz", genre_confidence=0.6)}
    s = by_id(plan([trk(1)], e), 1)
    assert s["language"] == {"value": "english", "source": "script", "confidence": 0.9, "used_for_rules": True, "withheld": None}
    assert s["genres"] == {"values": ["jazz", "trip hop"], "source": "musicbrainz", "confidence": 0.6}


def test_no_enrichment_language_and_genres_empty():
    s = by_id(plan([trk(1)]), 1)
    assert s["language"] == {"value": None, "source": None, "confidence": None, "used_for_rules": False, "withheld": None}
    assert s["genres"] == {"values": [], "source": None, "confidence": None}


def test_explain_embedded_uses_gated_enrichment():
    e = {"t1": Enrichment(language="hindi", language_source="hint")}
    s = by_id(plan([trk(1, "Nobody")], e), 1)
    assert s["explain"]["decided_by"] is None
    c = s["explain"]["trace"][0]["conditions"][0]
    assert c["actual"] is None and c["passed"] is False


def test_top_level_fields():
    p = plan([trk(1)], run_id="r1", mode="live", cfg_hash="abc", inbox_kind="inbox")
    assert p["version"] == 1 and p["run_id"] == "r1" and p["mode"] == "live" and p["config_hash"] == "abc"
    assert p["inbox_kind"] == "inbox" and p["what_if"] is False and p["generated_at"] == iso(NOW)
    assert p["default_days_threshold"] == 14 and p["english_default"] is True and p["liked_total"] == 1
    d = build_latest_plan([], {}, CFG, NOW, PLAYLISTS)
    assert d["mode"] == "dry_run" and d["inbox_kind"] == "legacy_library" and d["songs"] == [] and d["run_id"] == ""


def test_json_serialisable_roundtrip():
    e = {"t1": Enrichment(genres=("jazz",), language="hindi", language_source="hint")}
    p = plan([trk(1, "Nobody"), trk(2), trk(3, "Tycho"), trk(4, age=None)], e)
    assert json.loads(json.dumps(p)) == p


def test_empty_tracks():
    p = plan([])
    assert p["counts"] == {"will_move": 0, "too_young": 0, "no_match": 0, "target_problem": 0, "blocked": 0}
    assert all(r["would_match"] == 0 for r in p["rules"])


# ------------------------------------------------------------------ rules section

def test_rule_status_ok_dead_shadowed_disabled():
    p = plan([trk(1), trk(2)])
    assert [r["name"] for r in p["rules"]] == [r.name for r in RULES]
    assert rule_of(p, "chill")["status"] == "ok" and rule_of(p, "chill")["wins"] == 2
    assert rule_of(p, "chill2")["status"] == "shadowed"
    assert rule_of(p, "chill2")["would_match"] == 2 and rule_of(p, "chill2")["wins"] == 0
    assert rule_of(p, "dead")["status"] == "dead" and rule_of(p, "dead")["would_match"] == 0
    assert rule_of(p, "off")["status"] == "disabled"


def test_too_young_counts_as_win():
    p = plan([trk(1, age=1)])
    assert rule_of(p, "chill")["wins"] == 1 and rule_of(p, "chill")["would_match"] == 1


def test_wins_and_would_match_multiple_tracks():
    p = plan([trk(1), trk(2, "Nobody"), trk(3, age=1)])
    r = rule_of(p, "chill")
    assert r["would_match"] == 2 and r["wins"] == 2
    assert rule_of(p, "chill2")["would_match"] == 2


def test_rule_info_fields():
    p = plan([])
    r = rule_of(p, "slow")
    assert r["threshold_days"] == 100 and r["target_playlist"] == "Chill" and r["target_position"] == "bottom"
    assert r["conditions"] == {"artist_in": ["Slowpoke"]} and r["uses_language"] is False and r["weak_signals_possible"] == []
    h = rule_of(p, "hindi")
    assert h["uses_language"] is True and h["weak_signals_possible"] == ["language_in:hint", "language_in:country_default"]
    assert h["threshold_days"] == 14 and h["target_position"] == "top"


@pytest.mark.parametrize("name,status", [("chill", "resolved"), ("ghost", "missing"), ("twin", "ambiguous"), ("ro", "not_writable")])
def test_rule_target_status(name, status):
    assert rule_of(plan([]), name)["target_status"] == status


def test_what_if_enables_disabled_rules():
    t = trk(1, "Offy")
    assert by_id(plan([t]), 1)["decision"] == "no_match"
    p = plan([t], what_if=True)
    assert p["what_if"] is True and by_id(p, 1)["decision"] == "will_move" and by_id(p, 1)["rule"] == "off"
    assert rule_of(p, "off")["status"] == "ok" and rule_of(p, "off")["enabled"] is True


def test_what_if_does_not_mutate_config():
    plan([trk(1)], what_if=True)
    assert CFG.rules[6].enabled is False


def test_disabled_rule_not_counted_without_what_if():
    r = rule_of(plan([trk(1, "Offy")]), "off")
    assert r["would_match"] == 0 and r["status"] == "disabled"


# ------------------------------------------------------------------ playlists section

def test_playlists_section_planned_in_and_size():
    p = plan([trk(1), trk(2), trk(3, "Nobody")])
    pls = {x["name"]: x for x in p["playlists"]}
    assert pls["Chill"]["planned_in"] == 2 and pls["Chill"]["size"] == 42 and pls["Chill"]["status"] == "resolved"
    assert pls["Chill"]["rules"] == ["chill", "chill2", "off", "dead", "slow"]
    assert pls["Ghost"]["status"] == "missing" and pls["Ghost"]["size"] is None and pls["Ghost"]["planned_in"] == 0
    assert pls["Twin"]["status"] == "ambiguous" and pls["Followed"]["status"] == "not_writable"


def test_playlists_deduped_casefolded_in_rule_order():
    cfg = Config(rules=(R("a", BON, "chill"), R("b", BON, "CHILL"), R("c", BON, "Hindi")))
    p = build_latest_plan([trk(1)], {}, cfg, NOW, PLAYLISTS)
    assert [x["name"] for x in p["playlists"]] == ["chill", "Hindi"]
    assert p["playlists"][0]["rules"] == ["a", "b"] and p["playlists"][0]["planned_in"] == 1


def test_planned_in_counts_only_will_move():
    p = plan([trk(1, age=1), trk(2, "Tycho")])
    assert all(x["planned_in"] == 0 for x in p["playlists"])


def test_planned_in_hindi_top():
    e = {"t1": Enrichment(language="hindi", language_source="playlist")}
    p = plan([trk(1, "Nobody")], e)
    assert next(x for x in p["playlists"] if x["name"] == "Hindi")["planned_in"] == 1


# ------------------------------------------------------------------ run_entry

def entry(**kw):
    base = dict(run_id="r1", now=NOW, mode="live",
                plan_counts={"will_move": 3, "too_young": 2, "no_match": 5, "blocked": 1, "target_problem": 4},
                moved=3, errors=0, warnings=2, liked_before=10, liked_after=7, duration_s=1.26,
                rule_counts={"a": 3}, log_file="logs/x.json")
    base.update(kw)
    return run_entry(**base)


def test_run_entry_ok_and_fields():
    e = entry()
    assert e["verdict"] == "ok" and e["planned_moves"] == 3 and e["moved"] == 3 and e["too_young"] == 2 and e["no_match"] == 5
    assert e["blocked"] == 1 and e["target_problems"] == 4 and e["warnings"] == 2 and e["duration_seconds"] == 1.3
    assert e["time"] == iso(NOW) and e["log"] == "logs/x.json" and e["rule_counts"] == {"a": 3} and e["what_if"] is False


def test_run_entry_dry_run():
    assert entry(mode="dry_run", moved=0, liked_after=10)["verdict"] == "dry_run"


def test_run_entry_mismatch():
    assert entry(liked_after=8)["verdict"] == "mismatch"


def test_run_entry_error_beats_everything():
    assert entry(errors=1)["verdict"] == "error"
    assert entry(errors=2, mode="dry_run")["verdict"] == "error"
    assert entry(errors=1, liked_after=99)["verdict"] == "error"


def test_run_entry_missing_plan_counts_default_zero():
    e = entry(plan_counts={})
    assert e["planned_moves"] == 0 and e["target_problems"] == 0 and e["blocked"] == 0


def test_run_entry_rule_counts_copied():
    rc = {"a": 1}
    e = entry(rule_counts=rc)
    rc["b"] = 2
    assert e["rule_counts"] == {"a": 1}


def test_run_entry_json_serialisable():
    json.dumps(entry())


# ------------------------------------------------------------------ update_runs_index

def e_(rid, **kw):
    return {"run_id": rid, **kw}


def test_index_created_when_missing(tmp_path):
    f = tmp_path / "logs" / "runs.json"
    d = update_runs_index(f, e_("a"), NOW)
    assert d == {"version": 1, "generated_at": iso(NOW), "runs": [e_("a")]}
    assert json.loads(f.read_text(encoding="utf-8")) == d


def test_index_newest_first(tmp_path):
    f = tmp_path / "runs.json"
    for r in "abc":
        update_runs_index(f, e_(r), NOW)
    assert [r["run_id"] for r in json.loads(f.read_text())["runs"]] == ["c", "b", "a"]


def test_index_dedupes_run_id_and_moves_to_front(tmp_path):
    f = tmp_path / "runs.json"
    for r in "abc":
        update_runs_index(f, e_(r, v=1), NOW)
    d = update_runs_index(f, e_("a", v=2), NOW)
    assert [r["run_id"] for r in d["runs"]] == ["a", "c", "b"] and d["runs"][0]["v"] == 2


def test_index_caps_at_90(tmp_path):
    f = tmp_path / "runs.json"
    for n in range(95):
        d = update_runs_index(f, e_(f"r{n}"), NOW)
    assert len(d["runs"]) == 90 and d["runs"][0]["run_id"] == "r94" and d["runs"][-1]["run_id"] == "r5"
    assert artifacts.RUNS_KEPT == 90


def test_index_exactly_90_kept(tmp_path):
    f = tmp_path / "runs.json"
    for n in range(90):
        d = update_runs_index(f, e_(f"r{n}"), NOW)
    assert len(d["runs"]) == 90 and d["runs"][-1]["run_id"] == "r0"


@pytest.mark.parametrize("content", ["{not json", "[]", '{"runs": 5}', '"str"', "", '{"version": 1}'])
def test_index_tolerates_corrupt_existing(tmp_path, content):
    f = tmp_path / "runs.json"
    f.write_text(content, encoding="utf-8")
    d = update_runs_index(f, e_("new"), NOW)
    assert [r["run_id"] for r in d["runs"]] == ["new"]
    assert json.loads(f.read_text())["runs"] == d["runs"]


def test_index_drops_non_dict_rows(tmp_path):
    f = tmp_path / "runs.json"
    f.write_text(json.dumps({"runs": [e_("x"), 5, "s", None]}), encoding="utf-8")
    assert [r["run_id"] for r in update_runs_index(f, e_("y"), NOW)["runs"]] == ["y", "x"]


def test_index_atomic_leaves_no_tmp_files(tmp_path):
    f = tmp_path / "runs.json"
    for n in range(3):
        update_runs_index(f, e_(f"r{n}"), NOW)
    assert [p.name for p in tmp_path.iterdir()] == ["runs.json"]


# ------------------------------------------------------------------ atomic_write_json

def test_atomic_write_creates_parents_and_formats(tmp_path):
    f = tmp_path / "a" / "b" / "x.json"
    atomic_write_json(f, {"k": "é"})
    text = f.read_text(encoding="utf-8")
    assert "é" in text and text.endswith("\n") and json.loads(text) == {"k": "é"}


def test_atomic_write_overwrites(tmp_path):
    f = tmp_path / "x.json"
    atomic_write_json(f, {"a": 1})
    atomic_write_json(f, {"a": 2})
    assert json.loads(f.read_text()) == {"a": 2}


def test_atomic_write_failure_keeps_old_file_and_no_tmp(tmp_path):
    f = tmp_path / "x.json"
    atomic_write_json(f, {"a": 1})
    with pytest.raises(TypeError):
        atomic_write_json(f, {"a": object()})
    assert json.loads(f.read_text()) == {"a": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["x.json"]


def test_atomic_write_failure_on_new_file_leaves_nothing(tmp_path):
    with pytest.raises(TypeError):
        atomic_write_json(tmp_path / "n.json", {"a": {1, 2}})
    assert list(tmp_path.iterdir()) == []


def test_atomic_write_replace_failure_cleans_tmp(tmp_path, monkeypatch):
    f = tmp_path / "x.json"
    atomic_write_json(f, {"a": 1})

    def boom(*a, **k):
        raise OSError("nope")
    monkeypatch.setattr(artifacts.os, "replace", boom)
    with pytest.raises(OSError):
        atomic_write_json(f, {"a": 2})
    assert json.loads(f.read_text()) == {"a": 1} and [p.name for p in tmp_path.iterdir()] == ["x.json"]
