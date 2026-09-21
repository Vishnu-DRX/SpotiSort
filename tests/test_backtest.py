"""Unit + offline end-to-end tests for src/backtest.py using fabricated data (fake client, tmp output only)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src import backtest
from src.models import Artist, Config, Enrichment, Playlist, Rule, Track

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def trk(n, artist="Xylophonia", name=None, age=30, **kw):
    base = dict(id=f"t{n}", uri=f"spotify:track:t{n}", name=name or f"Zanzibar Song {n}",
                artists=(Artist(f"a-{artist}", artist),), album_name="Album", release_date="2005-06-01",
                release_date_precision="day", added_at=None if age is None else NOW - timedelta(days=age))
    base.update(kw)
    return Track(**base)


def pl(name, id, owned=True):
    return Playlist(id=id, name=name, owner_id="me" if owned else "o", owned=owned, collaborative=False)


# ------------------------------------------------------------------ signal_precision

def test_signal_precision_hand_computed():
    truth = {"t1": "hindi", "t2": "hindi", "t3": "tamil"}
    cands = {
        "t1": {"hint": "hindi", "script": "hindi"},
        "t2": {"hint": "tamil", "script": None},
        "t3": {"hint": "tamil"},
        "t9": {"hint": "hindi"},  # not in truth: ignored
    }
    out = backtest.signal_precision(cands, truth)
    assert set(out) == {"playlist", "script", "hint", "country_default"}
    assert out["hint"]["hindi"] == {"truth": 2, "predicted": 1, "correct": 1, "precision": 1.0, "recall": 0.5}
    assert out["hint"]["tamil"] == {"truth": 1, "predicted": 2, "correct": 1, "precision": 0.5, "recall": 1.0}
    assert out["script"]["hindi"] == {"truth": 2, "predicted": 1, "correct": 1, "precision": 1.0, "recall": 0.5}
    assert out["script"]["tamil"] == {"truth": 1, "predicted": 0, "correct": 0, "precision": None, "recall": 0.0}
    assert out["playlist"]["hindi"]["predicted"] == 0 and out["playlist"]["hindi"]["precision"] is None


def test_signal_precision_predicted_language_without_truth():
    out = backtest.signal_precision({"t1": {"hint": "korean"}}, {"t1": "hindi"})
    assert out["hint"]["korean"] == {"truth": 0, "predicted": 1, "correct": 0, "precision": 0.0, "recall": None}
    assert out["hint"]["hindi"]["recall"] == 0.0


def test_signal_precision_empty():
    out = backtest.signal_precision({}, {})
    assert out == {s: {} for s in backtest.SIGNALS}


def test_signal_precision_rounding():
    truth = {f"t{i}": "hindi" for i in range(3)}
    cands = {"t0": {"hint": "hindi"}, "t1": {"hint": "hindi"}, "t2": {"hint": "tamil"}}
    assert backtest.signal_precision(cands, truth)["hint"]["hindi"]["precision"] == 1.0
    assert backtest.signal_precision(cands, truth)["hint"]["hindi"]["recall"] == round(2 / 3, 4)


def test_build_signal_report_qualified():
    prec = backtest.signal_precision(
        {f"t{i}": {"hint": "hindi"} for i in range(12)}, {f"t{i}": "hindi" for i in range(12)})
    doc = backtest.build_signal_report(prec, NOW)
    assert doc["version"] == 1 and doc["min_precision"] == 0.9 and doc["min_samples"] == 10
    assert doc["trusted_by_design"] == ["playlist", "script"] and doc["by_signal"] is prec
    assert doc["qualified"]["hindi"] == ["playlist", "script", "hint"]
    json.dumps(doc)


# ------------------------------------------------------------------ routing_metrics

RULES = (
    Rule("r1", "Alpha", {"artist_in": ["X"]}),
    Rule("r2", "Beta", {"artist_in": ["Y"]}),
    Rule("r3", "Nowhere", {"artist_in": ["Z"]}),
)
CFG = Config(rules=RULES)
PLS = [pl("Alpha", "pa"), pl("Beta", "pb")]


def routing_fixture():
    tracks = [
        trk(1, "X"),               # home pa: correct
        trk(2, "X"),               # home pb: misrouted to pa
        trk(3, "Y"),               # homes pa,pb: correct (multi-home)
        trk(4, "W"),               # no rule; home pa: unrouted
        trk(5, "Z"),               # rule with unresolved target; home pb: unrouted
        trk(6, "X", age=0),        # brand new: age ignored; homes pa,pb: correct
    ]
    truth = {"t1": {"pa"}, "t2": {"pb"}, "t3": {"pa", "pb"}, "t4": {"pa"}, "t5": {"pb"}, "t6": {"pa", "pb"}}
    return tracks, truth


def test_routing_metrics_hand_computed():
    tracks, truth = routing_fixture()
    m = backtest.routing_metrics(tracks, truth, {}, CFG, PLS, NOW)
    assert (m["routed"], m["correct"], m["unrouted"]) == (4, 3, 2)
    assert dict(m["pred_by_pl"]) == {"pa": 3, "pb": 1}
    assert dict(m["tp_by_pl"]) == {"pa": 2, "pb": 1}
    assert dict(m["truth_by_pl"]) == {"pa": 4, "pb": 4}
    assert dict(m["unrouted_by_pl"]) == {"pa": 1, "pb": 1}
    assert dict(m["confusion"]) == {("pb", "pa"): 1}
    assert dict(m["rule_pred"]) == {"r1": 3, "r2": 1}
    assert dict(m["rule_ok"]) == {"r1": 2, "r2": 1}
    assert len(m["misroutes"]) == 1 and m["misroutes"][0]["track"].id == "t2"
    assert m["misroutes"][0]["predicted"] == "pa" and m["misroutes"][0]["homes"] == ["pb"] and m["misroutes"][0]["rule"] == "r1"


def test_routing_age_ignored():
    m = backtest.routing_metrics([trk(1, "X", age=0), trk(2, "X", age=None)], {"t1": {"pa"}, "t2": {"pa"}}, {}, CFG, PLS, NOW)
    assert m["routed"] == 2 and m["correct"] == 2


def test_routing_unresolved_target_counts_as_unrouted():
    m = backtest.routing_metrics([trk(1, "Z")], {"t1": {"pa"}}, {}, CFG, PLS, NOW)
    assert m["unrouted"] == 1 and m["routed"] == 0 and m["rule_pred"]["r3"] == 0


def test_routing_ambiguous_and_followed_targets_unrouted():
    cfg = Config(rules=(Rule("d", "Dup", {"artist_in": ["X"]}), Rule("f", "Fol", {"artist_in": ["Y"]})))
    pls = [pl("Dup", "d1"), pl("Dup", "d2"), pl("Fol", "f1", owned=False)]
    m = backtest.routing_metrics([trk(1, "X"), trk(2, "Y")], {}, {}, cfg, pls, NOW)
    assert m["unrouted"] == 2


def test_routing_track_without_truth():
    m = backtest.routing_metrics([trk(1, "X")], {}, {}, CFG, PLS, NOW)
    assert m["routed"] == 1 and m["correct"] == 0 and len(m["misroutes"]) == 1 and m["misroutes"][0]["homes"] == []
    assert not m["confusion"]


def test_routing_multi_home_misroute_records_every_confusion():
    m = backtest.routing_metrics([trk(1, "Y")], {"t1": {"pa", "pc"}}, {}, CFG, PLS, NOW)
    assert dict(m["confusion"]) == {("pa", "pb"): 1, ("pc", "pb"): 1}


def test_routing_uses_enrichment_and_disabled_rules_skipped():
    cfg = Config(rules=(Rule("off", "Alpha", {"artist_in": ["X"]}, enabled=False), Rule("hi", "Beta", {"language_in": ["hindi"]})))
    enr = {"t1": Enrichment(language="hindi", language_source="script")}
    m = backtest.routing_metrics([trk(1, "X")], {"t1": {"pb"}}, enr, cfg, PLS, NOW)
    assert m["correct"] == 1 and dict(m["rule_ok"]) == {"hi": 1}


def test_routing_empty():
    m = backtest.routing_metrics([], {}, {}, CFG, PLS, NOW)
    assert (m["routed"], m["correct"], m["unrouted"]) == (0, 0, 0) and m["misroutes"] == []


# ------------------------------------------------------------------ build_reports

def make_reports(names=None, cfg=CFG):
    tracks, truth = routing_fixture()
    names = names or {"pa": "Alpha Secretname", "pb": "Beta Secretname"}
    cfg = Config(rules=(Rule("rule-secret-one", "Alpha Secretname", {"artist_in": ["X"]}),
                        Rule("rule-secret-two", "Beta Secretname", {"artist_in": ["Y"]}),
                        Rule("rule-secret-three", "Nowhere", {"artist_in": ["Z"]})))
    pls = [pl("Alpha Secretname", "pa"), pl("Beta Secretname", "pb")]
    m = backtest.routing_metrics(tracks, truth, {}, cfg, pls, NOW)
    prec = backtest.signal_precision({}, {})
    rep, det = backtest.build_reports(tracks=tracks, truth=truth, playlists=pls, names=names, config=cfg, metrics=m,
                                      precision=prec, all_rules_enabled=False, cfg_hash="abc123", now=NOW)
    return rep, det, tracks


def test_counts_only_report_has_no_names():
    rep, det, tracks = make_reports()
    text = json.dumps(rep)
    forbidden = ["Secretname", "Alpha", "Beta", "rule-secret", "Xylophonia", "Zanzibar", "Nowhere"]
    forbidden += [t.name for t in tracks] + [a.name for t in tracks for a in t.artists] + [t.id for t in tracks]
    for f in forbidden:
        assert f not in text, f
    assert "top_misroutes" not in rep


def test_detail_report_has_names():
    _, det, _ = make_reports()
    text = json.dumps(det)
    for f in ("Alpha Secretname", "Beta Secretname", "rule-secret-one", "Zanzibar Song 2"):
        assert f in text
    mis = det["top_misroutes"]
    assert len(mis) == 1 and mis[0]["true"] == ["Beta Secretname"] and mis[0]["predicted"] == "Alpha Secretname"
    assert mis[0]["rule"] == "rule-secret-one" and mis[0]["artists"] == ["X"]
    assert det["confusions"] == [{"true": "Beta Secretname", "predicted": "Alpha Secretname", "count": 1}]
    assert [p["name"] for p in det["playlists"]] == ["Alpha Secretname", "Beta Secretname"]
    assert [r["name"] for r in det["rules"]] == ["rule-secret-one", "rule-secret-two", "rule-secret-three"]


def test_report_labels_stable_and_totals():
    rep, det, _ = make_reports()
    assert [p["id"] for p in rep["playlists"]] == ["P01", "P02"]
    assert [r["name_id"] for r in rep["rules"]] == ["R01", "R02", "R03"]
    assert rep["confusions"] == [{"true": "P02", "predicted": "P01", "count": 1}]
    assert rep["totals"] == {"tracks": 6, "routed": 4, "correct": 3, "misrouted": 1, "unrouted": 2, "precision": 0.75, "recall": 0.5}
    assert rep["playlists"][0] == {"id": "P01", "tracks": 4, "predicted": 3, "tp": 2, "precision": round(2 / 3, 4), "recall": 0.5, "unrouted": 1}
    assert rep["rules"][2] == {"name_id": "R03", "predicted": 0, "correct": 0, "precision": None}
    assert rep["inbox"] == {"tracks": 6, "playlists": 2} and rep["config_hash"] == "abc123" and rep["all_rules_enabled"] is False
    assert rep["version"] == 1 and rep["generated_at"] == "2026-09-21T12:00:00+00:00" and rep["caveats"]


def test_labels_ordered_by_casefolded_name_not_id():
    rep, det, _ = make_reports(names={"pa": "zeta", "pb": "Alpha"})
    assert [p["name"] for p in det["playlists"]] == ["Alpha", "zeta"]
    assert rep["playlists"][0]["tracks"] == 4  # pb (Alpha) is P01
    assert rep["confusions"] == [{"true": "P01", "predicted": "P02", "count": 1}]


def test_reports_deterministic():
    a, b = make_reports()[0], make_reports()[0]
    assert a == b


def test_reports_json_serialisable():
    rep, det, _ = make_reports()
    json.dumps(rep)
    json.dumps(det)


def test_render_markdown_smoke():
    rep, det, _ = make_reports()
    sig = backtest.build_signal_report(backtest.signal_precision(
        {"t1": {"hint": "hindi"}}, {"t1": "hindi"}), NOW)
    md = backtest.render_markdown(det, sig)
    assert md.startswith("# Backtest detail") and md.endswith("\n")
    for s in ("## Per playlist", "## Per rule", "## Top confusions", "## Sample misroutes", "Alpha Secretname", "rule-secret-one",
              "Zanzibar Song 2", "hint/hindi", "routed 4"):
        assert s in md


# ------------------------------------------------------------------ end-to-end main()

CONFIG_YAML = """\
default_days_threshold: 14
language_playlists:
  "Hindi Faves": hindi
rules:
  - name: hindi-rule
    match:
      language_in: ["hindi"]
    target_playlist: Hindi Faves
  - name: chill-rule
    match:
      artist_in: ["Xylophonia"]
    target_playlist: Chill Bucket
"""

H1 = trk(101, "Qwertyband", name="प्यार का गीत")
H2 = trk(102, "Qwertyband", name="दिल की बात")
H3 = trk(103, "Qwertyband", name="इश्क़ है")
C1 = trk(104, "Xylophonia", name="Zanzibar Nights")
C2 = trk(105, "Xylophonia", name="Zanzibar Dawn")
SEEDS = {"hf1": [H1, H2, H3], "ch1": [C1, C2], "tst": [C1], "fol": [C2]}


class FakeClient:
    instances: list = []
    playlists = [pl("Hindi Faves", "hf1"), pl("Chill Bucket", "ch1"), pl("SpotiSort Test", "tst"),
                 pl("Others Mix", "fol", owned=False), pl("Empty One", "emp")]

    def __init__(self, dry_run):
        self.dry_run = dry_run
        FakeClient.instances.append(self)

    @classmethod
    def from_env(cls, dry_run=True, **kw):
        return cls(dry_run)

    def iter_my_playlists(self):
        return iter(list(self.playlists))

    def iter_playlist_items(self, pid):
        return iter(list(SEEDS.get(pid, [])))

    def __getattr__(self, name):  # any write-ish call must never happen
        raise AssertionError(f"unexpected client call: {name}")


@pytest.fixture
def fake(monkeypatch):
    FakeClient.instances = []
    monkeypatch.setattr(backtest, "SpotifyClient", FakeClient)
    monkeypatch.setattr(backtest, "load_env", lambda *a, **k: False)


def run_main(tmp_path, *extra, config_text=CONFIG_YAML):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(config_text, encoding="utf-8")
    out = tmp_path / "out"
    rc = backtest.main(["--config", str(cfg), "--env", str(tmp_path / "none.env"), "--cache", str(tmp_path / "cache.json"),
                        "--out", str(out), "--no-network", *extra])
    return rc, out


def test_main_end_to_end_files_and_counts(fake, tmp_path, capsys):
    rc, out = run_main(tmp_path)
    assert rc == 0
    assert {p.name for p in out.iterdir()} == {"backtest.json", "signal-precision.json", "backtest-detail.json", "backtest-detail.md"}
    rep = json.loads((out / "backtest.json").read_text(encoding="utf-8"))
    # unique tracks: 3 hindi + C1 + C2 (test playlist and followed one excluded, but C1/C2 come via Chill Bucket)
    assert rep["inbox"] == {"tracks": 5, "playlists": 2}
    assert rep["totals"]["tracks"] == 5 and rep["totals"]["routed"] == 5
    assert "backtest:" in capsys.readouterr().out


def test_main_client_dry_run_and_single_client(fake, tmp_path):
    run_main(tmp_path)
    assert len(FakeClient.instances) == 1 and FakeClient.instances[0].dry_run is True


def test_main_counts_only_files_have_no_names(fake, tmp_path):
    _, out = run_main(tmp_path)
    forbidden = ["Hindi Faves", "Chill Bucket", "Xylophonia", "Qwertyband", "Zanzibar", "प्यार", "hindi-rule", "chill-rule",
                 "spotify:track", "SpotiSort Test"]
    for fname in ("backtest.json", "signal-precision.json"):
        text = (out / fname).read_text(encoding="utf-8")
        for f in forbidden:
            assert f not in text, (fname, f)


def test_main_detail_files_have_names(fake, tmp_path):
    _, out = run_main(tmp_path)
    detail = (out / "backtest-detail.json").read_text(encoding="utf-8")
    assert "Hindi Faves" in detail and "Chill Bucket" in detail and "hindi-rule" in detail
    md = (out / "backtest-detail.md").read_text(encoding="utf-8")
    assert "Hindi Faves" in md and md.startswith("# Backtest detail")


def test_main_signal_precision_measures_script_and_playlist(fake, tmp_path):
    _, out = run_main(tmp_path)
    sig = json.loads((out / "signal-precision.json").read_text(encoding="utf-8"))
    assert sig["trusted_by_design"] == ["playlist", "script"]
    script = sig["by_signal"]["script"]["hindi"]
    assert script["truth"] == 3 and script["predicted"] == 3 and script["correct"] == 3 and script["precision"] == 1.0
    # leave-one-out: artist has only these 3 tracks, so removing own votes leaves 2 votes for the same artist => hindi
    assert sig["by_signal"]["playlist"]["hindi"]["predicted"] == 3
    assert "hindi" in sig["qualified"] and "script" in sig["qualified"]["hindi"]


def test_main_routing_totals(fake, tmp_path):
    _, out = run_main(tmp_path)
    rep = json.loads((out / "backtest.json").read_text(encoding="utf-8"))
    assert rep["totals"]["correct"] == 5 and rep["totals"]["misrouted"] == 0 and rep["totals"]["precision"] == 1.0
    assert [r["predicted"] for r in rep["rules"]] == [3, 2]


def test_main_all_rules_flag(fake, tmp_path):
    cfg = CONFIG_YAML.replace("  - name: chill-rule\n", "  - name: chill-rule\n    enabled: false\n")
    _, out = run_main(tmp_path, config_text=cfg)
    assert json.loads((out / "backtest.json").read_text())["totals"]["routed"] == 3
    FakeClient.instances = []
    _, out2 = run_main(tmp_path, "--all-rules", config_text=cfg)
    r = json.loads((out2 / "backtest.json").read_text())
    assert r["totals"]["routed"] == 5 and r["all_rules_enabled"] is True


def test_main_bad_config_returns_1(fake, tmp_path, capsys):
    rc, out = run_main(tmp_path, config_text="rules: 5\n")
    assert rc == 1 and not out.exists()
    assert "error" in capsys.readouterr().err


def test_main_missing_config_returns_1(fake, tmp_path):
    rc = backtest.main(["--config", str(tmp_path / "nope.yaml"), "--out", str(tmp_path / "o")])
    assert rc == 1


def test_main_leaves_no_tmp_files(fake, tmp_path):
    _, out = run_main(tmp_path)
    assert not [p for p in out.iterdir() if p.name.startswith(".tmp-")]
