"""Local dashboard server: `python -m src.dashboard [--port 8787] [--logs logs] [--no-browser]`.

Serves the Pages site (``docs/``) at ``/`` and the run-artifact folder read-only at ``/data/`` so the dashboard can
show your real data without anything leaving the machine. Standard library only.

Safety properties (all covered by tests/test_dashboard_server.py):
- binds 127.0.0.1 only (never 0.0.0.0) and rejects requests whose ``Host`` header is not loopback (DNS rebinding);
- GET and HEAD only, every other method answers 405;
- ``/data/<name>`` serves a single ``*.json`` / ``*.md`` file that lives directly in the logs folder: no sub-folders,
  no traversal, no symlink escapes, no directory listing;
- ``/data`` responses are ``Cache-Control: no-store``.
"""

from __future__ import annotations

import argparse
import mimetypes
import re
import sys
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "docs"
DEFAULT_PORT = 8787
HOST = "127.0.0.1"
DATA_SUFFIXES = {".json": "application/json; charset=utf-8", ".md": "text/markdown; charset=utf-8"}
_HOST_RE = re.compile(r"^(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$", re.IGNORECASE)
_TYPES = {
    ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8", ".html": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8", ".webmanifest": "application/manifest+json",
    ".svg": "image/svg+xml", ".png": "image/png", ".md": "text/markdown; charset=utf-8",
}


def _within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "SpotiSortDashboard"
    protocol_version = "HTTP/1.1"
    docs_dir: Path = DOCS_DIR
    logs_dir: Path = Path("logs")

    # ------------------------------------------------------------------ plumbing
    def log_message(self, fmt: str, *args) -> None:  # keep the terminal quiet
        pass

    def _send(self, status: int, body: bytes = b"", ctype: str = "text/plain; charset=utf-8", *,
              cache: str = "no-cache", extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD" and body:
            self.wfile.write(body)

    def _error(self, status: int, cache: str = "no-cache", extra: dict[str, str] | None = None) -> None:
        self._send(status, (HTTPStatus(status).phrase + "\n").encode(), cache=cache, extra=extra)

    def _method_not_allowed(self) -> None:
        self._error(405, extra={"Allow": "GET, HEAD"})

    do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _method_not_allowed

    # ------------------------------------------------------------------ routing
    def do_HEAD(self) -> None:
        self._route()

    def do_GET(self) -> None:
        self._route()

    def _route(self) -> None:
        if not _HOST_RE.match(self.headers.get("Host", "")):
            return self._error(403)
        raw = urlsplit(self.path).path
        if "\x00" in raw or "\\" in raw:
            return self._error(400)
        path = unquote(raw)
        if "\x00" in path or "\\" in path or not path.startswith("/"):
            return self._error(400)
        if path == "/data" or path.startswith("/data/"):
            return self._serve_data(path[len("/data/"):] if path != "/data" else "")
        return self._serve_static(path)

    def _serve_data(self, name: str) -> None:
        nc = "no-store"
        if not name or "/" in name or name.startswith(".") or name in (".", ".."):
            return self._error(404, nc)
        suffix = Path(name).suffix.lower()
        if suffix not in DATA_SUFFIXES:
            return self._error(404, nc)
        base = self.logs_dir.resolve()
        target = (base / name).resolve()
        if target.parent != base or not target.is_file():
            return self._error(404, nc)
        try:
            body = target.read_bytes()
        except OSError:
            return self._error(404, nc)
        self._send(200, body, DATA_SUFFIXES[suffix], cache=nc)

    def _serve_static(self, path: str) -> None:
        base = self.docs_dir.resolve()
        parts = [p for p in path.split("/") if p]
        if any(p in (".", "..") or p.startswith(".") for p in parts):
            return self._error(404)
        target = (base.joinpath(*parts)).resolve()
        if not _within(target, base):
            return self._error(404)
        if target.is_dir():
            if not path.endswith("/"):
                return self._send(301, b"", extra={"Location": path + "/"})
            target = target / "index.html"
        if not target.is_file():
            return self._error(404)
        try:
            body = target.read_bytes()
        except OSError:
            return self._error(404)
        ctype = _TYPES.get(target.suffix.lower()) or mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self._send(200, body, ctype)


class ExclusiveServer(ThreadingHTTPServer):
    """Never share a port with another program (on Windows, SO_REUSEADDR would let two servers bind the same port)."""

    allow_reuse_address = False

    def server_bind(self) -> None:
        import socket

        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def make_server(logs_dir: str | Path = "logs", port: int = DEFAULT_PORT, docs_dir: str | Path = DOCS_DIR) -> ThreadingHTTPServer:
    """Build (but do not start) the loopback-only server. ``port=0`` picks a free port."""
    handler = type("BoundDashboardHandler", (DashboardHandler,), {
        "docs_dir": Path(docs_dir), "logs_dir": Path(logs_dir),
    })
    return ExclusiveServer((HOST, port), handler)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.dashboard", description="Serve the SpotiSort dashboard on localhost with your logs/ data.")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port on 127.0.0.1 (default {DEFAULT_PORT})")
    ap.add_argument("--logs", default="logs", help="folder holding the run artifacts (default: logs)")
    ap.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    args = ap.parse_args(argv)
    try:
        server = make_server(args.logs, args.port)
    except OSError as exc:
        print(f"Could not listen on {HOST}:{args.port}: {exc}", file=sys.stderr)
        return 1
    url = f"http://{HOST}:{server.server_address[1]}/dashboard/?source=local"
    print(f"SpotiSort dashboard: {url}")
    print(f"Serving {Path(args.logs).resolve()} read-only at /data/ (Ctrl+C to stop)")
    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001 - opening a browser is best-effort
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
