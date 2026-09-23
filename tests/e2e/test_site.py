"""Browser tests for the marketing site shell/Home/Setup/404/kitchen-sink (Master decisions 22-30).
Run: python -m pytest tests/e2e -q -m e2e

Cross-browser coverage follows SPOTISORT_BROWSERS (see conftest.py's `available_browsers` fixture):
"auto" (default) tries chromium/firefox/webkit and silently skips whichever can't launch on this machine.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")

try:
    from axe_playwright_python.sync_playwright import Axe
except ImportError:  # optional dev dependency
    Axe = None

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
SHOTS = DOCS / "screenshots"

PAGES = {
    "home": "index.html",
    "setup": "setup/",
    "404": "404.html",
    "kitchen-sink": "assets/kitchen-sink.html",
}

# Files that make up the shell + Home (decision 30: total transferred JS+CSS < 250 KB, excluding vendored js-yaml).
BUDGET_FILES = [
    "assets/tokens.css", "assets/components.css", "assets/site.css",
    "assets/ui.js", "assets/shell.js", "app.js",
]
BUDGET_LIMIT_BYTES = 250 * 1024


# ------------------------------------------------------------------------------------------- helpers
def _no_console_errors(page):
    """Collect genuine JS console errors, ignoring the browser's own network-resource-load log lines
    (e.g. a blocked/rate-limited GitHub API request, which the star-count fetch is designed to fail
    silently on - see shell.js loadStars()). A failed network request is not, by itself, an application bug."""
    errors = []
    page.on("console", lambda m: (m.type == "error" and "Failed to load resource" not in m.text) and errors.append(m.text))
    page.on("pageerror", lambda e: errors.append(str(e)))
    return errors


def _for_each_browser(available_browsers, fn):
    if not available_browsers:
        pytest.skip("no browser could be launched on this machine")
    for name, browser in available_browsers.items():
        fn(name, browser)


# ------------------------------------------------------------------------------------------- budget
def test_shell_and_home_byte_budget():
    total = sum((DOCS / f).stat().st_size for f in BUDGET_FILES)
    assert total < BUDGET_LIMIT_BYTES, f"{total} bytes >= {BUDGET_LIMIT_BYTES} budget: {BUDGET_FILES}"


# ------------------------------------------------------------------------------------------- fork link derivation (unit, via URL override)
@pytest.mark.parametrize(
    "hostname,pathname,expect_url",
    [
        ("vishnu-drx.github.io", "/SpotiSort/", None),
        ("someone-else.github.io", "/SpotiSort/", "https://github.com/someone-else/SpotiSort"),
        ("someone-else.github.io", "/SpotiSort/setup/", "https://github.com/someone-else/SpotiSort"),
        ("localhost", "/", None),
        ("example.com", "/SpotiSort/", None),
    ],
)
def test_fork_link_derivation_real(site_page, site, hostname, pathname, expect_url):
    page, _ = site_page()
    page.goto(site)
    page.wait_for_function("window.SpotiShell")
    result = page.evaluate(
        "([h, p]) => window.SpotiShell.deriveFork({hostname: h, pathname: p})",
        [hostname, pathname],
    )
    if expect_url is None:
        assert result is None
    else:
        assert result["url"] == expect_url


# ------------------------------------------------------------------------------------------- star count fails silently
def test_star_count_fails_silently_when_api_blocked(site_page, site):
    page, ctx = site_page()
    ctx.route("https://api.github.com/**", lambda route: route.abort())
    # the browser itself logs the aborted request to the console (net::ERR_FAILED) - that's expected and not
    # a bug; what matters is our own JS never throws or logs an *application* error for it.
    errors = _no_console_errors(page)
    page.goto(site)
    page.wait_for_selector("#site-star", state="attached")
    page.wait_for_timeout(300)  # let the aborted fetch's rejection settle
    assert page.locator("#site-star").text_content() == ""  # no stars shown, no crash
    assert not errors, errors


# ------------------------------------------------------------------------------------------- pages load, no console errors, no horizontal overflow
@pytest.mark.parametrize("page_name,path", list(PAGES.items()))
@pytest.mark.parametrize("width", [375, 768, 1280])
def test_page_loads_cleanly(site_page, site, page_name, path, width):
    page, _ = site_page(width=width, height=900)
    errors = _no_console_errors(page)
    page.goto(site + path)
    page.wait_for_load_state("networkidle")
    overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert overflow <= 0, f"{page_name} at {width}px overflows by {overflow}px"
    assert not errors, f"{page_name}: {errors}"


def test_pages_load_across_available_browsers(available_browsers, site):
    def check(name, browser):
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        errors = _no_console_errors(page)
        page.goto(site)
        page.wait_for_load_state("networkidle")
        assert page.title() != "", f"{name}: empty title"
        assert not errors, f"{name}: {errors}"
        ctx.close()

    _for_each_browser(available_browsers, check)


# ------------------------------------------------------------------------------------------- keyboard-only walkthrough
def test_keyboard_skip_link_and_theme_toggle_persist(site_page, site):
    page, _ = site_page()
    page.goto(site)
    page.wait_for_function("window.SpotiUI")
    page.keyboard.press("Tab")  # first focus stop should be the skip link
    active = page.evaluate("document.activeElement.className")
    assert "skip-link" in active
    page.keyboard.press("Enter")
    assert page.evaluate("document.activeElement.id") == "main" or page.url.endswith("#main")

    # theme toggle: find it, activate via keyboard, confirm persistence across reload
    toggle = page.locator("[data-theme-toggle]")
    toggle.focus()
    before = page.evaluate("document.documentElement.getAttribute('data-theme')")
    page.keyboard.press("Enter")
    after = page.evaluate("document.documentElement.getAttribute('data-theme')")
    assert after != before
    page.reload()
    page.wait_for_function("window.SpotiUI")
    assert page.evaluate("document.documentElement.getAttribute('data-theme')") == after


def test_mobile_menu_keyboard_and_escape(site_page, site):
    page, _ = site_page(width=375, height=812)
    page.goto(site)
    page.wait_for_function("window.SpotiUI")
    btn = page.locator("#site-menu-btn")
    assert btn.get_attribute("aria-expanded") == "false"
    btn.click()
    assert btn.get_attribute("aria-expanded") == "true"
    page.keyboard.press("Escape")
    assert btn.get_attribute("aria-expanded") == "false"


def test_tooltip_on_focus_and_escape(site_page, site):
    page, _ = site_page()
    page.goto(site + "assets/kitchen-sink.html")
    page.wait_for_function("window.SpotiUI")
    help_btn = page.locator(".help").first
    help_btn.focus()
    tip_id = help_btn.get_attribute("data-tip-id")
    assert tip_id, "tooltip should be wired on focus"
    tip = page.locator("#" + tip_id)
    assert tip.is_visible()
    page.keyboard.press("Escape")
    assert not tip.is_visible()


def test_copy_buttons_present_on_setup(site_page, site):
    page, _ = site_page()
    page.goto(site + "setup/")
    page.wait_for_function("window.SpotiUI")
    buttons = page.locator(".code-copy")
    assert buttons.count() >= 5  # one per command/URL block


# ------------------------------------------------------------------------------------------- axe-core: zero serious/critical
@pytest.mark.skipif(Axe is None, reason="axe-playwright-python not installed")
@pytest.mark.parametrize("page_name,path", list(PAGES.items()))
@pytest.mark.parametrize("theme", ["dark", "light"])
def test_axe_zero_serious_or_critical(site_page, site, page_name, path, theme):
    page, _ = site_page()
    page.goto(site + path)
    page.wait_for_load_state("networkidle")
    if theme == "light":
        page.evaluate("document.documentElement.setAttribute('data-theme', 'light')")
    axe = Axe()
    results = axe.run(page)
    serious = [v for v in results.response["violations"] if v.get("impact") in ("serious", "critical")]
    assert not serious, json.dumps([{"id": v["id"], "impact": v["impact"], "help": v["help"]} for v in serious], indent=2)


@pytest.mark.skipif(Axe is None, reason="axe-playwright-python not installed")
def test_axe_home_with_mobile_menu_open(site_page, site):
    page, _ = site_page(width=375, height=812)
    page.emulate_media(reduced_motion="reduce")  # avoid scanning mid-transition (opacity/transform in flight)
    page.goto(site)
    page.wait_for_function("window.SpotiUI")
    page.locator("#site-menu-btn").click()
    axe = Axe()
    results = axe.run(page)
    serious = [v for v in results.response["violations"] if v.get("impact") in ("serious", "critical")]
    assert not serious, json.dumps([{"id": v["id"], "impact": v["impact"]} for v in serious], indent=2)


# ------------------------------------------------------------------------------------------- committed screenshots
@pytest.mark.parametrize("page_name,path", list(PAGES.items()))
@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("width", [375, 1280])
def test_committed_screenshots(site_page, site, page_name, path, theme, width):
    if page_name == "kitchen-sink" and theme == "light":
        pytest.skip("kitchen-sink dark/light is a manual toggle in-page, not part of the committed marketing set")
    page, _ = site_page(width=width, height=900 if width == 1280 else 812, color_scheme=theme)
    page.goto(site + path)
    page.wait_for_load_state("networkidle")
    SHOTS.mkdir(parents=True, exist_ok=True)
    out = SHOTS / f"site-{page_name}-{theme}-{width}.png"
    page.screenshot(path=str(out), full_page=True)
    assert out.stat().st_size > 5_000
