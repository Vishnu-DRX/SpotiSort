"""Plain dataclasses shared by the client, config and rules engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Artist:
    id: str
    name: str


@dataclass(frozen=True)
class Track:
    id: str
    uri: str
    name: str
    artists: tuple[Artist, ...] = ()
    album_name: str = ""
    release_date: str | None = None
    release_date_precision: str | None = None
    explicit: bool = False
    isrc: str | None = None
    added_at: datetime | None = None


@dataclass(frozen=True)
class Playlist:
    id: str
    name: str
    owner_id: str
    owned: bool
    collaborative: bool
    public: bool | None = None
    items_total: int | None = None
    snapshot_id: str | None = None

    @property
    def usable(self) -> bool:
        """Only owned or collaborative playlists can be read/written."""
        return self.owned or self.collaborative


@dataclass(frozen=True)
class Enrichment:
    """Genre/language metadata for a track (Spotify provides neither)."""

    genres: tuple[str, ...] = ()
    language: str | None = None
    sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class Rule:
    name: str
    target_playlist: str
    match: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    days_threshold: int | None = None
    create_missing_playlists: bool = False


@dataclass(frozen=True)
class Config:
    default_days_threshold: int = 14
    fallback_playlist: str | None = None
    rules: tuple[Rule, ...] = ()
    language_playlists: dict[str, str] = field(default_factory=dict)  # playlist name -> canonical language
    musicbrainz: bool = True  # enrichment.musicbrainz


@dataclass(frozen=True)
class Match:
    """A rule that matched, plus which match keys were satisfied and by what."""

    rule: Rule
    matched: dict[str, Any] = field(default_factory=dict)
    age_days: float | None = None
    threshold: int | None = None
    aged: bool = True  # False: conditions matched but the age gate is not met yet
