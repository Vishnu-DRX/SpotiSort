"""Browser tests for the Pages Configure app (docs/builder). Run: python -m pytest tests/e2e -q -m e2e"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect  # noqa: E402

try:
    from axe_playwright_python.sync_playwright import Axe
except ImportError:  # optional dev dependency
    Axe = None

from src.config import ConfigError, parse_config  # noqa: E402
from src.enrichment.languages import ALIASES, normalize_language  # noqa: E402

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
SHOTS = DOCS / "screenshots"


# ------------------------------------------------------------------ helpers
def preview(page) -> str:
    return page.locator("#yaml-preview code").text_content()


def preview_data(page):
    return yaml.safe_load(preview(page))


def rule(page, i):
    return page.locator("#rules > li").nth(i)


def goto_step(page, n, name):
    page.locator("#step-tab-" + str(n)).click()
    expect(page.locator("#step-" + str(n))).to_be_visible()


def add_rule(page, name, target):
    goto_step(page, 3, "Rules")
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


def goto_review(page):
    goto_step(page, 4, "Review")


def download_text(page) -> str:
    goto_review(page)
    with page.expect_download() as info:
        page.get_by_role("button", name="Download config.yaml").click()
    dl = info.value
    assert dl.suggested_filename == "config.yaml"
    return Path(dl.path()).read_text(encoding="utf-8")


def validated(text: str):
    """Run the REAL Python validator on Configure output."""
    return parse_config(yaml.safe_load(text))


def problem_count(page) -> int:
    goto_review(page)
    txt = page.locator("#status").text_content()
    return 0 if txt.startswith("Valid") else int(txt.split()[0])


def start_blank(page):
    page.get_by_role("button", name="Start blank").click()
    expect(page.locator("#wizard")).to_be_visible()


def click_switch(page, input_id):
    """Click a `.switch` component's visible pill/label rather than its (visually covered) checkbox input -
    components.css stacks `.switch-ui` above `.switch-input` since both are position:relative siblings, so a
    direct Playwright click/check on the input itself is intercepted. A real mouse user clicking the pill
    works via native <label> click-forwarding; this reproduces that instead of clicking the input directly."""
    page.locator(f"label:has(#{input_id}) .switch-ui").click()


def make_advanced(page):
    box = page.locator("#advanced-toggle")
    if not box.is_checked():
        click_switch(page, "advanced-toggle")


# ------------------------------------------------------------------ fixtures (local overrides of conftest's `builder`)
@pytest.fixture
def builder(make_page, site):
    page, _ = make_page()
    page.goto(site + "builder/")
    page.wait_for_function("window.__spotiBuilder && window.__spotiBuilder.ready")
    start_blank(page)
    make_advanced(page)
    return page


@pytest.fixture
def builder_basic(make_page, site):
    page, _ = make_page()
    page.goto(site + "builder/")
    page.wait_for_function("window.__spotiBuilder && window.__spotiBuilder.ready")
    start_blank(page)
    return page


# ------------------------------------------------------------------ basics
def test_page_loads_without_external_requests_or_errors(make_page, site):
    page, ctx = make_page()
    requests, errors = [], []
    page.on("request", lambda r: requests.append(r.url))
    # ignore the browser's own network-resource-load log lines (e.g. a blocked/rate-limited GitHub API
    # request from the star count fetch, which is designed to fail silently - see shell.js loadStars()).
    # A failed network request is not, by itself, an application bug (same filter as test_site.py).
    page.on("console", lambda m: (m.type == "error" and "Failed to load resource" not in m.text) and errors.append(m.text))
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(site + "builder/")
    page.wait_for_function("window.__spotiBuilder")
    page.wait_for_load_state("networkidle")
    assert page.locator("h1").text_content() == "Configure"
    # the shared site shell (U1) fetches the GitHub star count at runtime and fails silently if it errors
    # (decision 26) - that is a known, intentional external request made by every page, not a Configure bug.
    requests = [u for u in requests if not u.startswith("https://api.github.com/")]
    assert all(u.startswith(site) or u.startswith("data:") or u.startswith("blob:") for u in requests), requests
    assert not errors, errors
    assert page.locator("#templates").is_visible()


def test_landing_page_links_to_configure(make_page, site):
    page, _ = make_page()
    page.goto(site)
    link = page.get_by_role("link", name="Configure", exact=True)
    assert link.get_attribute("href").endswith("builder/")
    link.click()
    page.wait_for_url(site + "builder/")


def test_templates_shown_on_first_visit_and_not_after(make_page, site):
    page, _ = make_page()
    page.goto(site + "builder/")
    page.wait_for_function("window.__spotiBuilder")
    expect(page.locator("#templates")).to_be_visible()
    expect(page.locator("#wizard")).to_be_hidden()
    start_blank(page)
    page.reload()
    page.wait_for_function("window.__spotiBuilder && window.__spotiBuilder.ready")
    expect(page.locator("#templates")).to_be_hidden()
    expect(page.locator("#wizard")).to_be_visible()


def test_template_language_prefills_rule_and_playlist(make_page, site):
    page, _ = make_page()
    page.goto(site + "builder/")
    page.wait_for_function("window.__spotiBuilder")
    page.get_by_role("button", name="Sort by language").click()
    data = preview_data(page)
    assert data["language_playlists"] == {"Chill Hindi": "hindi"}
    assert data["rules"][0]["match"] == {"language_in": ["hindi"]}


def test_template_artist_prefills_rule(make_page, site):
    page, _ = make_page()
    page.goto(site + "builder/")
    page.wait_for_function("window.__spotiBuilder")
    page.get_by_role("button", name="Sort by artist").click()
    data = preview_data(page)
    assert data["rules"][0]["match"] == {"artist_in": ["Bonobo", "Tycho"]}


# ------------------------------------------------------------------ stepper
def test_stepper_next_back_and_sidebar_jump(builder_basic):
    page = builder_basic
    expect(page.locator("#step-1")).to_be_visible()
    page.locator("#step-1 [data-next]").click()
    expect(page.locator("#step-2")).to_be_visible()
    page.locator("#step-2 [data-back]").click()
    expect(page.locator("#step-1")).to_be_visible()
    goto_step(page, 3, "Rules")
    expect(page.locator("#step-3")).to_be_visible()
    assert page.locator("#step-tab-1").get_attribute("class") and "is-done" in page.locator("#step-tab-1").get_attribute("class")


def test_next_never_blocked_by_invalid_step(builder):
    add_rule(builder, "", "")  # invalid rule: no name, no target, no match
    goto_step(builder, 4, "Review")
    expect(builder.locator("#step-4")).to_be_visible()
    assert problem_count(builder) >= 1


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
    goto_step(builder, 1, "Basics")
    builder.get_by_label("Default days threshold").fill("21")
    builder.get_by_label("Fallback playlist").fill("Inbox Overflow")
    goto_step(builder, 2, "Languages")
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
    cfg = validated(text)
    assert cfg.default_days_threshold == 21
    assert cfg.fallback_playlist == "Inbox Overflow"
    assert cfg.musicbrainz is False
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
    goto_review(builder)
    builder.get_by_role("button", name="Copy to clipboard").first.click()
    clip = builder.evaluate("navigator.clipboard.readText()")
    clip = chr(10).join(clip.splitlines()) + chr(10)
    assert validated(clip).rules[0].match == {"artist_in": ["Tycho"]}


# ------------------------------------------------------------------ language aliases
def test_alias_normalisation_in_chips_and_yaml(builder):
    r = add_rule(builder, "Lang", "P")
    add_chips(r, "language_in", "hi", "ML", "தமிழ்")
    chips = [c.text_content() for c in r.locator(".chip span").all()]
    assert chips == ["hindi", "malayalam", "tamil"]
    field = r.locator("input[id$='-match-language_in']")
    field.fill("hin")
    field.press("Enter")
    assert [c.text_content() for c in r.locator(".chip span").all()] == ["hindi", "malayalam", "tamil"]


def test_alias_table_matches_python(builder):
    js = builder.evaluate("(aliases) => aliases.map(a => window.SpotiLang.normalize(a))", list(ALIASES))
    assert js == [normalize_language(a) for a in ALIASES]


# ------------------------------------------------------------------ reorder / duplicate / collapse / remove
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
    focused = builder.evaluate("document.activeElement.getAttribute('aria-label')")
    assert focused == "Move rule 2 down"
    builder.keyboard.press("Enter")
    assert names_in_preview(builder) == ["B", "C", "A"]
    assert [rule(builder, i).get_by_label("Rule name").input_value() for i in range(3)] == ["B", "C", "A"]


def test_duplicate_rule(builder):
    add_chips(add_rule(builder, "A", "P"), "genre_contains", "x")
    rule(builder, 0).get_by_role("button", name="Duplicate rule 1").click()
    assert names_in_preview(builder) == ["A", "A (copy)"]
    assert rule(builder, 1).get_by_label("Rule name").input_value() == "A (copy)"


def test_collapse_expand_rule(builder):
    add_chips(add_rule(builder, "A", "P"), "genre_contains", "x")
    r = rule(builder, 0)
    r.get_by_role("button", name="Collapse").click()
    expect(r.locator(".rule-body")).to_be_hidden()
    r.get_by_role("button", name="Expand").click()
    expect(r.locator(".rule-body")).to_be_visible()


def test_disable_rule_shows_badge_and_persists_priority_note(builder):
    r = add_rule(builder, "A", "P")
    add_chips(r, "genre_contains", "x")
    r.get_by_label("Enabled", exact=True).uncheck()
    expect(r.locator(".badge")).to_have_text("disabled")
    goto_step(builder, 3, "Rules")
    assert "first match wins" in builder.locator("#step-3").text_content()


def test_remove_and_undo(builder):
    for n in ("A", "B"):
        add_chips(add_rule(builder, n, "P"), "genre_contains", "x")
    rule(builder, 0).get_by_role("button", name="Remove rule 1").click()
    assert names_in_preview(builder) == ["B"]
    builder.get_by_role("button", name="Undo").click()
    assert names_in_preview(builder) == ["A", "B"]


# ------------------------------------------------------------------ undo/redo (Ctrl+Z / Ctrl+Y), any form edit
def test_undo_redo_on_form_edit(builder):
    goto_step(builder, 1, "Basics")
    field = builder.get_by_label("Default days threshold")
    field.fill("21")
    field.blur()
    assert preview_data(builder)["default_days_threshold"] == 21
    builder.keyboard.press("Control+z")
    assert preview_data(builder).get("default_days_threshold", 14) == 14
    builder.keyboard.press("Control+y")
    assert preview_data(builder)["default_days_threshold"] == 21


# ------------------------------------------------------------------ validation
def _bad_no_match(p):
    add_rule(p, "R", "P")


def _bad_unknown_language(p):
    add_chips(add_rule(p, "R", "P"), "language_in", "klingon")


INVALID = [
    ("no_match", _bad_no_match, "'match' must be a non-empty mapping"),
    ("unknown_language", _bad_unknown_language, "unknown language 'klingon'"),
]


@pytest.mark.parametrize("label,build,fragment", INVALID, ids=[c[0] for c in INVALID])
def test_invalid_configs_are_blocked_like_the_python_validator(builder, label, build, fragment):
    build(builder)
    goto_review(builder)
    assert problem_count(builder) >= 1
    assert builder.get_by_role("button", name="Download config.yaml").get_attribute("aria-disabled") == "true"
    summary = builder.locator("#error-summary")
    assert summary.is_visible()
    assert fragment in summary.text_content()
    with pytest.raises(ConfigError) as ei:
        validated(preview(builder))
    assert any(fragment in m for m in ei.value.errors)


# ------------------------------------------------------------------ validator parity (JS vs Python), incl. logging (decision 32)
PARITY = [
    None, {}, {"logging": []}, {"logging": None}, {"logging": {"include_track_names": "yes"}},
    {"logging": {"include_track_names": True, "other": 1}}, {"logging": {"include_track_names": True}},
    {"logging": {"include_track_names": False}},
    {"rules": [{"name": "Same", "target_playlist": "p", "match": {"explicit": True}},
               {"name": "same", "target_playlist": "p", "match": {"explicit": False}}]},
    {"rules": [{"name": "ok", "target_playlist": "p", "match": {"language_in": ["hindi", "ml"], "release_year_after": 9999},
                "days_threshold": 0}], "language_playlists": {"X": "tamil"},
     "enrichment": {"musicbrainz": False, "english_default": False}, "logging": {"include_track_names": True},
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


def test_logging_default_false_and_toggle_updates_yaml(builder_basic):
    page = builder_basic
    goto_step(page, 2, "Languages")
    box = page.locator("#g-log")
    assert not box.is_checked()
    assert preview_data(page)["logging"] == {"include_track_names": False}
    click_switch(page, "g-log")
    assert preview_data(page)["logging"]["include_track_names"] is True
    assert validated(preview(page)).include_track_names is True


# ------------------------------------------------------------------ basic vs advanced mode
def test_basic_hides_advanced_fields_and_persists_across_reload(make_page, site):
    page, _ = make_page()
    page.goto(site + "builder/")
    page.wait_for_function("window.__spotiBuilder")
    start_blank(page)
    add_rule(page, "R", "P")
    expect(page.locator("[data-advanced-only]").first).to_be_hidden()
    click_switch(page, "advanced-toggle")
    goto_review(page)
    expect(page.locator("#yaml-edit")).to_be_visible()
    page.reload()
    page.wait_for_function("window.__spotiBuilder && window.__spotiBuilder.ready")
    assert page.locator("#advanced-toggle").is_checked()


# ------------------------------------------------------------------ YAML <-> form bidirectional sync (advanced)
def test_yaml_editor_updates_form(builder):
    goto_review(builder)
    edit = builder.locator("#yaml-edit")
    edit.fill("rules:\n  - name: FromYaml\n    target_playlist: P\n    match:\n      explicit: true\n")
    edit.blur()
    builder.wait_for_function("document.querySelectorAll('#rules > li').length === 1")
    goto_step(builder, 3, "Rules")
    assert rule(builder, 0).get_by_label("Rule name").input_value() == "FromYaml"


def test_form_edit_updates_yaml_editor(builder):
    add_rule(builder, "FromForm", "P")
    goto_review(builder)
    assert "FromForm" in builder.locator("#yaml-edit").input_value()


# ------------------------------------------------------------------ import (advanced)
def test_import_example_config_roundtrips(builder):
    original = (ROOT / "config.example.yaml").read_text(encoding="utf-8")
    goto_review(builder)
    builder.locator("#import summary").click()
    builder.get_by_label("Or paste / drop YAML").fill(original)
    builder.get_by_role("button", name="Load into form").click()
    builder.wait_for_function("document.querySelectorAll('#rules > li').length === 6")
    assert problem_count(builder) == 0
    exported = download_text(builder)
    assert validated(exported) == parse_config(yaml.safe_load(original))


def test_import_bad_yaml(builder):
    goto_review(builder)
    builder.locator("#import summary").click()
    text = builder.get_by_label("Or paste / drop YAML")
    text.fill("rules: [unclosed")
    builder.get_by_role("button", name="Load into form").click()
    assert "Not valid YAML" in builder.locator("#import-status").text_content()


# ------------------------------------------------------------------ autosave + reload recovery + beforeunload guard
def test_autosave_and_reload_recovery(make_page, site):
    page, _ = make_page()
    page.goto(site + "builder/")
    page.wait_for_function("window.__spotiBuilder")
    start_blank(page)
    add_rule(page, "Persisted", "P")
    add_chips(rule(page, 0), "genre_contains", "jazz")
    page.wait_for_timeout(600)  # debounce
    page.reload()
    page.wait_for_function("window.__spotiBuilder && window.__spotiBuilder.ready")
    assert names_in_preview(page) == ["Persisted"]


def test_beforeunload_guard_when_dirty(builder):
    add_rule(builder, "Dirty", "P")
    add_chips(rule(builder, 0), "genre_contains", "x")
    has_guard = builder.evaluate(
        """() => { const ev = new Event('beforeunload', {cancelable: true});
                   window.dispatchEvent(ev);
                   return ev.defaultPrevented || ev.returnValue !== undefined; }"""
    )
    assert has_guard


# ------------------------------------------------------------------ versions (decision 28)
def test_versions_save_list_restore_download_label(builder):
    add_chips(add_rule(builder, "V1", "P1"), "genre_contains", "x")
    goto_review(builder)
    builder.get_by_role("button", name="Save configuration").click()
    builder.wait_for_function("document.getElementById('action-status').textContent.includes('Saved')")

    builder.get_by_role("button", name="Versions").click()
    expect(builder.locator("#versions-list li")).to_have_count(1)
    label = builder.locator("#versions-list input").first
    label.fill("First cut")
    label.blur()

    with builder.expect_download() as info:
        builder.get_by_role("button", name="Download", exact=True).click()
    assert info.value.suggested_filename == "config.yaml"

    # change the draft, then restore the saved version back
    builder.locator("[data-close]").first.click()
    add_chips(add_rule(builder, "V2", "P2"), "genre_contains", "y")
    builder.get_by_role("button", name="Versions").click()
    builder.get_by_role("button", name="Restore").click()
    # confirm dialog (unsaved changes) then confirm restore
    builder.get_by_role("button", name="Restore", exact=True).last.click()
    builder.wait_for_function("document.querySelectorAll('#rules > li').length === 1")
    assert names_in_preview(builder) == ["V1"]


def test_versions_cap_at_five_and_warns(builder):
    for i in range(6):
        goto_step(builder, 3, "Rules")
        if builder.locator("#rules > li").count():
            rule(builder, 0).get_by_role("button", name="Remove rule 1").click()
        add_chips(add_rule(builder, f"R{i}", "P"), "genre_contains", "x")
        goto_review(builder)
        builder.get_by_role("button", name="Save configuration").click()
        if i >= 5:
            # 6th save should trigger the drop-oldest confirm dialog
            builder.get_by_role("button", name="Save and drop oldest").click()
        builder.wait_for_timeout(100)
    builder.get_by_role("button", name="Versions").click()
    expect(builder.locator("#versions-list li")).to_have_count(5)


def test_versions_compare_shows_rule_diff(builder):
    add_chips(add_rule(builder, "V1", "P1"), "genre_contains", "x")
    goto_review(builder)
    builder.get_by_role("button", name="Save configuration").click()
    builder.wait_for_timeout(100)
    add_chips(add_rule(builder, "V2", "P2"), "genre_contains", "y")
    builder.get_by_role("button", name="Versions").click()
    builder.get_by_role("button", name="Compare with current").click()
    expect(builder.locator("#compare-modal")).to_be_visible()
    rows = builder.locator("#compare-rules-table tbody tr")
    assert rows.count() == 2
    statuses = [rows.nth(i).locator(".badge").text_content() for i in range(2)]
    assert "kept" in statuses and "added" in statuses


# ------------------------------------------------------------------ storage blocked banner
def test_storage_blocked_banner(make_page, site):
    page, _ = make_page()
    page.add_init_script(
        "Object.defineProperty(window, 'localStorage', { get() { throw new Error('blocked'); } });"
    )
    page.goto(site + "builder/")
    page.wait_for_function("window.__spotiBuilder")
    expect(page.locator("#storage-banner")).to_be_visible()
    start_blank(page)
    add_rule(page, "StillWorks", "P")
    assert names_in_preview(page) == ["StillWorks"]


# ------------------------------------------------------------------ accessibility basics
def test_every_control_has_an_accessible_name(builder):
    r = add_rule(builder, "R", "P")
    for key in ("artist_in", "language_in", "release_year_before", "explicit", "track_name_contains"):
        add_cond(r, key)
    unnamed = builder.evaluate(
        """() => [...document.querySelectorAll('input, select, textarea, button')]
            .filter(e => e.type !== 'hidden' && e.offsetParent !== null)
            .filter(e => !(e.labels && e.labels.length) && !e.getAttribute('aria-label') && !e.textContent.trim()
                         && !e.getAttribute('aria-labelledby'))
            .map(e => e.outerHTML.slice(0, 80))"""
    )
    assert unnamed == []
    assert builder.locator("html").get_attribute("lang") == "en"


@pytest.mark.skipif(Axe is None, reason="axe-playwright-python not installed")
@pytest.mark.parametrize("theme", ["dark", "light"])
def test_axe_zero_serious_or_critical_with_stepper_and_modal_and_drawer(make_page, site, theme):
    page, _ = make_page()
    page.goto(site + "builder/")
    page.wait_for_function("window.__spotiBuilder")
    start_blank(page)
    if theme == "light":
        page.evaluate("document.documentElement.setAttribute('data-theme', 'light')")
    add_chips(add_rule(page, "A", "P"), "genre_contains", "x")
    goto_review(page)
    page.get_by_role("button", name="Save configuration").click()
    page.wait_for_timeout(100)
    page.get_by_role("button", name="Versions").click()
    expect(page.locator("#versions-drawer")).to_be_visible()
    page.wait_for_timeout(250)  # let the overlay's fade-in (--motion-base, 200ms) finish before scanning colors
    axe = Axe()
    results = axe.run(page)
    serious = [v for v in results.response["violations"] if v.get("impact") in ("serious", "critical")]
    assert not serious, json.dumps([{"id": v["id"], "impact": v["impact"], "help": v["help"]} for v in serious], indent=2)


# ------------------------------------------------------------------ full keyboard-only walkthrough (decision 30)
def test_keyboard_only_walkthrough_basics_to_review_and_save(make_page, site):
    page, _ = make_page()
    page.goto(site + "builder/")
    page.wait_for_function("window.__spotiBuilder")
    page.get_by_role("button", name="Start blank").focus()
    page.keyboard.press("Enter")
    expect(page.locator("#wizard")).to_be_visible()

    page.get_by_label("Default days threshold").focus()
    page.keyboard.type("10")
    page.keyboard.press("Tab")

    page.locator("#step-tab-3").focus()
    page.keyboard.press("Enter")
    page.get_by_role("button", name="Add rule").focus()
    page.keyboard.press("Enter")
    page.get_by_label("Rule name").focus()
    page.keyboard.type("Keyboard rule")
    page.keyboard.press("Tab")
    page.keyboard.type("Kb Playlist")

    r = page.locator("#rules > li").last
    r.locator("select[id$='-add-cond']").focus()
    page.keyboard.press("ArrowDown")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Tab")
    page.keyboard.press("Enter")  # Add condition
    page.keyboard.type("jazz")
    page.keyboard.press("Enter")

    page.locator("#step-tab-4").focus()
    page.keyboard.press("Enter")
    expect(page.locator("#step-4")).to_be_visible()
    page.get_by_role("button", name="Save configuration").focus()
    page.keyboard.press("Enter")
    page.wait_for_function("document.getElementById('action-status').textContent.includes('Saved')")


# ------------------------------------------------------------------ screenshots
STEPS = [(1, "basics"), (2, "languages"), (3, "rules"), (4, "review")]


@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("width,height", [(375, 812), (1280, 900)])
@pytest.mark.parametrize("step,name", STEPS)
def test_step_screenshots(make_page, site, step, name, width, height, theme):
    page, _ = make_page(width=width, height=height)
    page.goto(site + "builder/")
    page.wait_for_function("window.__spotiBuilder")
    start_blank(page)
    add_chips(add_rule(page, "Example rule", "Example Playlist"), "genre_contains", "jazz")
    if theme == "light":
        page.evaluate("document.documentElement.setAttribute('data-theme', 'light')")
    goto_step(page, step, name)
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SHOTS / f"site-configure-{name}-{theme}-{width}.png"), full_page=True)
    assert (SHOTS / f"site-configure-{name}-{theme}-{width}.png").stat().st_size > 5_000


# ------------------------------------------------------------------ PWA / service worker (cache version bumped for this rebuild)
def test_manifest_present(make_page, site):
    page, _ = make_page()
    page.goto(site + "builder/")
    href = page.locator("link[rel=manifest]").get_attribute("href")
    resp = page.request.get(page.evaluate("(h) => new URL(h, location.href).href", href))
    assert resp.ok
    manifest = json.loads(resp.text())
    assert manifest["display"] == "standalone"


def test_service_worker_registers(make_page, site):
    page, _ = make_page()
    page.goto(site + "builder/")
    page.wait_for_function("window.__spotiBuilder")
    scope = page.evaluate("navigator.serviceWorker.ready.then(r => r.scope)")
    assert scope == site
