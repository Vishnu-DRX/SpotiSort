"""Fixtures for the Pages config-builder browser tests (auto-skip without playwright / a browser)."""

from __future__ import annotations

import functools
import http.server
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
def browser():
    if sync_playwright is None:
        pytest.skip("playwright is not installed")
    with sync_playwright() as pw:
        last = None
        for kwargs in ({}, {"channel": "msedge"}, {"channel": "chrome"}):
            try:
                b = pw.chromium.launch(**kwargs)
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
