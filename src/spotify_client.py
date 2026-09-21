"""Thin Spotify Web API wrapper.

TODO: implement auth/refresh and API calls once the live explore output
confirms endpoint shapes against IMPLEMENTATION_PLAN.md §3 / §5.1.
"""

from __future__ import annotations

from typing import Any


def get_access_token(
    client_id: str,
    client_secret: str,
    refresh_token: str,
) -> str:
    """Exchange a refresh token for a fresh access token.

    TODO: POST https://accounts.spotify.com/api/token
    Never persist access tokens — only return them for the current run.
    """
    raise NotImplementedError("spotify_client.get_access_token — not implemented yet")


def get_saved_tracks(access_token: str) -> list[dict[str, Any]]:
    """Page through GET /me/tracks and return all saved track items.

    TODO: paginate (limit=50), collect added_at + track fields needed by sync.
    """
    raise NotImplementedError("spotify_client.get_saved_tracks — not implemented yet")


def get_playlists(access_token: str) -> list[dict[str, Any]]:
    """Page through GET /me/playlists and return playlist objects.

    TODO: build a name→id map for rule target resolution.
    Note: current API uses nested `items` (not `tracks`) for playlist totals.
    """
    raise NotImplementedError("spotify_client.get_playlists — not implemented yet")


def get_playlist_items(access_token: str, playlist_id: str) -> list[dict[str, Any]]:
    """Page through GET /playlists/{id}/items.

    TODO: use /items (not legacy /tracks); response field is `item`, not `track`.
    """
    raise NotImplementedError("spotify_client.get_playlist_items — not implemented yet")


def get_artist(access_token: str, artist_id: str) -> dict[str, Any]:
    """GET /artists/{id} (single artist only — batch endpoint removed).

    TODO: confirm whether `genres` is still present on live payloads before
    wiring genre-based rules to this response.
    """
    raise NotImplementedError("spotify_client.get_artist — not implemented yet")


def add_items_to_playlist(
    access_token: str,
    playlist_id: str,
    uris: list[str],
) -> None:
    """POST /playlists/{id}/items (batch, up to API limit).

    TODO: implement write path; only call from sync --apply mode.
    """
    raise NotImplementedError("spotify_client.add_items_to_playlist — not implemented yet")


def remove_saved_tracks(access_token: str, ids: list[str]) -> None:
    """DELETE /me/library (or current library-remove endpoint).

    TODO: confirm batch limit against live API before hardcoding.
    """
    raise NotImplementedError("spotify_client.remove_saved_tracks — not implemented yet")


def create_playlist(access_token: str, name: str) -> dict[str, Any]:
    """POST /me/playlists — only when a rule sets create_missing_playlists: true.

    TODO: implement; default sync behavior must never call this.
    """
    raise NotImplementedError("spotify_client.create_playlist — not implemented yet")
