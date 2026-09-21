"""Combine providers behind ``Enricher.resolve(track) -> Enrichment``.

Language tiers: playlist-learned > script > hint (MusicBrainz tag/area) > weak English country default > None
(MusicBrainz work/release language is intentionally not used). Genres come from the primary artist via MusicBrainz tags.
"""

from __future__ import annotations

from typing import Any

from ..models import Enrichment, Track
from .cache import EnrichmentCache
from .musicbrainz import ArtistInfo, MusicBrainz, MusicBrainzError
from .playlist_language import LanguageMap
from .hints import language_hint
from .script_detect import detect_script_language, dominant_script

ENGLISH_COUNTRIES = frozenset({"US", "GB", "AU", "CA", "IE", "NZ"})
# Prior confidence per tier; replaced by measured precision once a backtest exists (signal-precision).
TIER_CONFIDENCE = {"playlist": 0.95, "script": 0.9, "hint": 0.6, "country_default": 0.4, "musicbrainz": 0.6}


def _fold(s: str) -> str:
    return " ".join(s.casefold().split())


class Enricher:
    def __init__(
        self,
        cache: EnrichmentCache,
        musicbrainz: MusicBrainz | None = None,
        language_map: LanguageMap | None = None,
        english_default: bool = False,
    ):
        self.cache = cache
        self.mb = musicbrainz
        self.language_map = language_map
        self.english_default = english_default
        self.errors = 0

    def _artist_entry(self, track: Track) -> dict[str, Any] | None:
        if not track.artists:
            return None
        primary = track.artists[0]
        key = primary.id or _fold(primary.name)
        cached = self.cache.get_artist(key)
        if cached is not None:
            return cached
        if self.mb is None:
            return None
        found, info = self._lookup(track, primary.name)
        if not found:  # transient MusicBrainz error: do not cache a false negative
            return None
        entry = {
            "name": primary.name,
            "mbid": info.mbid if info else None,
            "genres": info.genres if info else [],
            "country": info.country if info else None,
            "via": info.via if info else None,
        }
        self.cache.put_artist(key, entry)
        return entry

    def _lookup(self, track: Track, primary_name: str) -> tuple[bool, ArtistInfo | None]:
        """(completed, info). completed is False if MusicBrainz errored, so nothing gets cached."""
        try:
            if track.isrc:
                cached = self.cache.get_isrc(track.isrc)
                if cached is None:
                    infos = self.mb.artists_for_isrc(track.isrc)
                    cached = {"hit": infos is not None, "credits": [i.__dict__ for i in infos] if infos else []}
                    self.cache.put_isrc(track.isrc, cached)
                for c in cached["credits"]:
                    if _fold(c.get("name") or "") == _fold(primary_name):
                        return True, ArtistInfo(**c)
            return True, self.mb.search_artist(primary_name)
        except MusicBrainzError:
            self.errors += 1
            return False, None

    @staticmethod
    def _english_by_country(track: Track, entry: dict[str, Any] | None) -> bool:
        """WEAK default: Latin-script title/album and the primary artist's MusicBrainz country is English-speaking."""
        text = f"{track.name}{track.album_name}"
        return (
            bool(entry)
            and entry.get("country") in ENGLISH_COUNTRIES
            and any(ch.isalpha() for ch in text)
            and dominant_script(track.name, track.album_name) is None
        )

    def signal_candidates(self, track: Track, *, loo: bool = False) -> dict[str, str | None]:
        """What each language tier says on its own (None = no opinion). Used by the backtest to measure precision."""
        return self._candidates(track, self._artist_entry(track), loo)

    def _candidates(self, track: Track, entry: dict[str, Any] | None, loo: bool) -> dict[str, str | None]:
        out: dict[str, str | None] = {"playlist": None, "script": None, "hint": None, "country_default": None}
        if self.language_map is not None:
            out["playlist"] = self.language_map.language_for(track, loo=loo)
        out["script"] = detect_script_language(track.name, track.album_name, *(a.name for a in track.artists))
        if entry:
            hint = language_hint(entry.get("genres") or [], entry.get("country"))
            out["hint"] = hint[0] if hint else None
            if self._english_by_country(track, entry):
                out["country_default"] = "english"
        return out

    def resolve(self, track: Track, *, exclude_own_playlist_vote: bool = False) -> Enrichment:
        """Genres + language with the tier that produced them.

        ``exclude_own_playlist_vote`` removes this track's own membership from the playlist signal
        (leave-one-out); the backtest uses it so playlist-learned language is not judged on its own answer.
        """
        sources: list[str] = []
        genres: tuple[str, ...] = ()
        genre_source = genre_conf = None
        entry = self._artist_entry(track)
        if entry and entry.get("genres"):
            genres = tuple(entry["genres"])
            sources.append("musicbrainz")
            genre_source, genre_conf = "musicbrainz", TIER_CONFIDENCE["musicbrainz"]

        cands = self._candidates(track, entry, exclude_own_playlist_vote)
        language = source = None
        for tier in ("playlist", "script", "hint", "country_default"):
            if tier == "country_default" and not self.english_default:
                continue
            if cands[tier]:
                language, source = cands[tier], tier
                break
        if source:
            sources.append(source)
        return Enrichment(
            genres=genres,
            language=language,
            sources=tuple(sources),
            language_source=source,
            language_confidence=TIER_CONFIDENCE.get(source) if source else None,
            genre_source=genre_source,
            genre_confidence=genre_conf,
        )
