"""Language hints from MusicBrainz artist tags and area (tier between script and country_default).

Weaker than script (a tag can describe a scene, not the singing language) but stronger than a bare country
default. Whether a hint may *drive a rule* is decided by measured per-language precision (see backtest).
"""

from __future__ import annotations

import re
from typing import Iterable

from .isrc_country import language_hint_from_country
from .languages import CANONICAL

# scene/genre tags that name a language without spelling it
_TAG_TO_LANGUAGE = {
    "bollywood": "hindi", "hindi": "hindi", "desi": None,
    "mollywood": "malayalam", "malayalam": "malayalam",
    "kollywood": "tamil", "tamil": "tamil",
    "tollywood": "telugu", "telugu": "telugu",
    "sandalwood": "kannada", "kannada": "kannada",
    "punjabi": "punjabi", "bhangra": "punjabi",
    "bengali": "bengali", "marathi": "marathi", "gujarati": "gujarati",
    "j-pop": "japanese", "jpop": "japanese", "j-rock": "japanese", "anime": "japanese", "city pop": "japanese", "japanese": "japanese",
    "k-pop": "korean", "kpop": "korean", "k-rock": "korean", "korean": "korean",
    "mandopop": "chinese", "cantopop": "chinese", "c-pop": "chinese",
    "flamenco": "spanish", "reggaeton": "spanish", "latin": None,
}
_WORD = re.compile(r"[a-z]+")


def language_from_tags(tags: Iterable[str]) -> str | None:
    """The language most named by the tags (scene tags and literal language names)."""
    votes: dict[str, int] = {}
    for tag in tags:
        t = tag.strip().lower()
        lang = _TAG_TO_LANGUAGE.get(t)
        if lang is None:
            words = _WORD.findall(t)
            lang = next((w for w in words if w in CANONICAL), None)
        if lang:
            votes[lang] = votes.get(lang, 0) + 1
    if not votes:
        return None
    return max(votes, key=lambda k: votes[k])


def language_hint(tags: Iterable[str], country: str | None) -> tuple[str, str] | None:
    """(language, why) from tags first, then a mono-lingual artist country; None when neither says anything."""
    lang = language_from_tags(tags)
    if lang:
        return lang, "tag"
    lang = language_hint_from_country(country)
    if lang:
        return lang, "country"
    return None
