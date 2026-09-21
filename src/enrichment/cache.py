"""On-disk enrichment cache (.cache/enrichment.json): artist genres/area and ISRC lookups.

Negative results are cached too, so an artist MusicBrainz does not know is not re-queried every run.
Entries older than ``max_age_days`` (default 90) count as missing. Writes are atomic.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

DEFAULT_PATH = Path(".cache") / "enrichment.json"
MAX_AGE_DAYS = 90
VERSION = 1


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EnrichmentCache:
    def __init__(
        self,
        path: str | Path = DEFAULT_PATH,
        *,
        max_age_days: int = MAX_AGE_DAYS,
        now: Callable[[], datetime] = _utcnow,
    ):
        self.path = Path(path)
        self.max_age = timedelta(days=max_age_days)
        self._now = now
        self.data: dict[str, Any] = {"version": VERSION, "artists": {}, "isrc": {}}
        self.dirty = False
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(raw, dict) and raw.get("version") == VERSION:
            self.data["artists"] = raw.get("artists") if isinstance(raw.get("artists"), dict) else {}
            self.data["isrc"] = raw.get("isrc") if isinstance(raw.get("isrc"), dict) else {}

    def _fresh(self, entry: Any) -> bool:
        try:
            fetched = datetime.fromisoformat(entry["fetched_at"])
        except (TypeError, KeyError, ValueError):
            return False
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        return self._now() - fetched <= self.max_age

    def _get(self, bucket: str, key: str) -> dict[str, Any] | None:
        entry = self.data[bucket].get(key)
        return entry if self._fresh(entry) else None

    def _put(self, bucket: str, key: str, value: dict[str, Any]) -> None:
        self.data[bucket][key] = {**value, "fetched_at": self._now().isoformat(timespec="seconds")}
        self.dirty = True

    def get_artist(self, artist_id: str) -> dict[str, Any] | None:
        return self._get("artists", artist_id)

    def put_artist(self, artist_id: str, value: dict[str, Any]) -> None:
        self._put("artists", artist_id, value)

    def get_isrc(self, isrc: str) -> dict[str, Any] | None:
        return self._get("isrc", isrc)

    def put_isrc(self, isrc: str, value: dict[str, Any]) -> None:
        self._put("isrc", isrc, value)

    def save(self) -> None:
        """Atomic write (temp file + replace)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".enrichment-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                json.dump(self.data, fh, ensure_ascii=False, indent=1, sort_keys=True)
                fh.write("\n")
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        self.dirty = False
