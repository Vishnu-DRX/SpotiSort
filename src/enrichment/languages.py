"""Canonical language names and the alias table (ISO 639-1/-3 codes, native names -> lowercase English name).

Every language value in config (`language_in`, `language_playlists`) and in enrichment is normalised through
``normalize_language`` so ``hi``, ``hin`` and ``हिन्दी`` all become ``hindi``.
"""

from __future__ import annotations

# canonical name: (iso639-1, iso639-3, native names / extra aliases)
_LANGUAGES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "hindi": ("hi", "hin", ("हिन्दी", "हिंदी")),
    "malayalam": ("ml", "mal", ("മലയാളം",)),
    "tamil": ("ta", "tam", ("தமிழ்",)),
    "telugu": ("te", "tel", ("తెలుగు",)),
    "kannada": ("kn", "kan", ("ಕನ್ನಡ",)),
    "bengali": ("bn", "ben", ("বাংলা", "bangla")),
    "punjabi": ("pa", "pan", ("ਪੰਜਾਬੀ", "panjabi")),
    "marathi": ("mr", "mar", ("मराठी",)),
    "gujarati": ("gu", "guj", ("ગુજરાતી",)),
    "urdu": ("ur", "urd", ("اردو",)),
    "odia": ("or", "ori", ("ଓଡ଼ିଆ", "oriya")),
    "assamese": ("as", "asm", ("অসমীয়া",)),
    "nepali": ("ne", "nep", ("नेपाली",)),
    "sinhala": ("si", "sin", ("සිංහල", "sinhalese")),
    "sanskrit": ("sa", "san", ("संस्कृतम्",)),
    "english": ("en", "eng", ("english (us)", "english (uk)")),
    "spanish": ("es", "spa", ("español", "espanol")),
    "portuguese": ("pt", "por", ("português", "portugues")),
    "french": ("fr", "fra", ("français", "francais", "fre")),
    "german": ("de", "deu", ("deutsch", "ger")),
    "italian": ("it", "ita", ("italiano",)),
    "dutch": ("nl", "nld", ("nederlands", "dut")),
    "swedish": ("sv", "swe", ("svenska",)),
    "norwegian": ("no", "nor", ("norsk", "nb", "nob")),
    "danish": ("da", "dan", ("dansk",)),
    "finnish": ("fi", "fin", ("suomi",)),
    "polish": ("pl", "pol", ("polski",)),
    "russian": ("ru", "rus", ("русский",)),
    "ukrainian": ("uk", "ukr", ("українська",)),
    "turkish": ("tr", "tur", ("türkçe", "turkce")),
    "greek": ("el", "ell", ("ελληνικά", "gre")),
    "arabic": ("ar", "ara", ("العربية",)),
    "persian": ("fa", "fas", ("فارسی", "farsi", "per")),
    "hebrew": ("he", "heb", ("עברית",)),
    "japanese": ("ja", "jpn", ("日本語",)),
    "korean": ("ko", "kor", ("한국어",)),
    "chinese": ("zh", "zho", ("中文", "mandarin", "cantonese", "chi")),
    "thai": ("th", "tha", ("ไทย",)),
    "vietnamese": ("vi", "vie", ("tiếng việt",)),
    "indonesian": ("id", "ind", ("bahasa indonesia",)),
    "malay": ("ms", "msa", ("bahasa melayu", "may")),
    "tagalog": ("tl", "tgl", ("filipino", "fil")),
}

ALIASES: dict[str, str] = {}
for _name, (_iso1, _iso3, _extra) in _LANGUAGES.items():
    for _alias in (_name, _iso1, _iso3, *_extra):
        ALIASES[_alias.casefold()] = _name

CANONICAL: tuple[str, ...] = tuple(_LANGUAGES)


def normalize_language(value: str | None) -> str | None:
    """Canonical lowercase English name for ``value``, or None if it is not a known language."""
    if not isinstance(value, str):
        return None
    return ALIASES.get(value.strip().casefold())
