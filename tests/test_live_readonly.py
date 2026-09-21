"""Live, READ-ONLY checks (skipped unless SPOTISORT_LIVE=1). Never writes."""

from __future__ import annotations

import pytest
import requests

from src import spotify_client as sc

pytestmark = pytest.mark.live


class SpySession(requests.Session):
    def __init__(self):
        super().__init__()
        self.sent = []  # (method, url as actually sent on the wire)

    def send(self, request, **kwargs):
        self.sent.append((request.method, request.url))
        return super().send(request, **kwargs)


def test_contains_works_with_percent_encoded_uris_as_requests_sends_them():
    """Master decision 8: `:` -> %3A and `,` -> %2C must be accepted by /me/library/contains."""
    sc.load_env()
    spy = SpySession()
    client = sc.SpotifyClient.from_env(dry_run=True, session=spy)
    liked = []
    for t in client.iter_saved_tracks():
        liked.append(t.uri)
        if len(liked) == 3:
            break
    assert len(liked) == 3
    not_liked = "spotify:track:4PTG3Z6ehGkBFwjybzWkR8"  # a catalogue track; result for it is not asserted
    result = client.contains_saved(liked + [not_liked])
    assert [result[u] for u in liked] == [True, True, True]
    assert isinstance(result[not_liked], bool)

    contains_urls = [u for m, u in spy.sent if "/me/library/contains" in u]
    assert len(contains_urls) == 1
    assert "%3A" in contains_urls[0] and "%2C" in contains_urls[0] and "spotify:track" not in contains_urls[0]
    assert {m for m, u in spy.sent if u.startswith(sc.API_BASE)} == {"GET"}
