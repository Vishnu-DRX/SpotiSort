"""Browser tests for the Pages config builder (docs/builder). Run: python -m pytest tests/e2e -q -m e2e"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect  # noqa: E402

from src.config import ConfigError, parse_config  # noqa: E402
from src.enrichment.languages import ALIASES, normalize_language  # noqa: E402

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
SHOTS = DOCS / "screenshots"


# ------------------------------------------------------------------ helpers
def preview(page) -> str:
    return page.locator("#yaml-out code").text_content()


def preview_data(page):
    return yaml.safe_load(preview(page))


def rule(page, i):
    return page.locator("#rules > li").nth(i)


def add_rule(page, name, target):
    page.get_by_role("button", name="Add rule").click()
    r = page.locator("#rules > li").last
    r.get_by_label("Rule name").fill(name)
    r.get_by_label("Target playlist").fill(target)
    return r


def add_cond(r, key):
    r.locator("select[id$='-add-cond']").select_option(key)
    r.get_by_role("button", name="Add condition", exact=True).click()
    return r.locator(f"input[id$='-match-{key}'], select[id$='-match-{key}']")


def add_chips(r, key, *values):
    field = add_cond(r, key)
    for v in values:
        field.fill(v)
        field.press("Enter")


def download_text(page) -> str:
    with page.expect_download() as info:
        page.get_by_role("button", name="Download config.yaml").click()
    dl = info.value
    assert dl.suggested_filename == "config.yaml"
    return Path(dl.path()).read_text(encoding="utf-8")


def validated(text: str):
    """Run the REAL Python validator on builder output."""
    return parse_config(yaml.safe_load(text))


def problem_count(page) -> int:
    txt = page.locator("#status").text_content()
    return 0 if txt.startswith("Valid") else int(txt.split()[0])


# ------------------------------------------------------------------ basics
def test_page_loads_without_external_requests_or_errors(make_page, site):
    page, _ = make_page()
    requests, errors = [], []
    page.on("request", lambda r: requests.append(r.url))
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(site + "builder/")
    page.wait_for_function("window.__spotiBuilder")
    page.wait_for_load_state("networkidle")
    assert page.locator("h1").text_content() == "Config builder"
    assert all(u.startswith(site) or u.startswith("data:") or u.startswith("blob:") for u in requests), requests
    assert not errors, errors
    # the empty form is already a valid config
    assert problem_count(page) == 0
    assert validated(preview(page)).rules == ()


def test_landing_page_links_to_builder(make_page, site):
    page, _ = make_page()
    page.goto(site)
    link = page.get_by_role("link", name="Open the config builder")
    assert link.get_attribute("href") == "builder/"
    link.click()
    page.wait_for_url(site + "builder/")


# ------------------------------------------------------------------ building each rule type
CASES = [
    ("artist_in", lambda r: add_chips(r, "artist_in", "Bonobo", "Tyler, The Creator"),
     {"artist_in": ["Bonobo", "Tyler, The Creator"]}),
    ("genre_contains", lambda r: add_chips(r, "genre_contains", "jazz", "hip hop"),
     {"genre_contains": ["jazz", "hip hop"]}),
    ("language_in", lambda r: add_chips(r, "language_in", "hi", "Malayalam", "ta"),
     {"language_in": ["hindi", "malayalam", "tamil"]}),
    ("release_year_before", lambda r: add_cond(r, "release_year_before").fill("2010"), {"release_year_before": 2010}),
    ("release_year_after", lambda r: add_cond(r, "release_year_after").fill("1999"), {"release_year_after": 1999}),
    ("explicit_true", lambda r: add_cond(r, "explicit").select_option("true"), {"explicit": True}),
    ("explicit_false", lambda r: add_cond(r, "explicit").select_option("false"), {"explicit": False}),
    ("track_name_contains", lambda r: add_cond(r, "track_name_contains").fill("acoustic"), {"track_name_contains": "acoustic"}),
    ("album_name_contains", lambda r: add_cond(r, "album_name_contains").fill("Live at"), {"album_name_contains": "Live at"}),
]


@pytest.mark.parametrize("label,build,expected", CASES, ids=[c[0] for c in CASES])
def test_build_each_rule_type(builder, label, build, expected):
    r = add_rule(builder, "My rule", "My Playlist")
    build(r)
    assert problem_count(builder) == 0, builder.locator("#error-summary").text_content()
    cfg = validated(download_text(builder))
    assert len(cfg.rules) == 1
    got = cfg.rules[0]
    assert got.name == "My rule" and got.target_playlist == "My Playlist"
    assert got.match == expected
    assert got.enabled is True and got.create_missing_playlists is False and got.days_threshold is None
    assert got.target_position == "bottom"


def test_full_build_with_globals_and_all_keys(builder):
    builder.get_by_label("Default days threshold").fill("21")
    builder.get_by_label("Fallback playlist").fill("Inbox Overflow")
    builder.get_by_label("Look up genre and language on MusicBrainz").uncheck()
    builder.get_by_role("button", name="Add language playlist").click()
    builder.locator("#lp-list li").first.get_by_label("Playlist name", exact=True).fill("Chill Hindi")
    lang = builder.locator("#lp-list li").first.get_by_label("Language", exact=True)
    lang.fill("hi")
    lang.blur()
    assert lang.input_value() == "hindi"

    r = add_rule(builder, "Everything", "Kitchen Sink")
    r.get_by_label("Days threshold override").fill("3")
    r.get_by_label("Create playlist if missing").check()
    r.get_by_label("Enabled", exact=True).uncheck()
    r.get_by_label("Insert position").select_option("top")
    add_chips(r, "artist_in", "Bonobo")
    add_chips(r, "genre_contains", "ambient")
    add_chips(r, "language_in", "en")
    add_cond(r, "release_year_before").fill("2020")
    add_cond(r, "release_year_after").fill("1990")
    add_cond(r, "explicit").select_option("false")
    add_cond(r, "track_name_contains").fill("remix")
    add_cond(r, "album_name_contains").fill("deluxe")
    assert r.locator("select[id$='-add-cond']").count() == 0  # all conditions used

    text = download_text(builder)
    assert text == preview(builder)
    cfg = validated(text)
    assert cfg.default_days_threshold == 21
    assert cfg.fallback_playlist == "Inbox Overflow"
    assert cfg.musicbrainz is False
    assert cfg.english_default is False
    assert dict(cfg.language_playlists) == {"Chill Hindi": "hindi"}
    (got,) = cfg.rules
    assert got.enabled is False and got.create_missing_playlists is True and got.days_threshold == 3
    assert got.target_position == "top"
    assert got.match == {
        "artist_in": ["Bonobo"], "genre_contains": ["ambient"], "language_in": ["english"],
        "release_year_before": 2020, "release_year_after": 1990, "explicit": False,
        "track_name_contains": "remix", "album_name_contains": "deluxe",
    }


def test_copy_button_copies_yaml(builder):
    add_chips(add_rule(builder, "R", "P"), "artist_in", "Tycho")
    builder.get_by_role("button", name="Copy", exact=True).click()
    builder.wait_for_function("document.getElementById('action-status').textContent.startsWith('Copied')")
    clip = builder.evaluate("navigator.clipboard.readText()")
    clip = chr(10).join(clip.splitlines()) + chr(10)  # Windows clipboard uses CRLF
    assert clip == preview(builder)
    assert validated(clip).rules[0].match == {"artist_in": ["Tycho"]}


# ------------------------------------------------------------------ language aliases
def test_alias_normalisation_in_chips_and_yaml(builder):
    r = add_rule(builder, "Lang", "P")
    add_chips(r, "language_in", "hi", "ML", "தமிழ்")
    chips = [c.text_content() for c in r.locator(".chip span").all()]
    assert chips == ["hindi", "malayalam", "tamil"]
    assert "hindi" in preview(builder) and "- hi" not in preview(builder)
    # duplicates via alias are collapsed
    field = r.locator("input[id$='-match-language_in']")
    field.fill("hin")
    field.press("Enter")
    assert [c.text_content() for c in r.locator(".chip span").all()] == ["hindi", "malayalam", "tamil"]


def test_alias_table_matches_python(builder):
    js = builder.evaluate("(aliases) => aliases.map(a => window.SpotiLang.normalize(a))", list(ALIASES))
    assert js == [normalize_language(a) for a in ALIASES]
    probes = ["  HINDI ", "Hi", "klingon", "", "xx"]
    js = builder.evaluate("(ps) => ps.map(a => window.SpotiLang.normalize(a))", probes)
    assert js == [normalize_language(p) for p in probes]


# ------------------------------------------------------------------ reorder / remove
def names_in_preview(page):
    return [x["name"] for x in preview_data(page)["rules"]]


def test_reorder_with_buttons_and_keyboard(builder):
    for n in ("A", "B", "C"):
        add_chips(add_rule(builder, n, "P" + n), "genre_contains", n.lower())
    assert names_in_preview(builder) == ["A", "B", "C"]
    up_first = rule(builder, 0).get_by_role("button", name="Move rule 1 up")
    assert up_first.is_disabled()
    rule(builder, 0).get_by_role("button", name="Move rule 1 down").click()
    assert names_in_preview(builder) == ["B", "A", "C"]
    # keyboard only: focus follows the moved rule, Enter / Space activate
    focused = builder.evaluate("document.activeElement.getAttribute('aria-label')")
    assert focused == "Move rule 2 down"
    builder.keyboard.press("Enter")
    assert names_in_preview(builder) == ["B", "C", "A"]
    focused = builder.evaluate("document.activeElement.getAttribute('aria-label')")
    assert focused == "Move rule 3 up"  # last position: down is disabled so focus moves to up
    builder.keyboard.press("Space")
    assert names_in_preview(builder) == ["B", "A", "C"]
    assert "position 2 of 3" in builder.locator("#rule-notice").text_content()
    assert [rule(builder, i).get_by_label("Rule name").input_value() for i in range(3)] == ["B", "A", "C"]
    assert [r.name for r in validated(download_text(builder)).rules] == ["B", "A", "C"]


def test_remove_and_undo(builder):
    for n in ("A", "B"):
        add_chips(add_rule(builder, n, "P"), "genre_contains", "x")
    rule(builder, 0).get_by_role("button", name="Remove rule 1").click()
    assert names_in_preview(builder) == ["B"]
    builder.get_by_role("button", name="Undo").click()
    assert names_in_preview(builder) == ["A", "B"]


# ------------------------------------------------------------------ validation
def _bad_empty_name(p):
    r = add_rule(p, "", "P"); add_chips(r, "genre_contains", "x")


def _bad_no_target(p):
    r = add_rule(p, "R", ""); add_chips(r, "genre_contains", "x")


def _bad_no_match(p):
    add_rule(p, "R", "P")


def _bad_duplicate_names(p):
    add_chips(add_rule(p, "Jazz", "P"), "genre_contains", "x")
    add_chips(add_rule(p, "jazz", "P2"), "genre_contains", "y")


def _bad_empty_list(p):
    add_cond(add_rule(p, "R", "P"), "artist_in")


def _bad_unknown_language(p):
    add_chips(add_rule(p, "R", "P"), "language_in", "klingon")


def _bad_year(value):
    def build(p):
        add_cond(add_rule(p, "R", "P"), "release_year_before").fill(value)
    return build


def _bad_text_blank(p):
    add_cond(add_rule(p, "R", "P"), "track_name_contains").fill("   ")


def _bad_text_empty(p):
    add_cond(add_rule(p, "R", "P"), "album_name_contains")


def _bad_days_rule(value):
    def build(p):
        r = add_rule(p, "R", "P"); add_chips(r, "genre_contains", "x")
        r.get_by_label("Days threshold override").fill(value)
    return build


def _bad_default_days(value):
    return lambda p: p.get_by_label("Default days threshold").fill(value)


def _bad_fallback_blank(p):
    p.get_by_label("Fallback playlist").fill("   ")


def _bad_lp_language(p):
    p.get_by_role("button", name="Add language playlist").click()
    li = p.locator("#lp-list li").first
    li.get_by_label("Playlist name", exact=True).fill("Chill")
    li.get_by_label("Language", exact=True).fill("elvish")


def _bad_lp_no_name(p):
    p.get_by_role("button", name="Add language playlist").click()
    p.locator("#lp-list li").first.get_by_label("Language", exact=True).fill("hindi")


INVALID = [
    ("empty_name", _bad_empty_name, "'name' is required"),
    ("no_target", _bad_no_target, "'target_playlist' is required"),
    ("no_match", _bad_no_match, "'match' must be a non-empty mapping"),
    ("duplicate_names", _bad_duplicate_names, "duplicate rule name"),
    ("empty_list", _bad_empty_list, "non-empty list of non-empty strings"),
    ("unknown_language", _bad_unknown_language, "unknown language 'klingon'"),
    ("year_zero", _bad_year("0"), "year (integer 1-9999)"),
    ("year_10000", _bad_year("10000"), "year (integer 1-9999)"),
    ("year_text", _bad_year("abc"), "year (integer 1-9999)"),
    ("year_blank", _bad_year(""), "year (integer 1-9999)"),
    ("text_blank", _bad_text_blank, "must be a non-empty string"),
    ("text_empty", _bad_text_empty, "must be a non-empty string"),
    ("days_negative", _bad_days_rule("-1"), "'days_threshold' must be an integer >= 0"),
    ("days_text", _bad_days_rule("soon"), "'days_threshold' must be an integer >= 0"),
    ("default_days_text", _bad_default_days("abc"), "'default_days_threshold' must be an integer >= 0"),
    ("default_days_negative", _bad_default_days("-5"), "'default_days_threshold' must be an integer >= 0"),
    ("fallback_blank", _bad_fallback_blank, "'fallback_playlist' must be a playlist name or null"),
    ("lp_unknown_language", _bad_lp_language, "unknown language 'elvish'"),
    ("lp_blank_name", _bad_lp_no_name, "playlist names must be non-empty strings"),
]


@pytest.mark.parametrize("label,build,fragment", INVALID, ids=[c[0] for c in INVALID])
def test_invalid_configs_are_blocked_like_the_python_validator(builder, label, build, fragment):
    downloads = []
    builder.on("download", lambda d: downloads.append(d))
    build(builder)
    assert problem_count(builder) >= 1
    assert builder.get_by_role("button", name="Download config.yaml").get_attribute("aria-disabled") == "true"

    builder.get_by_role("button", name="Download config.yaml").click(force=True)
    summary = builder.locator("#error-summary")
    assert summary.is_visible()
    assert fragment in summary.text_content()
    assert builder.evaluate("document.activeElement.id") == "error-summary"
    builder.get_by_role("button", name="Copy", exact=True).click(force=True)
    assert "Cannot copy" in builder.locator("#action-status").text_content()
    builder.wait_for_timeout(150)
    assert downloads == []

    # ... and the real Python validator rejects exactly what the builder would have exported
    with pytest.raises(ConfigError) as ei:
        validated(preview(builder))
    py_msgs = ei.value.errors
    assert any(fragment in m for m in py_msgs), py_msgs
    # inline error is next to a field (rule-level or global)
    assert builder.locator(".err:not(:empty)").count() >= 1


def test_blocked_state_clears_when_fixed(builder):
    r = add_rule(builder, "R", "P")
    builder.get_by_role("button", name="Download config.yaml").click(force=True)
    assert builder.locator("#error-summary").is_visible()
    add_chips(r, "genre_contains", "jazz")
    assert not builder.locator("#error-summary").is_visible()
    assert builder.get_by_role("button", name="Download config.yaml").get_attribute("aria-disabled") is None
    validated(download_text(builder))


def test_new_rule_does_not_shout_before_touched(builder):
    builder.get_by_role("button", name="Add rule").click()
    assert builder.locator(".err:not(:empty)").count() == 0
    assert not builder.locator("#error-summary").is_visible()


# ------------------------------------------------------------------ validator parity (JS vs Python), incl. messages
PARITY = [
    None, {}, [], "x", {"bogus": 1}, {"default_days_threshold": -1}, {"default_days_threshold": True},
    {"default_days_threshold": "7"}, {"fallback_playlist": ""}, {"fallback_playlist": 5},
    {"language_playlists": []}, {"language_playlists": {"": "hindi", "A": "nope", "B": "ml"}},
    {"enrichment": []}, {"enrichment": {"musicbrainz": "yes", "other": 1}},
    {"enrichment": {"english_default": "yes"}}, {"enrichment": {"english_default": 1, "musicbrainz": None}},
    {"enrichment": {"english_default": False, "musicbrainz": True}}, {"rules": {}},
    {"rules": ["x", {}, {"name": "a"}]},
    *[{"rules": [{"name": "r", "target_playlist": "p", "match": {"explicit": True}, "target_position": v}]}
      for v in ("top", "bottom", "middle", "", "TOP", True, 0, 1, None, [], {})],
    {"rules": [{"name": "O'Brien", "target_playlist": "p", "match": {}, "extra": 1}]},
    {"rules": [{"name": "r", "target_playlist": "p", "match": {"nope": 1, "artist_in": [], "genre_contains": ["a", ""],
                                                                 "language_in": ["hi", "zzz"], "release_year_before": 0,
                                                                 "release_year_after": True, "explicit": "x",
                                                                 "track_name_contains": " ", "album_name_contains": 3}}]},
    {"rules": [{"name": "r", "target_playlist": "p", "match": {"explicit": True}, "enabled": None,
                "create_missing_playlists": 1, "days_threshold": -2}]},
    {"rules": [{"name": "Same", "target_playlist": "p", "match": {"explicit": True}},
               {"name": "same", "target_playlist": "p", "match": {"explicit": False}}]},
    {"rules": [{"name": "ok", "target_playlist": "p", "match": {"language_in": ["hindi", "ml"], "release_year_after": 9999},
                "days_threshold": 0}], "language_playlists": {"X": "tamil"}, "enrichment": {"musicbrainz": False, "english_default": False},
     "fallback_playlist": "F", "default_days_threshold": 0},
]


@pytest.mark.parametrize("doc", PARITY, ids=[f"doc{i}" for i in range(len(PARITY))])
def test_js_validator_matches_python_messages(builder, doc):
    js = builder.evaluate("(d) => window.SpotiValidate.validateConfig(d).errors.map(e => e.msg)", doc)
    try:
        parse_config(doc)
        py = []
    except ConfigError as exc:
        py = exc.errors
    assert js == py


# ------------------------------------------------------------------ english_default
def test_english_default_toggle_changes_yaml(builder):
    box = builder.get_by_label("Assume English for Latin-script songs", exact=False)
    assert not box.is_checked()
    assert "Off by default" in builder.locator("#g-en-hint").text_content()
    assert preview_data(builder)["enrichment"] == {"musicbrainz": True, "english_default": False}
    assert validated(download_text(builder)).english_default is False
    box.check()
    assert preview_data(builder)["enrichment"]["english_default"] is True
    assert validated(download_text(builder)).english_default is True


def test_insert_position_select(builder):
    r = add_rule(builder, "Vault", "The Vault")
    add_cond(r, "explicit").select_option("false")
    sel = r.get_by_label("Insert position")
    assert sel.input_value() == "bottom"
    assert [o.text_content() for o in sel.locator("option").all()] == ["Bottom (default)", "Top"]
    assert validated(download_text(builder)).rules[0].target_position == "bottom"
    sel.select_option("top")
    assert preview_data(builder)["rules"][0]["target_position"] == "top"
    assert validated(download_text(builder)).rules[0].target_position == "top"


@pytest.mark.parametrize("value", ["top", "bottom"])
def test_insert_position_import_roundtrip(builder, value):
    text = f"rules:\n  - name: R\n    target_playlist: P\n    target_position: {value}\n    match:\n      explicit: true\n"
    builder.locator("#import summary").click()
    builder.get_by_label("Or paste YAML").fill(text)
    builder.get_by_role("button", name="Load into form").click()
    assert rule(builder, 0).get_by_label("Insert position").input_value() == value
    assert validated(download_text(builder)).rules[0].target_position == value


@pytest.mark.parametrize("value", [True, False])
def test_english_default_import_roundtrip(builder, value):
    text = f"enrichment:\n  musicbrainz: true\n  english_default: {str(value).lower()}\n"
    builder.locator("#import summary").click()
    builder.get_by_label("Or paste YAML").fill(text)
    builder.get_by_role("button", name="Load into form").click()
    assert builder.get_by_label("Assume English for Latin-script songs", exact=False).is_checked() is value
    assert f"english_default: {str(value).lower()}" in download_text(builder)
    assert validated(download_text(builder)).english_default is value


def test_english_default_invalid_flags_field(builder):
    builder.locator("#import summary").click()
    builder.get_by_label("Or paste YAML").fill("enrichment:\n  english_default: maybe\n")
    builder.get_by_role("button", name="Load into form").click()
    assert "'enrichment.english_default' must be true or false" in builder.locator("#import-status").text_content()
    assert not builder.get_by_label("Assume English for Latin-script songs", exact=False).is_checked()  # falls back to default


# ------------------------------------------------------------------ import
def test_import_example_config_roundtrips(builder):
    original = (ROOT / "config.example.yaml").read_text(encoding="utf-8")
    builder.locator("#import summary").click()
    builder.get_by_label("Or paste YAML").fill(original)
    builder.get_by_role("button", name="Load into form").click()
    assert "Loaded 6 rules" in builder.locator("#import-status").text_content()
    assert builder.locator("#rules > li").count() == 6
    assert rule(builder, 0).get_by_label("Rule name").input_value() == "Jazz to Jazz Vault"
    assert rule(builder, 0).get_by_label("Days threshold override").input_value() == "7"
    assert builder.get_by_label("Default days threshold").input_value() == "14"
    assert problem_count(builder) == 0
    exported = download_text(builder)
    assert validated(exported) == parse_config(yaml.safe_load(original))


def test_import_via_file_picker_and_alias_normalisation(builder, tmp_path):
    f = tmp_path / "in.yaml"
    f.write_text(
        'language_playlists:\n  "Malayalam Favs": ml\nrules:\n  - name: H\n    target_playlist: P\n'
        "    match:\n      language_in: [hi, tamil]\n",
        encoding="utf-8",
    )
    builder.locator("#import summary").click()
    builder.set_input_files("#import-file", str(f))
    builder.wait_for_function("document.querySelectorAll('#rules > li').length === 1")
    assert builder.locator("#lp-list li").first.get_by_label("Language", exact=True).input_value() == "malayalam"
    cfg = validated(download_text(builder))
    assert cfg.rules[0].match == {"language_in": ["hindi", "tamil"]}
    assert dict(cfg.language_playlists) == {"Malayalam Favs": "malayalam"}


def test_import_bad_yaml_and_invalid_config(builder):
    builder.locator("#import summary").click()
    text = builder.get_by_label("Or paste YAML")
    text.fill("rules: [unclosed")
    builder.get_by_role("button", name="Load into form").click()
    assert "Not valid YAML" in builder.locator("#import-status").text_content()
    text.fill("- just\n- a list\n")
    builder.get_by_role("button", name="Load into form").click()
    assert "top level must be a mapping" in builder.locator("#import-status").text_content()
    text.fill("bogus: 1\nrules:\n  - name: R\n    target_playlist: P\n    match:\n      release_year_before: 0\n")
    builder.get_by_role("button", name="Load into form").click()
    status = builder.locator("#import-status").text_content()
    assert "unknown top-level key 'bogus'" in status and "year (integer 1-9999)" in status
    # the bad value is loaded into the form and flagged, and export stays blocked
    assert rule(builder, 0).locator("input[id$='-match-release_year_before']").input_value() == "0"
    assert problem_count(builder) == 1
    assert "year" in rule(builder, 0).locator(".err:not(:empty)").first.text_content()


# ------------------------------------------------------------------ accessibility basics
def test_every_control_has_an_accessible_name(builder):
    r = add_rule(builder, "R", "P")
    for key in ("artist_in", "language_in", "release_year_before", "explicit", "track_name_contains"):
        add_cond(r, key)
    builder.get_by_role("button", name="Add language playlist").click()
    unnamed = builder.evaluate(
        """() => [...document.querySelectorAll('input, select, textarea, button')]
            .filter(e => e.type !== 'hidden')
            .filter(e => !(e.labels && e.labels.length) && !e.getAttribute('aria-label') && !e.textContent.trim()
                         && !e.getAttribute('aria-labelledby'))
            .map(e => e.outerHTML.slice(0, 80))"""
    )
    assert unnamed == []
    assert builder.locator("html").get_attribute("lang") == "en"


# ------------------------------------------------------------------ PWA
def test_manifest_and_icons(make_page, site):
    page, _ = make_page()
    page.goto(site + "builder/")
    href = page.locator("link[rel=manifest]").get_attribute("href")
    resp = page.request.get(page.evaluate("(h) => new URL(h, location.href).href", href))
    assert resp.ok
    manifest = json.loads(resp.text())
    for key in ("name", "short_name", "start_url", "scope", "display", "icons", "theme_color", "background_color"):
        assert manifest[key]
    assert manifest["display"] == "standalone"
    assert manifest["start_url"].startswith(".") and manifest["scope"].startswith(".")  # relative: works under /SpotiSort/
    assert page.locator("meta[name=theme-color]").get_attribute("content")
    base = site  # manifest sits in docs/
    sizes, purposes = set(), set()
    for icon in manifest["icons"]:
        r = page.request.get(base + icon["src"])
        assert r.ok, icon
        body = r.body()
        assert body[:8] == b"\x89PNG\r\n\x1a\n"
        w, h = int.from_bytes(body[16:20], "big"), int.from_bytes(body[20:24], "big")
        assert f"{w}x{h}" == icon["sizes"]
        sizes.add(icon["sizes"])
        purposes.add(icon.get("purpose", "any"))
    assert {"192x192", "512x512"} <= sizes and {"any", "maskable"} <= purposes
    assert page.request.get(site + "builder/").ok  # start_url ./builder/ resolves against the manifest
    assert page.request.get(site + "builder/").ok


def test_service_worker_and_offline_reload(make_page, site):
    page, ctx = make_page()
    page.goto(site + "builder/")
    page.wait_for_function("window.__spotiBuilder")
    scope = page.evaluate("navigator.serviceWorker.ready.then(r => r.scope)")
    assert scope == site  # covers the whole site incl. builder/
    page.wait_for_function("navigator.serviceWorker.controller || true")
    page.reload()  # now controlled by the SW
    page.wait_for_function("navigator.serviceWorker.controller !== null")
    keys = page.evaluate("caches.keys()")
    assert keys == ["spotisort-shell-v5"]
    cached = page.evaluate("caches.open('spotisort-shell-v5').then(c => c.keys()).then(ks => ks.map(k => k.url))")
    for needed in ("builder/", "builder/app.js", "builder/languages.js", "builder/validate.js", "builder/builder.css",
                   "vendor/js-yaml.min.js", "manifest.webmanifest", "icons/icon-192.png", "style.css"):
        assert site + needed in cached, needed

    ctx.set_offline(True)
    page.reload()
    page.wait_for_function("window.__spotiBuilder && window.__spotiBuilder.ready")
    assert page.locator("h1").text_content() == "Config builder"
    r = add_rule(page, "Offline", "P")
    add_chips(r, "genre_contains", "jazz")
    assert validated(preview(page)).rules[0].name == "Offline"
    # landing page works offline too
    page.goto(site)
    assert page.get_by_role("link", name="Open the config builder").is_visible()
    ctx.set_offline(False)


# ------------------------------------------------------------------ layout / screenshots
def _populate_sample(page):
    original = (ROOT / "config.example.yaml").read_text(encoding="utf-8")
    page.locator("#import summary").click()
    page.get_by_label("Or paste YAML").fill(original)
    page.get_by_role("button", name="Load into form").click()
    page.locator("#import summary").click()  # collapse again
    page.wait_for_function("document.querySelectorAll('#rules > li').length === 6")


@pytest.mark.parametrize("width,height,name", [(375, 812, "builder-375.png"), (1280, 900, "builder-1280.png")])
def test_layout_screenshots_and_no_horizontal_overflow(make_page, site, width, height, name):
    page, _ = make_page(width=width, height=height)
    page.goto(site + "builder/")
    page.wait_for_function("window.__spotiBuilder")
    _populate_sample(page)
    # stress: long unbroken text and chips
    r = add_rule(page, "A very long rule name " + "x" * 60, "Target " + "y" * 60)
    add_chips(r, "artist_in", "Z" * 80, "Someone With A Fairly Long Name")
    add_cond(r, "track_name_contains").fill("q" * 90)
    overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert overflow <= 0, f"horizontal overflow of {overflow}px at {width}px"
    assert page.evaluate("document.body.scrollWidth") <= width
    # drop the stress rule again so the screenshot shows the tidy example
    r.get_by_role("button", name="Remove rule 7").click()
    page.evaluate("() => { document.getElementById('rule-notice').className = 'notice'; document.activeElement.blur(); window.scrollTo(0, 0); }")
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SHOTS / name), full_page=True)
    assert (SHOTS / name).stat().st_size > 10_000


def test_dark_mode_renders(make_page, site):
    page, _ = make_page(color_scheme="dark")
    page.goto(site + "builder/")
    page.wait_for_function("window.__spotiBuilder")
    bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
    assert bg == "rgb(15, 19, 17)"
