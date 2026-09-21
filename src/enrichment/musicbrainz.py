"""MusicBrainz provider: ISRC -> recording -> artist (genre tags, country), artist-name search fallback.

Polite client: descriptive User-Agent, at most one request per second (injectable clock for tests),
retry on 503/429 with backoff. No key needed.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import requests

from .. import __version__

log = logging.getLogger("spotisort")

BASE = "https://musicbrainz.org/ws/2"
USER_AGENT = f"SpotiSort/{__version__} (https://github.com/Vishnu-DRX/SpotiSort)"
MIN_INTERVAL = 1.0
MAX_RETRIES = 4
SEARCH_MIN_SCORE = 95
MAX_GENRES = 5


class MusicBrainzError(RuntimeError):
    pass


class RateLimiter:
    """Guarantees >= ``interval`` seconds between calls to ``wait``."""

    def __init__(
        self,
        interval: float = MIN_INTERVAL,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.interval, self._clock, self._sleep = interval, clock, sleep
        self._last: float | None = None

    def wait(self) -> None:
        if self._last is not None:
            remaining = self.interval - (self._clock() - self._last)
            if remaining > 0:
                self._sleep(remaining)
        self._last = self._clock()


@dataclass
class ArtistInfo:
    mbid: str | None = None
    name: str | None = None
    genres: list[str] = field(default_factory=list)
    country: str | None = None
    via: str = ""  # "isrc" | "search"


def tags_to_genres(tags: Any, limit: int = MAX_GENRES) -> list[str]:
    """Top tags by vote count (ties keep API order); lowercase, deduplicated."""
    if not isinstance(tags, list):
        return []
    ranked = sorted(
        (t for t in tags if isinstance(t, dict) and isinstance(t.get("name"), str) and t.get("count", 0) >= 1),
        key=lambda t: -int(t.get("count", 0)),
    )
    out: list[str] = []
    for t in ranked:
        name = t["name"].strip().lower()
        if name and name not in out:
            out.append(name)
    return out[:limit]


def _fold(s: str) -> str:
    return " ".join(s.casefold().split())


class MusicBrainz:
    def __init__(
        self,
        session: Any = None,
        limiter: RateLimiter | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._session = session if session is not None else requests.Session()
        self._limiter = limiter or RateLimiter()
        self._sleep = sleep
        self.requests_made = 0
        self.retries_503 = 0

    def _get(self, path: str, params: dict[str, Any]) -> Any | None:
        """GET returning parsed JSON, None on 404. Retries 503/429 with backoff."""
        for attempt in range(MAX_RETRIES + 1):
            self._limiter.wait()
            self.requests_made += 1
            resp = self._session.get(
                f"{BASE}/{path}",
                params={**params, "fmt": "json"},
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=30,
            )
            if resp.status_code == 404:
                return None
            if resp.status_code in (503, 429) and attempt < MAX_RETRIES:
                self.retries_503 += 1
                try:
                    wait = float(resp.headers.get("Retry-After", 0))
                except (TypeError, ValueError):
                    wait = 0.0
                self._sleep(max(wait, 2.0 * (attempt + 1)))
                continue
            if resp.status_code != 200:
                raise MusicBrainzError(f"MusicBrainz {path} -> HTTP {resp.status_code}")
            return resp.json()
        raise MusicBrainzError(f"MusicBrainz {path}: gave up after {MAX_RETRIES} retries")

    def artists_for_isrc(self, isrc: str) -> list[ArtistInfo] | None:
        """Credited artists of the recording with this ISRC, or None if MusicBrainz has no such ISRC."""
        isrc = isrc.strip().upper()  # Spotify sometimes returns lowercase ISRCs; MusicBrainz answers 400
        data = self._get(f"isrc/{isrc}", {"inc": "artists+tags"})
        recordings = (data or {}).get("recordings") or []
        if not recordings:
            return None
        infos: list[ArtistInfo] = []
        for credit in recordings[0].get("artist-credit") or []:
            artist = credit.get("artist") if isinstance(credit, dict) else None
            if not isinstance(artist, dict):
                continue
            infos.append(
                ArtistInfo(
                    mbid=artist.get("id"),
                    name=artist.get("name"),
                    genres=tags_to_genres(artist.get("tags")),
                    country=artist.get("country"),
                    via="isrc",
                )
            )
        return infos or None

    def search_artist(self, name: str) -> ArtistInfo | None:
        """Best exact-name (or alias) hit with score >= SEARCH_MIN_SCORE, else None."""
        query = name.replace('"', " ")
        data = self._get("artist", {"query": f'artist:"{query}"', "limit": 5})
        for hit in (data or {}).get("artists") or []:
            if not isinstance(hit, dict) or hit.get("score", 0) < SEARCH_MIN_SCORE:
                continue
            names = {_fold(hit.get("name") or "")} | {
                _fold(a.get("name") or "") for a in hit.get("aliases") or [] if isinstance(a, dict)
            }
            if _fold(name) in names:
                area = hit.get("area") if isinstance(hit.get("area"), dict) else {}
                codes = area.get("iso-3166-1-codes") if isinstance(area.get("iso-3166-1-codes"), list) else []
                return ArtistInfo(
                    mbid=hit.get("id"),
                    name=hit.get("name"),
                    genres=tags_to_genres(hit.get("tags")),
                    country=hit.get("country") or (codes[0] if codes else None),
                    via="search",
                )
        return None
