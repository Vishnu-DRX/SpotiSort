"""`.env` handling and the PKCE login helpers (offline)."""

from __future__ import annotations

import base64
import hashlib
import re
import urllib.parse

import pytest

from src import spotify_client as sc


def test_parse_env_basics():
    text = "# c\n\nA=1\nB = two \nC=\"quoted value\"\nD='single'\nexport E=5\nnoequals\nF=a=b\n"
    assert sc.parse_env(text) == {"A": "1", "B": "two", "C": "quoted value", "D": "single", "E": "5", "F": "a=b"}


def test_load_env_existing_vars_win(tmp_path):
    p = tmp_path / ".env"
    p.write_text("A=from_file\nB=from_file\n", encoding="utf-8")
    env = {"A": "from_env"}
    assert sc.load_env(p, env) is True
    assert env == {"A": "from_env", "B": "from_file"}


def test_load_env_missing_file_is_fine(tmp_path):
    env: dict[str, str] = {}
    assert sc.load_env(tmp_path / "nope", env) is False
    assert env == {}


def test_set_env_value_replaces_and_preserves_other_lines(tmp_path):
    p = tmp_path / ".env"
    p.write_text("# keep\nSPOTIFY_CLIENT_ID=cid\nSPOTIFY_REFRESH_TOKEN=old\nOTHER=1\n", encoding="utf-8")
    sc.set_env_value(p, "SPOTIFY_REFRESH_TOKEN", "new")
    assert p.read_text(encoding="utf-8") == "# keep\nSPOTIFY_CLIENT_ID=cid\nSPOTIFY_REFRESH_TOKEN=new\nOTHER=1\n"


def test_set_env_value_appends_when_absent_or_file_missing(tmp_path):
    p = tmp_path / ".env"
    sc.set_env_value(p, "K", "v")
    assert p.read_text(encoding="utf-8") == "K=v\n"
    sc.set_env_value(p, "K2", "v2")
    assert p.read_text(encoding="utf-8") == "K=v\nK2=v2\n"


def test_pkce_pair_is_valid_s256():
    verifier, challenge = sc.pkce_pair()
    assert 43 <= len(verifier) <= 128 and re.fullmatch(r"[A-Za-z0-9_-]+", verifier)
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert challenge == expected and "=" not in challenge


def test_pkce_pairs_are_unique():
    assert sc.pkce_pair()[0] != sc.pkce_pair()[0]


def test_authorize_url_contents():
    url = sc.build_authorize_url("my-client", "CHAL", "STATE")
    parsed = urllib.parse.urlparse(url)
    q = urllib.parse.parse_qs(parsed.query)
    assert parsed.netloc == "accounts.spotify.com"
    assert q["client_id"] == ["my-client"]
    assert q["code_challenge_method"] == ["S256"] and q["code_challenge"] == ["CHAL"]
    assert q["redirect_uri"] == ["http://127.0.0.1:8888/callback"]
    assert q["state"] == ["STATE"] and q["response_type"] == ["code"]
    assert set(q["scope"][0].split()) == set(sc.SCOPES.split()) and len(q["scope"][0].split()) == 6
    assert "client_secret" not in q and "code_verifier" not in q


def test_run_setup_writes_only_refresh_token_and_prints_no_secret(tmp_path, monkeypatch, capsys):
    env = tmp_path / ".env"
    env.write_text("SPOTIFY_CLIENT_ID=cid\n", encoding="utf-8")
    seen = {}

    def fake_capture(state, timeout, on_ready):
        on_ready()
        seen["state"] = state
        return "AUTH-CODE-123"

    class Resp:
        status_code = 200
        text = ""

        def json(self):
            return {"refresh_token": "RT-super-secret-value", "scope": sc.SCOPES, "access_token": "AT-secret"}

    class Session:
        def post(self, url, data, timeout):
            seen["url"], seen["data"] = url, data
            return Resp()

    monkeypatch.setattr(sc, "_capture_code", fake_capture)
    sc.run_setup("cid", env, session=Session(), open_browser=False)
    out = capsys.readouterr()
    assert "RT-super-secret-value" not in out.out + out.err
    assert "AT-secret" not in out.out + out.err
    assert "SPOTIFY_REFRESH_TOKEN=RT-super-secret-value" in env.read_text(encoding="utf-8")
    assert env.read_text(encoding="utf-8").count("=") == 2
    d = seen["data"]
    assert seen["url"] == sc.TOKEN_URL and d["grant_type"] == "authorization_code"
    assert d["code"] == "AUTH-CODE-123" and "client_secret" not in d
    # verifier really is the pre-image of the challenge sent in the authorize URL
    assert 43 <= len(d["code_verifier"]) <= 128


def test_run_setup_failure_message_has_no_code_or_verifier(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "_capture_code", lambda s, t, r: (r(), "THE-CODE-XYZ")[1])

    class Resp:
        status_code = 400
        text = "bad code=THE-CODE-XYZ"

    class Session:
        def post(self, url, data, timeout):
            self.verifier = data["code_verifier"]
            Resp.text = f"invalid code THE-CODE-XYZ verifier {data['code_verifier']}"
            return Resp()

    with pytest.raises(sc.SpotifyError) as exc:
        sc.run_setup("cid", tmp_path / ".env", session=Session(), open_browser=False)
    assert "THE-CODE-XYZ" not in str(exc.value)


def test_smoke_refuses_without_live_flag(monkeypatch, capsys):
    monkeypatch.delenv("SPOTISORT_LIVE", raising=False)
    assert sc.main(["--smoke", "--env", "definitely-missing.env"]) == 2
    assert "SPOTISORT_LIVE=1" in capsys.readouterr().err


def test_setup_without_client_id_fails_cleanly(monkeypatch, capsys):
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    assert sc.main(["--setup", "--env", "definitely-missing.env"]) == 2


# ---- the real localhost redirect server (state check is a security control)


def _run_capture(query: str, timeout: float = 5):
    import threading
    import urllib.request

    outcome = {}

    def serve():
        try:
            outcome["code"] = sc._capture_code("GOODSTATE", timeout, lambda: None)
        except sc.SpotifyError as exc:
            outcome["error"] = str(exc)

    t = threading.Thread(target=serve)
    t.start()
    import time

    for _ in range(50):  # wait for the socket to open
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{sc.REDIRECT_PORT}/callback?{query}", timeout=2).read()
            break
        except OSError:
            time.sleep(0.1)
    t.join(10)
    return outcome


def test_capture_code_happy_path():
    assert _run_capture("code=THECODE&state=GOODSTATE") == {"code": "THECODE"}


def test_capture_code_rejects_state_mismatch():
    out = _run_capture("code=THECODE&state=EVIL")
    assert "state mismatch" in out["error"] and "code" not in out


def test_capture_code_reports_denied_authorization():
    assert "denied" in _run_capture("error=access_denied&state=GOODSTATE")["error"]


def test_capture_code_rejects_missing_code():
    assert "no code" in _run_capture("state=GOODSTATE")["error"]


def test_capture_code_times_out():
    import threading

    out = {}

    def serve():
        try:
            sc._capture_code("S", 0.5, lambda: None)
        except sc.SpotifyError as exc:
            out["error"] = str(exc)

    t = threading.Thread(target=serve)
    t.start()
    t.join(10)
    assert "timed out" in out["error"]
