"""Thin Spotify Web API client: .env loading, PKCE login, refresh-token auth, paging, guarded writes.

All Spotify HTTP goes through ``SpotifyClient._request``. Request shapes are the ones verified live
(spotify-api-explore/FINDINGS.md §4/§6, build spec "Verified write shapes"):

- add to playlist      POST   /playlists/{id}/items   json {"uris": [...]}            max 100
- remove from playlist DELETE /playlists/{id}/items   json {"items": [{"uri": ...}]}  max 100
- save / remove liked  PUT / DELETE /me/library?uris=a,b   (query string, never body)  max 40
- contains             GET    /me/library/contains?uris=a,b                            max 40

Safety: every write refuses to run while ``dry_run`` is True (default), only ``spotify:track:`` URIs
are ever sent to /me/library, and tokens never reach logs or exception messages.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import http.server
import logging
import os
import re
import secrets
import sys
import threading
import time
import urllib.parse
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

import requests

from .models import Artist, Playlist, Track

log = logging.getLogger("spotisort")

API_BASE = "https://api.spotify.com/v1"
AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
REDIRECT_PORT = 8888
REDIRECT_URI = f"http://127.0.0.1:{REDIRECT_PORT}/callback"
SCOPES = (
    "user-library-read user-library-modify playlist-read-private "
    "playlist-read-collaborative playlist-modify-private playlist-modify-public"
)

LIBRARY_BATCH = 40  # /me/library add/remove/contains
PLAYLIST_BATCH = 100  # playlist items add/remove
SAVED_PAGE = 50
PLAYLISTS_PAGE = 50
PLAYLIST_ITEMS_PAGE = 100
MAX_RETRIES = 5
MAX_RETRY_AFTER = 300  # seconds; a longer Retry-After is surfaced as an error, not slept
REQUEST_TIMEOUT = 30

TRACK_URI_RE = re.compile(r"^spotify:track:[0-9A-Za-z]{22}$")
PLAYLIST_ID_RE = re.compile(r"^[0-9A-Za-z]{1,64}$")
ENV_REFRESH_KEY = "SPOTIFY_REFRESH_TOKEN"

_SCRUB_PATTERNS = (
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(
        r"(?i)((?:access_token|refresh_token|client_secret|code_verifier|code)"
        r"[\"']?\s*[=:]\s*[\"']?)[^&\"'\s,}]+"
    ),
)


class SpotifyError(RuntimeError):
    """A failed Spotify/token call. Messages are always scrubbed of secrets."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class DryRunError(SpotifyError):
    """A write was attempted while dry_run=True."""


# ---------------------------------------------------------------- .env handling


def parse_env(text: str) -> dict[str, str]:
    """Tiny KEY=VALUE parser: ``#`` comments, blank lines, optional matching quotes."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def load_env(path: str | Path = ".env", environ: dict[str, str] | None = None) -> bool:
    """Load ``path`` into ``environ`` (default ``os.environ``). Existing variables win.

    Returns True if the file existed. Never logs values.
    """
    environ = os.environ if environ is None else environ
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return False
    for key, value in parse_env(text).items():
        environ.setdefault(key, value)
    return True


def set_env_value(path: str | Path, key: str, value: str) -> None:
    """Set ``key`` in a .env file, keeping every other line untouched."""
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out, done = [], False
    for line in lines:
        if line.strip().split("=", 1)[0].strip() == key and "=" in line:
            if not done:
                out.append(f"{key}={value}")
                done = True
        else:
            out.append(line)
    if not done:
        out.append(f"{key}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- redaction


def scrub(text: str, secret_values: Iterable[str | None] = ()) -> str:
    """Remove known secret values and token-shaped fragments from ``text``."""
    for secret in secret_values:
        if secret and len(secret) >= 4:
            text = text.replace(secret, "[REDACTED]")
    text = _SCRUB_PATTERNS[0].sub("Bearer [REDACTED]", text)
    return _SCRUB_PATTERNS[1].sub(r"\1[REDACTED]", text)


# ---------------------------------------------------------------- validation & normalising


def validate_track_uris(uris: Iterable[str]) -> list[str]:
    """Return ``uris`` as a list, or raise ValueError unless every entry is a ``spotify:track:`` URI.

    /me/library also follows/unfollows albums, playlists and users, so nothing else may pass.
    """
    out = list(uris)
    bad = [u for u in out if not isinstance(u, str) or not TRACK_URI_RE.match(u)]
    if bad:
        raise ValueError(f"{len(bad)} value(s) are not spotify:track: URIs (first: {bad[0]!r})")
    return out


def _chunks(seq: list[str], size: int) -> Iterator[list[str]]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def parse_added_at(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def track_from_api(obj: Any, added_at: Any = None) -> Track | None:
    """Normalise an API track object; None for local files, episodes, nulls and malformed data."""
    if not isinstance(obj, dict) or obj.get("is_local") or obj.get("type", "track") != "track":
        return None
    uri = obj.get("uri")
    if not isinstance(uri, str) or not TRACK_URI_RE.match(uri):
        return None
    album = obj.get("album") if isinstance(obj.get("album"), dict) else {}
    artists = tuple(
        Artist(id=a.get("id") or "", name=a.get("name") or "")
        for a in obj.get("artists") or []
        if isinstance(a, dict)
    )
    external = obj.get("external_ids") if isinstance(obj.get("external_ids"), dict) else {}
    return Track(
        id=obj.get("id") or uri.rsplit(":", 1)[-1],
        uri=uri,
        name=obj.get("name") or "",
        artists=artists,
        album_name=album.get("name") or "",
        release_date=album.get("release_date"),
        release_date_precision=album.get("release_date_precision"),
        explicit=bool(obj.get("explicit", False)),
        isrc=external.get("isrc"),
        added_at=parse_added_at(added_at),
    )


def playlist_from_api(obj: dict[str, Any], me_id: str) -> Playlist:
    owner = obj.get("owner") if isinstance(obj.get("owner"), dict) else {}
    owner_id = owner.get("id") or ""
    items = obj.get("items") if isinstance(obj.get("items"), dict) else {}
    return Playlist(
        id=obj["id"],
        name=obj.get("name") or "",
        owner_id=owner_id,
        owned=bool(owner_id) and owner_id == me_id,
        collaborative=bool(obj.get("collaborative", False)),
        public=obj.get("public"),
        items_total=items.get("total"),
        snapshot_id=obj.get("snapshot_id"),
    )


# ---------------------------------------------------------------- client


class SpotifyClient:
    def __init__(
        self,
        client_id: str,
        refresh_token: str,
        client_secret: str | None = None,
        *,
        dry_run: bool = True,
        session: Any = None,
        sleep: Callable[[float], None] = time.sleep,
        max_retries: int = MAX_RETRIES,
    ):
        self.client_id = client_id
        self._refresh_token = refresh_token
        self._client_secret = client_secret or None
        self.dry_run = dry_run
        self._session = session if session is not None else requests.Session()
        self._sleep = sleep
        self._max_retries = max_retries
        self._access_token: str | None = None
        self._me_id: str | None = None
        self.skipped_entries = 0

    @classmethod
    def from_env(
        cls, *, dry_run: bool = True, environ: dict[str, str] | None = None, **kwargs: Any
    ) -> "SpotifyClient":
        env = os.environ if environ is None else environ
        client_id, refresh = env.get("SPOTIFY_CLIENT_ID"), env.get(ENV_REFRESH_KEY)
        missing = [n for n, v in (("SPOTIFY_CLIENT_ID", client_id), (ENV_REFRESH_KEY, refresh)) if not v]
        if missing:
            raise SpotifyError("missing environment variable(s): " + ", ".join(missing))
        return cls(
            client_id,
            refresh,
            env.get("SPOTIFY_CLIENT_SECRET") or None,
            dry_run=dry_run,
            **kwargs,
        )

    # -- internals

    def _scrub(self, text: str) -> str:
        return scrub(text, (self._access_token, self._refresh_token, self._client_secret))

    def _error(self, message: str, status: int | None = None) -> SpotifyError:
        return SpotifyError(self._scrub(message), status)

    def _describe(self, resp: Any) -> str:
        try:
            body = resp.json()
            msg = body["error"]
            msg = msg.get("message") if isinstance(msg, dict) else msg
            if msg:
                return str(msg)[:200]
        except Exception:  # noqa: BLE001 - any parse problem falls back to the raw text
            pass
        return str(getattr(resp, "text", ""))[:200]

    def _retry_wait(self, resp: Any) -> float:
        raw = (getattr(resp, "headers", None) or {}).get("Retry-After")
        try:
            wait = max(0.0, float(raw))
        except (TypeError, ValueError):
            wait = 1.0
        if wait > MAX_RETRY_AFTER:
            raise self._error(f"rate limited: Retry-After {wait:.0f}s exceeds {MAX_RETRY_AFTER}s", 429)
        return wait

    def _send(self, method: str, url: str, **kwargs: Any) -> Any:
        try:
            return self._session.request(method, url, timeout=REQUEST_TIMEOUT, **kwargs)
        except requests.RequestException as exc:
            raise self._error(f"{method} {url.split('?')[0]} failed: {exc}") from None

    def refresh_access_token(self) -> str:
        """Exchange the refresh token for an access token (client_id only; secret used if set)."""
        data = {
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
            "client_id": self.client_id,
        }
        headers = {}
        if self._client_secret:
            basic = base64.b64encode(f"{self.client_id}:{self._client_secret}".encode()).decode()
            headers["Authorization"] = f"Basic {basic}"
        for attempt in range(self._max_retries + 1):
            resp = self._send("POST", TOKEN_URL, data=data, headers=headers)
            if resp.status_code == 429 and attempt < self._max_retries:
                self._sleep(self._retry_wait(resp))
                continue
            break
        if resp.status_code != 200:
            raise self._error(
                f"token refresh failed (HTTP {resp.status_code}): {self._describe(resp)}",
                resp.status_code,
            )
        try:
            token = resp.json()["access_token"]
        except Exception:  # noqa: BLE001
            raise self._error("token refresh returned no access_token", resp.status_code) from None
        self._access_token = token
        log.debug("access token refreshed")
        return token

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        """Authenticated call to the Web API. Non-GET is refused in dry-run mode (last line of defence)."""
        method = method.upper()
        if method != "GET" and self.dry_run:
            raise DryRunError(f"dry-run: refusing {method} {path}")
        if self._access_token is None:
            self.refresh_access_token()
        url = API_BASE + path
        refreshed = False
        retries = 0
        while True:
            resp = self._send(
                method,
                url,
                params=params,
                json=json,
                headers={"Authorization": f"Bearer {self._access_token}"},
            )
            status = resp.status_code
            log.debug("%s %s -> %s", method, path, status)
            if status == 401 and not refreshed:
                refreshed = True
                self.refresh_access_token()
                continue
            if status == 429:
                if retries >= self._max_retries:
                    raise self._error(f"{method} {path}: still rate limited after {retries} retries", 429)
                retries += 1
                self._sleep(self._retry_wait(resp))
                continue
            if status >= 400:
                raise self._error(f"{method} {path} failed (HTTP {status}): {self._describe(resp)}", status)
            return resp

    def _json(self, method: str, path: str, **kwargs: Any) -> Any:
        resp = self._request(method, path, **kwargs)
        if not getattr(resp, "content", b"x"):
            return None
        try:
            return resp.json()
        except ValueError:
            return None

    def _require_writable(self, what: str) -> None:
        if self.dry_run:
            raise DryRunError(f"dry-run: refusing to {what}")

    # -- reads

    @property
    def me_id(self) -> str:
        if self._me_id is None:
            self._me_id = self._json("GET", "/me")["id"]
        return self._me_id

    def _pages(self, path: str, limit: int, params: dict[str, Any] | None = None) -> Iterator[dict]:
        offset = 0
        while True:
            data = self._json("GET", path, params={**(params or {}), "limit": limit, "offset": offset})
            items = (data or {}).get("items") or []
            yield from items
            if not items or not (data or {}).get("next"):
                return
            offset += limit

    def iter_saved_tracks(self) -> Iterator[Track]:
        """Liked Songs, newest first. Skips null / local / non-track entries."""
        for entry in self._pages("/me/tracks", SAVED_PAGE):
            track = track_from_api(entry.get("track"), entry.get("added_at")) if isinstance(entry, dict) else None
            if track is None:
                self.skipped_entries += 1
                continue
            yield track

    def iter_my_playlists(self) -> Iterator[Playlist]:
        """All playlists the user has, classified; check ``Playlist.usable`` before use."""
        me = self.me_id
        for obj in self._pages("/me/playlists", PLAYLISTS_PAGE):
            if isinstance(obj, dict) and obj.get("id"):
                yield playlist_from_api(obj, me)

    def iter_playlist_items(self, playlist_id: str) -> Iterator[Track]:
        """Tracks of a playlist (entry shape ``{added_at, item}``). 403 for followed playlists."""
        self._check_playlist_id(playlist_id)
        for entry in self._pages(f"/playlists/{playlist_id}/items", PLAYLIST_ITEMS_PAGE):
            if not isinstance(entry, dict) or entry.get("is_local"):
                self.skipped_entries += 1
                continue
            track = track_from_api(entry.get("item"), entry.get("added_at"))
            if track is None:
                self.skipped_entries += 1
                continue
            yield track

    def contains_saved(self, uris: Iterable[str]) -> dict[str, bool]:
        """Which of ``uris`` are in Liked Songs (read-only; allowed in dry-run)."""
        uris = validate_track_uris(uris)
        result: dict[str, bool] = {}
        for chunk in _chunks(uris, LIBRARY_BATCH):
            flags = self._json("GET", "/me/library/contains", params={"uris": ",".join(chunk)})
            if not isinstance(flags, list) or len(flags) != len(chunk):
                raise self._error("/me/library/contains returned an unexpected response")
            result.update(zip(chunk, (bool(f) for f in flags)))
        return result

    # -- writes (all refuse in dry-run)

    @staticmethod
    def _check_playlist_id(playlist_id: str) -> None:
        if not isinstance(playlist_id, str) or not PLAYLIST_ID_RE.match(playlist_id):
            raise ValueError("invalid playlist id")

    def add_playlist_items(self, playlist_id: str, uris: Iterable[str]) -> str | None:
        """POST /playlists/{id}/items in batches of 100. Returns the last snapshot_id."""
        self._require_writable("add playlist items")
        self._check_playlist_id(playlist_id)
        uris = validate_track_uris(uris)
        snapshot = None
        for chunk in _chunks(uris, PLAYLIST_BATCH):
            data = self._json("POST", f"/playlists/{playlist_id}/items", json={"uris": chunk})
            snapshot = (data or {}).get("snapshot_id", snapshot)
        return snapshot

    def remove_playlist_items(
        self, playlist_id: str, uris: Iterable[str], snapshot_id: str | None = None
    ) -> str | None:
        """DELETE /playlists/{id}/items in batches of 100.

        ``snapshot_id`` must come from a previous *write* response, never a fresh GET (read-after-write
        lag). Later batches chain the snapshot returned by the batch before.
        """
        self._require_writable("remove playlist items")
        self._check_playlist_id(playlist_id)
        uris = validate_track_uris(uris)
        snapshot = snapshot_id
        for chunk in _chunks(uris, PLAYLIST_BATCH):
            body: dict[str, Any] = {"items": [{"uri": u} for u in chunk]}
            if snapshot:
                body["snapshot_id"] = snapshot
            data = self._json("DELETE", f"/playlists/{playlist_id}/items", json=body)
            snapshot = (data or {}).get("snapshot_id", snapshot)
        return snapshot

    def save_tracks(self, uris: Iterable[str], *, allow_resave: bool = False) -> list[str]:
        """PUT /me/library in batches of 40. Returns the URIs actually sent.

        Re-saving an already-liked track resets its ``added_at``, so already-liked tracks are skipped
        (via ``contains``) unless ``allow_resave`` is set — only ``--restore`` should do that.
        """
        self._require_writable("save tracks")
        uris = validate_track_uris(uris)
        if not allow_resave and uris:
            liked = self.contains_saved(uris)
            uris = [u for u in uris if not liked[u]]
        for chunk in _chunks(uris, LIBRARY_BATCH):
            self._request("PUT", "/me/library", params={"uris": ",".join(chunk)})
        return uris

    def remove_saved_tracks(self, uris: Iterable[str]) -> None:
        """DELETE /me/library in batches of 40. Callers must have journalled + verified first."""
        self._require_writable("remove saved tracks")
        uris = validate_track_uris(uris)
        for chunk in _chunks(uris, LIBRARY_BATCH):
            self._request("DELETE", "/me/library", params={"uris": ",".join(chunk)})


# ---------------------------------------------------------------- PKCE login (--setup)


def pkce_pair() -> tuple[str, str]:
    """(verifier, S256 challenge)."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def build_authorize_url(client_id: str, challenge: str, state: str) -> str:
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPES,
            "state": state,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
        }
    )
    return f"{AUTH_URL}?{query}"


def _capture_code(state: str, timeout: float, on_ready: Callable[[], None]) -> str:
    """Serve 127.0.0.1:8888 until the redirect arrives; returns the code (state verified)."""
    result: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if urllib.parse.urlparse(self.path).path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            result["code"] = (query.get("code") or [""])[0]
            result["state"] = (query.get("state") or [""])[0]
            result["error"] = (query.get("error") or [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"SpotiSort: login received. You can close this tab.")

        def log_message(self, *args: Any) -> None:  # silence request logging
            pass

    server = http.server.HTTPServer(("127.0.0.1", REDIRECT_PORT), Handler)
    server.timeout = 1.0
    try:
        on_ready()
        deadline = time.monotonic() + timeout
        while "state" not in result and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()
    if "state" not in result:
        raise SpotifyError("login timed out waiting for the browser redirect")
    if result["error"]:
        raise SpotifyError(f"authorization denied: {result['error']}")
    if not hmac.compare_digest(result["state"], state):
        raise SpotifyError("state mismatch on login redirect; aborting")
    if not result["code"]:
        raise SpotifyError("login redirect carried no code")
    return result["code"]


def run_setup(
    client_id: str,
    env_path: str | Path = ".env",
    *,
    session: Any = None,
    timeout: float = 300,
    open_browser: bool = True,
) -> None:
    """PKCE login; writes only SPOTIFY_REFRESH_TOKEN to ``env_path``. Prints nothing secret."""
    session = session or requests.Session()
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(16)
    url = build_authorize_url(client_id, challenge, state)

    def announce() -> None:
        print("Opening your browser to log in to Spotify. If it does not open, visit:")
        print(url)
        if open_browser:
            threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()

    code = _capture_code(state, timeout, announce)
    resp = session.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "code_verifier": verifier,
        },
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code != 200:
        raise SpotifyError(
            scrub(f"token exchange failed (HTTP {resp.status_code}): {str(resp.text)[:200]}", (code, verifier)),
            resp.status_code,
        )
    body = resp.json()
    refresh = body.get("refresh_token")
    if not refresh:
        raise SpotifyError("token exchange returned no refresh_token")
    set_env_value(env_path, ENV_REFRESH_KEY, refresh)
    missing = set(SCOPES.split()) - set((body.get("scope") or "").split())
    print(f"Saved {ENV_REFRESH_KEY} to {env_path}.")
    if missing:
        print("Warning: scopes not granted: " + ", ".join(sorted(missing)))


# ---------------------------------------------------------------- live smoke test (read-only)


def smoke(client: SpotifyClient) -> dict[str, int]:
    """Read-only counts. Never prints names, ids or tokens."""
    liked = sum(1 for _ in client.iter_saved_tracks())
    owned = collab = followed = 0
    for p in client.iter_my_playlists():
        if p.owned:
            owned += 1
        elif p.collaborative:
            collab += 1
        else:
            followed += 1
    return {
        "liked": liked,
        "owned_playlists": owned,
        "collaborative_playlists": collab,
        "followed_unusable_playlists": followed,
        "skipped_entries": client.skipped_entries,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.spotify_client", description=__doc__.split("\n")[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--setup", action="store_true", help="one-time PKCE login; saves the refresh token to .env")
    group.add_argument("--smoke", action="store_true", help="read-only live check (needs SPOTISORT_LIVE=1)")
    parser.add_argument("--env", default=".env", help="path to the .env file (default: .env)")
    args = parser.parse_args(argv)

    load_env(args.env)
    try:
        if args.setup:
            client_id = os.environ.get("SPOTIFY_CLIENT_ID")
            if not client_id:
                print("SPOTIFY_CLIENT_ID is not set (put it in .env).", file=sys.stderr)
                return 2
            run_setup(client_id, args.env)
            return 0
        if os.environ.get("SPOTISORT_LIVE") != "1":
            print("Refusing to hit the live API: set SPOTISORT_LIVE=1 to run --smoke.", file=sys.stderr)
            return 2
        counts = smoke(SpotifyClient.from_env(dry_run=True))
    except (SpotifyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for key, value in counts.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
