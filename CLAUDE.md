# SpotiSort

Rules-based sorter for Spotify Liked Songs (the "inbox"). Songs older than N days are matched
against user rules and moved into an **existing** playlist. Open source, fork-and-run: no backend,
each user runs their own GitHub Actions against their own Spotify Developer app.

## Read first
- @design/IMPLEMENTATION_PLAN.md — source of truth for architecture, rules schema, build order
- @design/BUILD_SPEC.md — work packages with acceptance tests (if present, work from this)
- `design/` holds all planning docs. `docs/` is the **GitHub Pages site** — never put planning docs there.

## Commands
- Install: `python -m pip install -r requirements.txt`
- Tests: `python -m pytest -q`
- Dry run (default, no writes): `python src/sync.py`
- Live run: `python src/sync.py --apply` (only after manual verification, see Safety)

## Hard constraints (Spotify API, Feb 2026, verified live)
- No `popularity`. No `genres` on `GET /artists/{id}` for dev-mode apps. No batch artist lookup.
- Genre/language come from MusicBrainz + user's own playlists, never from Spotify.
- Playlist items: `/playlists/{id}/items`; entry shape `{added_at, item}` (`track` is a bool now).
- Liked-song add/remove: `/me/library`. Fetch: `GET /me/tracks`.
- Only write to playlists the user owns/collaborates on. Never create playlists unless a rule sets
  `create_missing_playlists: true`.
- Skip `is_local` tracks and entries whose `item` is null / an episode.
- Check `design/` and `spotify-api-explore/FINDINGS.md` before assuming any API behaviour.

## Safety (non-negotiable)
- Dry-run is the default; `--apply` is opt-in. Any new write path must have a dry-run branch.
- Never read, print, log or commit `.env` or any token/secret. `.env` is gitignored.
- Live write tests target only the playlist named `SpotiSort Test`.
- Never remove a song from Liked Songs unless it was successfully added to its target playlist.

## Conventions
- Python 3.12 target (CI); stdlib + `requests` + `PyYAML` only — ask before adding dependencies.
- `rules_engine.py` is pure functions (no I/O) and fully unit-tested with fabricated tracks.
- All HTTP goes through `spotify_client.py`; honour 429 `Retry-After`.
- Type hints on public functions; small modules; no speculative abstractions.
- Commits: imperative subject, one logical change each. Never force-push `main`.

## Roles
- Master/design session: owns `design/`, reviews. Implementation sessions: work from `BUILD_SPEC.md`,
  keep changes within the work package, report deviations instead of silently changing the design.
