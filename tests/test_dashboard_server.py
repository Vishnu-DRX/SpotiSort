"""The local dashboard server: loopback only, read-only, JSON/MD only, no traversal."""

from __future__ import annotations

import http.client
import threading

import pytest

from src.dashboard import make_server


@pytest.fixture
def srv(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "runs.json").write_text('{"runs": []}', encoding="utf-8")
    (logs / "backtest-detail.md").write_text("# detail", encoding="utf-8")
    (logs / "secret.txt").write_text("nope", encoding="utf-8")
    (logs / ".env").write_text("TOKEN=1", encoding="utf-8")
    (logs / "sub").mkdir()
    (logs / "sub" / "x.json").write_text("{}", encoding="utf-8")
    (tmp_path / "outside.json").write_text('{"leak": true}', encoding="utf-8")
    docs = tmp_path / "docs"
    (docs / "dashboard").mkdir(parents=True)
    (docs / "index.html").write_text("<h1>home</h1>", encoding="utf-8")
    (docs / "dashboard" / "index.html").write_text("<h1>dash</h1>", encoding="utf-8")
    (docs / "app.js").write_text("1", encoding="utf-8")
    server = make_server(logs, 0, docs)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield server
    server.shutdown()
    server.server_close()


def req(server, method, path, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    c.request(method, path, headers=headers or {})
    r = c.getresponse()
    body = r.read()
    c.close()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, body


def test_binds_loopback_only(srv):
    assert srv.server_address[0] == "127.0.0.1"


def test_serves_data_json_and_md_no_store(srv):
    status, h, body = req(srv, "GET", "/data/runs.json")
    assert status == 200 and body == b'{"runs": []}'
    assert h["cache-control"] == "no-store" and h["content-type"].startswith("application/json")
    status, h, _ = req(srv, "GET", "/data/backtest-detail.md")
    assert status == 200 and h["content-type"].startswith("text/markdown")


def test_head_has_no_body(srv):
    status, h, body = req(srv, "HEAD", "/data/runs.json")
    assert status == 200 and body == b"" and h["content-length"] == "12"


@pytest.mark.parametrize("path", [
    "/data/secret.txt", "/data/.env", "/data/", "/data", "/data/sub/x.json", "/data/sub", "/data/missing.json",
    "/data/../outside.json", "/data/%2e%2e/outside.json", "/data/..%2foutside.json", "/data/%2e%2e%2foutside.json",
    "/data/..%5coutside.json", "/data/runs.json%00.txt", "/data//runs.json", "/data/runs.json/",
])
def test_data_refuses_everything_else(srv, path):
    status, h, body = req(srv, "GET", path)
    assert status in (400, 404), (path, status)
    assert b"leak" not in body and b"TOKEN" not in body and b"nope" not in body


@pytest.mark.parametrize("path", ["/../outside.json", "/%2e%2e/outside.json", "/dashboard/../../outside.json", "/..%2foutside.json", "/.env"])
def test_static_no_traversal(srv, path):
    status, _, body = req(srv, "GET", path)
    assert status in (400, 404) and b"leak" not in body


def test_static_docs_and_index(srv):
    assert req(srv, "GET", "/")[2] == b"<h1>home</h1>"
    assert req(srv, "GET", "/dashboard/")[2] == b"<h1>dash</h1>"
    status, h, _ = req(srv, "GET", "/dashboard")
    assert status == 301 and h["location"] == "/dashboard/"
    status, h, _ = req(srv, "GET", "/app.js")
    assert status == 200 and h["content-type"].startswith("text/javascript")
    assert req(srv, "GET", "/nothing.html")[0] == 404


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
def test_only_get_and_head(srv, method):
    for path in ("/data/runs.json", "/", "/dashboard/"):
        status, h, _ = req(srv, method, path)
        assert status == 405 and h["allow"] == "GET, HEAD"


def test_non_loopback_host_header_rejected(srv):
    assert req(srv, "GET", "/data/runs.json", {"Host": "evil.example"})[0] == 403
    assert req(srv, "GET", "/data/runs.json", {"Host": "localhost:1234"})[0] == 200


def test_missing_logs_dir_is_404_not_crash(tmp_path):
    server = make_server(tmp_path / "nope", 0, tmp_path)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert req(server, "GET", "/data/runs.json")[0] == 404
    finally:
        server.shutdown()
        server.server_close()
