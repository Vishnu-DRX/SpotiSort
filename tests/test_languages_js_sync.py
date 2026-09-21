"""docs/builder/languages.js must be regenerated whenever src/enrichment/languages.py changes."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _gen():
    spec = importlib.util.spec_from_file_location("gen_languages_js", ROOT / "scripts" / "gen_languages_js.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_languages_js_is_up_to_date():
    gen = _gen()
    current = (ROOT / "docs" / "builder" / "languages.js").read_bytes().decode("utf-8").replace("\r\n", "\n")
    assert current == gen.render(), "run: python scripts/gen_languages_js.py"


def test_languages_js_covers_every_alias():
    from src.enrichment.languages import ALIASES

    text = (ROOT / "docs" / "builder" / "languages.js").read_text(encoding="utf-8")
    for alias, canonical in ALIASES.items():
        assert f'"{alias}": "{canonical}"' in text
