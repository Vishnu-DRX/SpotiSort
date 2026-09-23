"""Fixtures for the Pages config-builder browser tests (auto-skip without playwright / a browser)."""

from __future__ import annotations

import functools
import http.server
import os
import threading
from pathlib import Path

import pytest

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # playwright is an optional dev dependency
    sync_playwright = None

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
BASE_PATH = "/SpotiSort/"  # mimic the GitHub Pages project-site base path


class _Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".webmanifest": "application/manifest+json",
        ".js": "text/javascript",
        ".css": "text/css",
        ".png": "image/png",
    }

    def translate_path(self, path):
        if path.startswith(BASE_PATH):
            path = "/" + path[len(BASE_PATH):]
        elif path == BASE_PATH.rstrip("/"):
            path = "/"
        else:
            return str(DOCS / "__not_found__")
        return super().translate_path(path)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture(scope="session")
def site():
    handler = functools.partial(_Handler, directory=str(DOCS))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}{BASE_PATH}"
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="session")
def playwright_instance():
    # The single sync_playwright() context for the whole test session - playwright's sync API errors if you
    # try to open a second one nested inside the first, so every fixture that needs a browser (this file's
    # `browser`, and `available_browsers` below for the multi-browser site tests) shares this one instance.
    if sync_playwright is None:
        pytest.skip("playwright is not installed")
    with sync_playwright() as pw:
        yield pw


@pytest.fixture(scope="session")
def browser(playwright_instance):
    last = None
    for kwargs in ({}, {"channel": "msedge"}, {"channel": "chrome"}):
        try:
            b = playwright_instance.chromium.launch(**kwargs)
            break
        except Exception as exc:  # noqa: BLE001 - any launch failure means "unavailable"
            last = exc
    else:
        pytest.skip(f"no chromium-family browser available: {str(last).splitlines()[0]}")
    yield b
    b.close()


@pytest.fixture
def make_page(browser, site):
    """Factory: open a fresh isolated context and return (page, context)."""
    contexts = []

    def _make(width=1280, height=900, **ctx_kwargs):
        ctx = browser.new_context(
            viewport={"width": width, "height": height},
            accept_downloads=True,
            permissions=["clipboard-read", "clipboard-write"],
            **ctx_kwargs,
        )
        contexts.append(ctx)
        page = ctx.new_page()
        return page, ctx

    yield _make
    for c in contexts:
        c.close()


@pytest.fixture
def builder(make_page, site):
    page, _ = make_page()
    page.goto(site + "builder/")
    page.wait_for_function("window.__spotiBuilder && window.__spotiBuilder.ready")
    return page


# ---------------------------------------------------------------------------------- multi-browser (site tests)
# SPOTISORT_BROWSERS controls which browser families the site tests (tests/e2e/test_site.py) run against:
#   "auto" (default) = whichever of chromium/firefox/webkit can actually launch on this machine
#   a comma list, e.g. "chromium,firefox" = only try those (CI sets this after installing all three)
def _launch_one(pw, name):
    """Try to launch one browser family, returning None (never raising) if it isn't available."""
    if name == "chromium":
        for kwargs in ({}, {"channel": "msedge"}, {"channel": "chrome"}):
            try:
                return pw.chromium.launch(**kwargs)
            except Exception:  # noqa: BLE001
                continue
        return None
    try:
        return getattr(pw, name).launch()
    except Exception:  # noqa: BLE001
        return None


@pytest.fixture(scope="session")
def available_browsers(playwright_instance):
    """{name: Browser} for every browser family that could be launched (soft-skips missing ones)."""
    wanted = os.environ.get("SPOTISORT_BROWSERS", "auto")
    names = ["chromium", "firefox", "webkit"] if wanted == "auto" else [n.strip() for n in wanted.split(",") if n.strip()]
    out = {}
    for name in names:
        b = _launch_one(playwright_instance, name)
        if b is not None:
            out[name] = b
    yield out
    for b in out.values():
        b.close()


@pytest.fixture
def site_page(available_browsers, site):
    """Factory: (browser_name) -> (page, context) against `site`, on any one available browser."""
    contexts = []

    def _make(browser_name=None, width=1280, height=900, **ctx_kwargs):
        if not available_browsers:
            pytest.skip("no browser could be launched on this machine")
        name = browser_name or next(iter(available_browsers))
        if browser_name and browser_name not in available_browsers:
            pytest.skip(f"{browser_name} is not available on this machine")
        ctx = available_browsers[name].new_context(viewport={"width": width, "height": height}, **ctx_kwargs)
        contexts.append(ctx)
        return ctx.new_page(), ctx

    yield _make
    for c in contexts:
        c.close()
