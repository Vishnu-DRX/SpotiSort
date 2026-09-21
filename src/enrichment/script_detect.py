"""Language hints from Unicode-script analysis of track / album / artist names.

Pure stdlib (``unicodedata``). Latin, digits, punctuation and emoji are ignored, so purely Latin text says
nothing and yields ``None``. Known limits (by design, script alone cannot tell these apart):

* Devanagari is shared by Hindi, Marathi, Nepali, Sanskrit -> ``hindi`` by default (``devanagari_default``).
* Arabic script is shared by Arabic, Urdu, Persian -> ``arabic``.
* Bengali script also covers Assamese -> ``bengali``.
* Han-only text is treated as ``chinese``; any kana makes it ``japanese``; Hangul (no kana) makes it ``korean``.
* Greek letters used as symbols (e.g. an artist called "Δ") will read as ``greek``.
"""

from __future__ import annotations

import unicodedata
from collections import Counter

# unicodedata.name() prefix -> script id. Longer/more specific prefixes first.
_PREFIXES: tuple[tuple[str, str], ...] = (
    ("DEVANAGARI", "devanagari"),
    ("MALAYALAM", "malayalam"),
    ("TAMIL", "tamil"),
    ("TELUGU", "telugu"),
    ("KANNADA", "kannada"),
    ("BENGALI", "bengali"),
    ("GURMUKHI", "gurmukhi"),
    ("GUJARATI", "gujarati"),
    ("ORIYA", "oriya"),
    ("SINHALA", "sinhala"),
    ("HIRAGANA", "kana"),
    ("KATAKANA", "kana"),
    ("HANGUL", "hangul"),
    ("CJK", "han"),
    ("CYRILLIC", "cyrillic"),
    ("ARABIC", "arabic"),
    ("HEBREW", "hebrew"),
    ("THAI", "thai"),
    ("GREEK", "greek"),
)

_SCRIPT_TO_LANGUAGE: dict[str, str] = {
    "malayalam": "malayalam",
    "tamil": "tamil",
    "telugu": "telugu",
    "kannada": "kannada",
    "bengali": "bengali",
    "gurmukhi": "punjabi",
    "gujarati": "gujarati",
    "oriya": "odia",
    "sinhala": "sinhala",
    "kana": "japanese",
    "hangul": "korean",
    "han": "chinese",
    "cyrillic": "russian",
    "arabic": "arabic",
    "hebrew": "hebrew",
    "thai": "thai",
    "greek": "greek",
}


def _script_of(ch: str) -> str | None:
    """Script id of a letter/mark character, or None for Latin, digits, punctuation, emoji, etc."""
    cat = unicodedata.category(ch)
    if cat[0] not in ("L", "M"):  # letters, plus combining marks (Indic vowel signs)
        return None
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return None
    if name.startswith("HALFWIDTH "):
        name = name[len("HALFWIDTH "):]
    for prefix, script in _PREFIXES:
        if name.startswith(prefix):
            return script
    return None


def _count(texts: tuple[str | None, ...]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for text in texts:
        if not isinstance(text, str):
            continue
        for ch in text:
            script = _script_of(ch)
            if script:
                counts[script] += 1
    # Japanese text mixes kanji with kana; Korean mixes hanja with Hangul. Fold Han into them.
    if counts.get("kana"):
        counts["kana"] += counts.pop("han", 0)
    elif counts.get("hangul"):
        counts["hangul"] += counts.pop("han", 0)
    return counts


def dominant_script(*texts: str | None) -> str | None:
    """Dominant non-Latin script id across ``texts`` (combined letter counts), or None if there is none.

    Ids: devanagari, malayalam, tamil, telugu, kannada, bengali, gurmukhi, gujarati, oriya, sinhala,
    kana (hiragana/katakana, also wins over Han), hangul, han, cyrillic, arabic, hebrew, thai, greek.
    Ties are broken by first-seen order of the script in the text.
    """
    counts = _count(texts)
    if not counts:
        return None
    # Any kana at all means Japanese, even when Han characters outnumber it.
    if counts.get("kana"):
        return "kana"
    return max(counts, key=lambda s: counts[s])  # Counter preserves insertion order -> stable ties


def detect_script_language(*texts: str | None, devanagari_default: str = "hindi") -> str | None:
    """Canonical language name implied by the scripts in ``texts``, or None (pure Latin / nothing).

    Letters are counted across all arguments together. Devanagari cannot separate Hindi from Marathi
    (or Nepali), so ``devanagari_default`` (``"hindi"``) is returned for it.
    """
    script = dominant_script(*texts)
    if script is None:
        return None
    if script == "devanagari":
        return devanagari_default
    return _SCRIPT_TO_LANGUAGE[script]
