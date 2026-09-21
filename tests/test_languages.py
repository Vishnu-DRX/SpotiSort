import pytest

from src.enrichment.languages import ALIASES, CANONICAL, normalize_language


@pytest.mark.parametrize(
    "raw,expected",
    [("hi", "hindi"), ("HIN", "hindi"), ("हिन्दी", "hindi"), ("ml", "malayalam"), ("mal", "malayalam"), ("മലയാളം", "malayalam"),
     ("ta", "tamil"), ("te", "telugu"), ("kn", "kannada"), ("bn", "bengali"), ("pa", "punjabi"), ("mr", "marathi"),
     ("en", "english"), ("ja", "japanese"), ("ko", "korean"), ("es", "spanish"), ("  Hindi ", "hindi"), ("fra", "french")],
)
def test_aliases(raw, expected):
    assert normalize_language(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "klingon", 5])
def test_unknown_is_none(raw):
    assert normalize_language(raw) is None


def test_every_canonical_name_maps_to_itself_and_required_set_present():
    for name in CANONICAL:
        assert normalize_language(name) == name
    for req in "hindi malayalam tamil telugu kannada bengali punjabi marathi english japanese korean spanish".split():
        assert req in CANONICAL
    assert len(ALIASES) > len(CANONICAL)
