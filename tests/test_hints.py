"""Unit tests for src/enrichment/hints.py (fabricated tags, no I/O)."""

from __future__ import annotations

import pytest

from src.enrichment.hints import language_from_tags, language_hint


@pytest.mark.parametrize("tag,lang", [
    ("bollywood", "hindi"), ("mollywood", "malayalam"), ("kollywood", "tamil"), ("tollywood", "telugu"),
    ("sandalwood", "kannada"), ("bhangra", "punjabi"), ("j-pop", "japanese"), ("jpop", "japanese"),
    ("anime", "japanese"), ("city pop", "japanese"), ("k-pop", "korean"), ("kpop", "korean"),
    ("mandopop", "chinese"), ("cantopop", "chinese"), ("c-pop", "chinese"),
    ("flamenco", "spanish"), ("reggaeton", "spanish"),
])
def test_scene_tag_table(tag, lang):
    assert language_from_tags([tag]) == lang


@pytest.mark.parametrize("tag,lang", [
    ("hindi", "hindi"), ("Tamil", "tamil"), ("french", "french"), ("German", "german"),
    ("hindi pop", "hindi"), ("classic italian songs", "italian"), ("  SPANISH  ", "spanish"),
])
def test_canonical_names_in_tags(tag, lang):
    assert language_from_tags([tag]) == lang


@pytest.mark.parametrize("tags", [[], ["rock"], ["desi"], ["latin"], ["pop", "jazz"], [""], ["   "]])
def test_unknown_or_ambiguous_tags_give_none(tags):
    assert language_from_tags(tags) is None


def test_majority_of_votes_wins():
    assert language_from_tags(["bollywood", "tamil", "kollywood"]) == "tamil"


def test_tag_case_and_whitespace_normalised():
    assert language_from_tags(["  BOLLYWOOD "]) == "hindi"


def test_accepts_generator():
    assert language_from_tags(t for t in ["k-pop"]) == "korean"


def test_tie_prefers_first_seen():
    assert language_from_tags(["bollywood", "kpop"]) == "hindi"


def test_language_hint_tags_first():
    assert language_hint(["k-pop"], "JP") == ("korean", "tag")


def test_language_hint_country_fallback():
    assert language_hint(["rock"], "JP") == ("japanese", "country")
    assert language_hint([], "FR") == ("french", "country")


def test_language_hint_in_is_ambiguous():
    assert language_hint([], "IN") is None
    assert language_hint(["rock"], "IN") is None


def test_language_hint_unknown():
    assert language_hint([], None) is None
    assert language_hint(["rock"], "ZZ") is None
    assert language_hint([], "US") is None


def test_language_hint_in_with_tag_uses_tag():
    assert language_hint(["mollywood"], "IN") == ("malayalam", "tag")
