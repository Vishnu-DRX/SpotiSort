import pytest

from src.enrichment.isrc_country import (
    ISRC_PREFIX_COUNTRY,
    isrc_country,
    language_hint_from_country,
)
from src.enrichment.languages import CANONICAL


@pytest.mark.parametrize(
    "isrc, expected",
    [
        ("USRC17607839", "US"),
        ("usrc17607839", "US"),
        ("US-S1Z-99-00001", "US"),
        ("US S1Z 99 00001", "US"),
        (" GBAYE0601498 ", "GB"),  # surrounding whitespace stripped
        ("GBAYE06014988", None),  # 13 chars -> invalid
        ("GBAYE0601498", "GB"),
        ("QMJMT1900123", "US"),
        ("QZAB01900001", "US"),
        ("FRZ039900001", "FR"),
        ("DEUM71900001", "DE"),
        ("JPPC09900001", "JP"),
        ("KRA381900001", "KR"),
        ("INU101900001", "IN"),
        ("AUAB01900001", "AU"),
        ("BRBMG1900001", "BR"),
        ("UKAB01900001", "GB"),
        ("ZZAB01900001", None),  # unknown prefix
        ("USRC1760783", None),  # too short
        ("USRC176078399", None),  # too long
        ("US!C17607839", None),  # punctuation
        ("12RC17607839", None),  # digits in country part
        ("", None),
        (None, None),
        (123456789012, None),
    ],
)
def test_isrc_country(isrc, expected):
    assert isrc_country(isrc) == expected


def test_table_values_are_uppercase_alpha2():
    assert all(len(v) == 2 and v.isupper() for v in ISRC_PREFIX_COUNTRY.values())


@pytest.mark.parametrize(
    "country, expected",
    [
        ("JP", "japanese"),
        ("jp", "japanese"),
        ("KR", "korean"),
        ("FR", "french"),
        ("DE", "german"),
        ("ES", "spanish"),
        ("IT", "italian"),
        ("BR", "portuguese"),
        ("RU", "russian"),
        ("IN", None),  # ambiguous
        ("US", None),
        ("GB", None),
        ("XX", None),
        (None, None),
    ],
)
def test_language_hint(country, expected):
    assert language_hint_from_country(country) == expected


def test_hints_are_canonical_languages():
    from src.enrichment import isrc_country as mod

    for lang in mod._COUNTRY_LANGUAGE.values():
        assert lang in CANONICAL
    for country in mod._COUNTRY_LANGUAGE:
        assert country in ISRC_PREFIX_COUNTRY.values()
