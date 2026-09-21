"""Artist-id → genres cache (JSON on disk under .cache/).

TODO: implement load/save and stale-entry refresh
(IMPLEMENTATION_PLAN.md §5.3). Cache aggressively — only single-artist
lookups remain, and live explore output suggested genres may be sparse/missing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

DEFAULT_CACHE_PATH = Path(".cache") / "artist_genres.json"


def load_cache(path: Path = DEFAULT_CACHE_PATH) -> dict[str, Any]:
    """Load `{ artist_id: { name, genres, fetched_at } }` from disk.

    TODO: return {} if file missing; validate basic shape.
    """
    raise NotImplementedError("genre_cache.load_cache — not implemented yet")


def save_cache(cache: dict[str, Any], path: Path = DEFAULT_CACHE_PATH) -> None:
    """Write the cache JSON (pretty-printed) to disk.

    TODO: ensure parent dirs exist; atomic write preferred.
    """
    raise NotImplementedError("genre_cache.save_cache — not implemented yet")


def get_artist_genres(
    artist_id: str,
    cache: dict[str, Any],
    *,
    fetch_fn,
    max_age_days: int = 90,
) -> list[str]:
    """Return genres for artist_id, using cache or fetch_fn on miss/stale.

    TODO:
      - cache hit + fresh → return cached genres
      - miss or older than max_age_days → call fetch_fn(artist_id), store, return
      - handle artists with empty/missing genres gracefully
    """
    raise NotImplementedError("genre_cache.get_artist_genres — not implemented yet")
