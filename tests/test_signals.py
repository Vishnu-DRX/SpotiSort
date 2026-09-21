"""Unit tests for src/signals.py (precision gate for language signals)."""

from __future__ import annotations

import json

import pytest

from src.models import Enrichment
from src.signals import MIN_PRECISION, MIN_SAMPLES, gate, load_precision, qualified_map, qualifies


def prec(**by_signal):
    return {"by_signal": by_signal}


def st(predicted, precision):
    return {"predicted": predicted, "precision": precision}


GOOD = prec(hint={"tamil": st(20, 0.95)}, country_default={"english": st(50, 0.92)})


def test_constants():
    assert MIN_PRECISION == 0.90 and MIN_SAMPLES == 10


@pytest.mark.parametrize("source", ["playlist", "script"])
def test_trusted_by_design_without_any_data(source):
    assert qualifies("hindi", source, None)
    assert qualifies("hindi", source, {})
    assert qualifies("hindi", source, prec(**{source: {"hindi": st(1, 0.0)}}))


@pytest.mark.parametrize("lang,source", [(None, "playlist"), ("", "script"), ("hindi", None), ("hindi", "")])
def test_missing_language_or_source_never_qualifies(lang, source):
    assert not qualifies(lang, source, GOOD)


def test_hint_qualifies_when_measured_well():
    assert qualifies("tamil", "hint", GOOD)
    assert qualifies("english", "country_default", GOOD)


@pytest.mark.parametrize("p,ok", [(0.90, True), (0.9001, True), (0.8999, False), (0.0, False), (1.0, True)])
def test_precision_boundary(p, ok):
    assert qualifies("tamil", "hint", prec(hint={"tamil": st(20, p)})) is ok


@pytest.mark.parametrize("n,ok", [(10, True), (11, True), (9, False), (0, False)])
def test_min_samples_boundary(n, ok):
    assert qualifies("tamil", "hint", prec(hint={"tamil": st(n, 1.0)})) is ok


def test_none_precision_not_qualified():
    # precision may be None when nothing predicted; must not raise
    assert not qualifies("tamil", "hint", prec(hint={"tamil": {"predicted": 20, "precision": None}}))


def test_unmeasured_not_qualified():
    assert not qualifies("tamil", "hint", None)
    assert not qualifies("tamil", "hint", {})
    assert not qualifies("tamil", "hint", prec(hint={}))
    assert not qualifies("korean", "hint", GOOD)
    assert not qualifies("tamil", "country_default", GOOD)
    assert not qualifies("tamil", "hint", prec(hint={"tamil": {}}))


def test_unknown_source_not_qualified():
    assert not qualifies("tamil", "mystery", GOOD)


def test_qualified_map_empty():
    assert qualified_map(None) == {}
    assert qualified_map({}) == {}
    assert qualified_map(prec()) == {}


def test_qualified_map_lists_sources_in_fixed_order():
    p = prec(country_default={"tamil": st(20, 0.95)}, hint={"tamil": st(20, 0.95), "korean": st(20, 0.5)})
    assert qualified_map(p) == {"korean": ["playlist", "script"], "tamil": ["playlist", "script", "hint", "country_default"]}


def test_qualified_map_sorted_languages():
    p = prec(hint={"zulu": st(20, 1.0), "arabic": st(20, 1.0)})
    assert list(qualified_map(p)) == ["arabic", "zulu"]


# ------------------------------------------------------------------ gate

def enr(language, source, conf=0.6):
    return Enrichment(genres=("jazz",), language=language, sources=("x",), language_source=source, language_confidence=conf)


def test_gate_none_enrichment():
    assert gate(None, None) == (None, None)


def test_gate_no_language_passes_through():
    e = Enrichment(genres=("jazz",))
    assert gate(e, None) == (e, None)


@pytest.mark.parametrize("source", ["playlist", "script"])
def test_gate_trusted_pass_without_precision_file(source):
    e = enr("hindi", source)
    assert gate(e, None) == (e, None)


@pytest.mark.parametrize("source", ["hint", "country_default"])
def test_gate_weak_blocked_without_precision_file(source):
    e = enr("hindi", source)
    out, info = gate(e, None)
    assert out.language is None and out.language_source is None and out.language_confidence is None
    assert info == {"language": "hindi", "source": source, "precision": None, "samples": 0, "reason": "unmeasured"}


def test_gate_keeps_genres_and_other_fields_when_withholding():
    e = enr("hindi", "hint")
    out, _ = gate(e, None)
    assert out.genres == ("jazz",) and out.sources == ("x",)
    assert e.language == "hindi"  # original untouched


def test_gate_below_90_reports_stats():
    p = prec(hint={"tamil": st(40, 0.85)})
    out, info = gate(enr("tamil", "hint"), p)
    assert out.language is None
    assert info["reason"] == "below_90_percent" and info["precision"] == 0.85 and info["samples"] == 40


def test_gate_high_precision_but_too_few_samples_is_below_90_reason():
    p = prec(hint={"tamil": st(3, 1.0)})
    out, info = gate(enr("tamil", "hint"), p)
    assert out.language is None and info["reason"] == "below_90_percent" and info["samples"] == 3


def test_gate_qualified_hint_passes():
    e = enr("tamil", "hint")
    assert gate(e, GOOD) == (e, None)


def test_gate_language_measured_for_other_source_only():
    out, info = gate(enr("tamil", "country_default"), GOOD)
    assert out.language is None and info["reason"] == "unmeasured"


def test_gate_language_without_source_is_blocked():
    out, info = gate(enr("tamil", None), GOOD)
    assert out.language is None and info["reason"] == "unmeasured" and info["source"] is None


# ------------------------------------------------------------------ load_precision

def test_load_precision_missing_file(tmp_path):
    assert load_precision(tmp_path / "nope.json") is None


def test_load_precision_corrupt_and_wrong_shape(tmp_path):
    f = tmp_path / "p.json"
    f.write_text("{not json", encoding="utf-8")
    assert load_precision(f) is None
    f.write_text("[1,2]", encoding="utf-8")
    assert load_precision(f) is None
    f.write_text('{"by_signal": 3}', encoding="utf-8")
    assert load_precision(f) is None


def test_load_precision_ok(tmp_path):
    f = tmp_path / "p.json"
    f.write_text(json.dumps(GOOD), encoding="utf-8")
    assert load_precision(f) == GOOD
