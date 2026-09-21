"""Learn language from the user's own language playlists (strongest signal).

``config.language_playlists`` maps a playlist name to a language. Every track in such a playlist votes for
that language on the track itself and on each credited artist; an artist's language is the majority vote
(must hold > 60 % of that artist's votes, otherwise unknown).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable, Mapping

from ..models import Track

MAJORITY = 0.6


class LanguageMap:
    def __init__(self) -> None:
        self._track_votes: dict[str, Counter[str]] = defaultdict(Counter)
        self._artist_votes: dict[str, Counter[str]] = defaultdict(Counter)

    def add(self, track: Track, language: str) -> None:
        self._track_votes[track.id][language] += 1
        for artist in track.artists:
            if artist.id:
                self._artist_votes[artist.id][language] += 1

    def add_playlist(self, tracks: Iterable[Track], language: str) -> None:
        for t in tracks:
            self.add(t, language)

    @staticmethod
    def _winner(votes: Counter[str] | None) -> str | None:
        if not votes:
            return None
        lang, n = votes.most_common(1)[0]
        return lang if n / sum(votes.values()) > MAJORITY else None

    def artist_language(self, artist_id: str) -> str | None:
        return self._winner(self._artist_votes.get(artist_id))

    def language_for(self, track: Track) -> str | None:
        """Track's own playlist membership first, then the credited artists' learned languages."""
        direct = self._winner(self._track_votes.get(track.id))
        if direct:
            return direct
        votes: Counter[str] = Counter()
        for a in track.artists:
            lang = self.artist_language(a.id) if a.id else None
            if lang:
                votes[lang] += 1
        return self._winner(votes) if votes else None

    def __len__(self) -> int:
        return len(self._artist_votes)


def resolve_language_playlists(
    language_playlists: Mapping[str, str], playlists: Iterable
) -> tuple[dict[str, str], list[str]]:
    """Map configured playlist names to usable playlist ids.

    Returns ({playlist_id: language}, warnings). Only owned/collaborative playlists count; the name match is
    case-insensitive and exact; missing or ambiguous names are warned about and skipped.
    """
    by_name: dict[str, list] = defaultdict(list)
    for p in playlists:
        if p.usable:
            by_name[p.name.casefold().strip()].append(p)
    found: dict[str, str] = {}
    warnings: list[str] = []
    for name, lang in language_playlists.items():
        matches = by_name.get(name.casefold().strip(), [])
        if not matches:
            warnings.append(f"language playlist not found among owned/collaborative playlists: {name!r}")
        elif len(matches) > 1:
            warnings.append(f"language playlist name is ambiguous ({len(matches)} matches), skipped: {name!r}")
        else:
            found[matches[0].id] = lang
    return found, warnings
