"""Which language signals may drive rules.

Master decision (Phase 2 review, step 3): a (language, signal) pair may drive a rule only when its measured precision
is >= 90 % (from the backtest, ``logs/signal-precision.json``). ``playlist`` (the user's own ground truth) and
``script`` (deterministic Unicode) are trusted by design; ``hint`` and ``country_default`` must be *measured* good.
Signals that do not qualify are still resolved and shown (dashboard), they just cannot decide a move.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from .models import Enrichment

MIN_PRECISION = 0.90
MIN_SAMPLES = 10
TRUSTED_BY_DESIGN = frozenset({"playlist", "script"})
DEFAULT_PATH = Path("logs") / "signal-precision.json"


def load_precision(path: str | Path = DEFAULT_PATH) -> dict[str, Any] | None:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("by_signal"), dict) else None


def qualifies(language: str | None, source: str | None, precision: dict[str, Any] | None) -> bool:
    """May this (language, source) drive a rule?"""
    if not language or not source:
        return False
    if source in TRUSTED_BY_DESIGN:
        return True
    stats = ((precision or {}).get("by_signal", {}).get(source, {}) or {}).get(language)
    if not stats:
        return False
    return (stats.get("predicted") or 0) >= MIN_SAMPLES and (stats.get("precision") or 0.0) >= MIN_PRECISION


def qualified_map(precision: dict[str, Any] | None) -> dict[str, list[str]]:
    """{language: [sources that qualify]} for reporting."""
    langs: set[str] = set()
    for per_lang in ((precision or {}).get("by_signal") or {}).values():
        langs.update(per_lang)
    out: dict[str, list[str]] = {}
    for lang in sorted(langs):
        ok = [s for s in ("playlist", "script", "hint", "country_default") if qualifies(lang, s, precision)]
        out[lang] = ok
    return out


def gate(enrichment: Enrichment | None, precision: dict[str, Any] | None) -> tuple[Enrichment | None, dict[str, Any] | None]:
    """(enrichment safe for rule matching, blocked-info or None).

    A non-qualifying language is removed from the copy used for matching; the info says what was withheld and why.
    """
    if enrichment is None or not enrichment.language:
        return enrichment, None
    if qualifies(enrichment.language, enrichment.language_source, precision):
        return enrichment, None
    stats = (((precision or {}).get("by_signal") or {}).get(enrichment.language_source or "", {}) or {}).get(enrichment.language)
    info = {
        "language": enrichment.language,
        "source": enrichment.language_source,
        "precision": stats.get("precision") if stats else None,
        "samples": stats.get("predicted") if stats else 0,
        "reason": "unmeasured" if not stats else "below_90_percent",
    }
    return replace(enrichment, language=None, language_source=None, language_confidence=None), info
