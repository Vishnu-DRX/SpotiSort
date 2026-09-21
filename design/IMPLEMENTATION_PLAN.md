# Spotify Liked-Songs Auto-Sorter — Implementation Plan

> ## Revision 2 errata (2026-09-21, from live API verification — these override the text below)
> - **No genres from Spotify** (`GET /artists/{id}` has no `genres`; album `genres` always empty; batch
>   endpoints 403). Genre + **language** come from MusicBrainz (via ISRC, still present on all tracks),
>   script detection, and language maps learned from the user's own playlists. `genre_cache.py` becomes
>   `src/enrichment/`. New rule key `language_in`; new config `language_playlists`. Language is the
>   *primary* differentiator, genre secondary.
> - **No Client Secret needed**: PKCE login + client_id-only refresh both work. Actions secrets are only
>   `SPOTIFY_CLIENT_ID` and `SPOTIFY_REFRESH_TOKEN`. Refresh tokens are not rotated.
> - Limits: `/me/library` add/remove/contains **40** per call (`uris` query param, `spotify:track:` only);
>   `/me/tracks` 50/page; `/me/playlists` 50/page; `/playlists/{id}/items` 100/page and 100/write; search 10.
> - Playlists: only **owned** (29) or **collaborative** (3) are usable; **followed** playlists return 403 on
>   read. Resolve targets by name among owned/collaborative only. Counts live in `items.total`.
> - `GET /me` has no `product` — Premium cannot be verified in code (document as prerequisite only).
> - Playlist entries are `{added_at, item}`; `track` is now a boolean. Skip `is_local`/null/episode entries.
> - Safety: journal-before-remove, verify-after, reconcile totals, `--restore`; see `BUILD_SPEC.md`.
> - Planning docs live in `design/`; `docs/` is the Pages site. Build order is in `BUILD_SPEC.md`.
> - Exact write-request shapes: `spotify-api-explore/FINDINGS.md` §6 (pending live write tests).

## 1. What this is

A rules-based system that treats Spotify **Liked Songs as an inbox**: any liked
song older than a configurable number of days gets evaluated against a set of
user-defined rules (artist, genre, release year, explicit flag, etc.) and,
on match, is **moved into an existing playlist** (added there, then removed
from Liked Songs). Unmatched songs are left alone (or routed to a fallback
playlist, if configured).

**Hard requirement: this only attaches to playlists the user already has.**
It never creates new playlists on its own unless `create_missing_playlists`
is explicitly set to `true` per-rule.

Two operating modes:
- **Sync mode** (daily, automated) — does the actual sorting.
- **Analyze mode** (one-time / on-demand) — inspects the user's *existing*
  playlists, infers what pattern likely governs each one (dominant genres,
  recurring artists, release era, explicit ratio), and drafts a starting
  `config.yaml` with human-readable rationale comments, for the user to
  review and edit — not applied blind.

## 2. Distribution model (important — do not deviate)

This ships as an **open-source, fork-and-run** project. There is no shared
backend and no central server. Each user:
1. Forks the repo
2. Creates their own Spotify Developer app (their own Client ID/Secret)
3. Stores their own credentials as their own repo's GitHub Actions Secrets
4. Runs their own scheduled Actions workflow, acting only on their own account

This is required, not optional — it's what avoids Spotify's Extended Quota
review process, avoids us holding anyone's write-scoped tokens, and avoids
any hosting cost/liability. Do not design toward a multi-tenant hosted
version.

## 3. Constraints confirmed by live API research (Feb 2026 changes)

These are **not assumptions — verified against Spotify's current docs and
changelog** as of this writing. Design around them, don't rediscover them:

- **Spotify Premium is required** to create a Developer app at all (new
  requirement as of Feb 11, 2026). Each developer is capped at 1 Client ID
  and 5 authorized users per Client ID — irrelevant for single-user use, but
  document this clearly in the README as a prerequisite.
- **`popularity` field has been removed** from both track and artist
  objects. Do **not** implement any popularity-based rule type.
- **No batch artist lookup anymore.** `GET /artists` (plural, up to 50 ids)
  was removed. Only `GET /artists/{id}` (single) remains. Genre lookups
  must be one call per unique artist — **cache aggressively** (see §5.3).
- **Library endpoints are now generic.** Saving/removing liked tracks uses
  `PUT /me/library` / `DELETE /me/library` (not the old `/me/tracks`
  endpoints, which are removed). Fetching saved tracks still uses
  `GET /me/tracks` (unchanged, paginated, includes `added_at`).
- **Playlist item endpoints renamed.** Use `POST /playlists/{id}/items`,
  `GET /playlists/{id}/items`, `DELETE /playlists/{id}/items` — the old
  `/tracks` variants are removed. Response field `tracks` → `items`,
  `track` → `item`.
- **Creating playlists**: `POST /me/playlists` only (current user only —
  fine, that's all we need).
- Track `explicit` field, album `release_date`, artist `genres` (via single
  artist lookup) are all still present and usable.
- Required scopes: `user-library-read`, `user-library-modify`,
  `playlist-read-private`, `playlist-read-collaborative`,
  `playlist-modify-private`, `playlist-modify-public`.

Before writing any API-calling code, run `explore_api.py` (provided
separately) against a real account and diff its output against this section
— confirm nothing has shifted again since.

## 4. Repository structure

```
spotify-liked-sorter/
├── README.md                     # setup walkthrough, prerequisites, FAQ
├── requirements.txt
├── config.yaml                   # user's live rules (gitignored is NOT
│                                  # required — no secrets live here)
├── config.example.yaml           # template with commented examples
├── src/
│   ├── spotify_client.py         # thin wrapper: auth/refresh + all API calls
│   ├── rules_engine.py           # match logic (pure functions, unit-testable)
│   ├── genre_cache.py            # artist_id -> genres cache (load/save)
│   ├── sync.py                   # daily sync entrypoint
│   └── analyze.py                # onboarding/analysis entrypoint
├── .cache/
│   └── artist_genres.json        # committed cache, keeps genre lookups cheap
├── logs/
│   └── YYYY-MM-DD.json           # one structured run summary per sync
├── .github/
│   └── workflows/
│       └── sync.yml              # scheduled daily run
└── docs/                         # GitHub Pages site (config UI)
    ├── index.html
    ├── app.js
    └── style.css
```

## 5. Core script design

### 5.1 Auth (`spotify_client.py`)
- One-time interactive setup (`auth_setup.py` or a `--setup` flag) runs the
  Authorization Code flow locally: spins up a temporary localhost server on
  `127.0.0.1:8888`, opens the browser, captures the `code`, exchanges for a
  refresh token.
- The refresh token is what gets stored as a GitHub Actions secret
  (`SPOTIFY_REFRESH_TOKEN`), alongside `SPOTIFY_CLIENT_ID` and
  `SPOTIFY_CLIENT_SECRET`. Refresh tokens don't expire under normal use, so
  this setup step is a one-time thing per user.
- Every script run starts by exchanging the refresh token for a fresh
  access token — never persist access tokens.

### 5.2 Sync flow (`sync.py`)
1. Refresh access token.
2. Page through `GET /me/tracks` (50 per page) — collect `added_at`, track
   id/uri/name, artists (id + name), album (name, release_date), explicit.
3. Filter to tracks where `now - added_at >= days_threshold` (global default,
   overridable per-rule — see §6).
4. For each surviving track, resolve genres for its primary artist via
   `genre_cache.py` (cache hit first; on miss, call `GET /artists/{id}`,
   store result, then continue).
5. Evaluate rules **in file order**, first match wins. No match → fallback
   playlist if configured, else leave untouched.
6. Resolve each target playlist **by name** via `GET /me/playlists`
   (paginate, build a name→id map once per run). If not found:
   - default: **skip that track, log a warning** (never silently create)
   - only create if that specific rule sets `create_missing_playlists: true`
7. Batch add matched tracks to their resolved playlists
   (`POST /playlists/{id}/items`, up to 100 uris per call).
8. Batch remove successfully-moved tracks from Liked Songs
   (`DELETE /me/library`, up to 50 per call — confirm current batch limit
   against live API before hardcoding).
9. Write a structured run summary to `logs/YYYY-MM-DD.json` (see §8) and
   commit it back to the repo as part of the workflow.
10. Support `--dry-run` (default **on** unless `--apply` is passed) — must
    preview every intended move/removal without calling any write endpoint.
11. Respect `429` rate limit responses — read `Retry-After`, sleep, retry.

### 5.3 Genre cache (`genre_cache.py`)
- Simple `{ "artist_id": { "name": ..., "genres": [...], "fetched_at": ... } }`
  JSON file, committed to the repo (`.cache/artist_genres.json`).
- On sync, only call the API for artist ids not already in the cache (or
  older than some staleness window, e.g. 90 days, in case an artist's
  genre tags change — configurable, not critical).
- This is what keeps daily runs fast and API-call-cheap after the first run.

### 5.4 Analyze mode (`analyze.py`)
1. Auth + fetch all the user's existing playlists.
2. For each playlist, fetch its full track list (`GET /playlists/{id}/items`,
   paginated).
3. Resolve genres for every unique artist involved (same cache).
4. Per playlist, compute: top N genres by frequency, top artists by track
   count, release-year spread (and whether it clusters into an era), ratio
   of explicit tracks.
5. Emit a **draft** `config.yaml`, one rule block per playlist, each
   preceded by a comment explaining the inferred rationale, e.g.:
   ```yaml
   # "Sunday Jazz" — inferred from 34 tracks: 71% genre-tagged "jazz" or
   # "bossa nova", mostly released before 2005. Review before enabling.
   - name: "Sunday Jazz (inferred)"
     match:
       genre_contains: ["jazz", "bossa nova"]
       release_year_before: 2005
     target_playlist: "Sunday Jazz"
     enabled: false   # analyze-mode rules start disabled until reviewed
   ```
6. Never applies anything automatically — output is inspection/editing
   material only.

## 6. Rules schema (`config.yaml`)

```yaml
default_days_threshold: 14

fallback_playlist: null   # or a playlist name; null = leave unmatched songs alone

rules:
  - name: "Jazz to Jazz Vault"
    enabled: true
    match:
      genre_contains: ["jazz"]
    target_playlist: "Jazz Vault"
    days_threshold: 7          # optional override of the global default

  - name: "Favorite chill artists"
    enabled: true
    match:
      artist_in: ["Bonobo", "Tycho"]
    target_playlist: "Chillhop Favorites"

  - name: "Old hip-hop"
    enabled: true
    match:
      genre_contains: ["hip hop", "rap"]
      release_year_before: 2010
    target_playlist: "Old School Hip-Hop"

  - name: "Explicit filter example"
    enabled: true
    match:
      explicit: false
      track_name_contains: "acoustic"
    target_playlist: "Acoustic"
    create_missing_playlists: false   # default; only attach to existing
```

Supported `match` keys (all optional, all AND-combined within one rule):
`artist_in` (list), `genre_contains` (list, substring match against any of
the artist's genres), `release_year_before` / `release_year_after` (int),
`explicit` (bool), `track_name_contains` / `album_name_contains` (string,
case-insensitive substring). **No popularity-based key** (unavailable, see §3).

## 7. GitHub Actions workflow (`.github/workflows/sync.yml`)

- Trigger: `schedule` (daily cron, user-configurable time) + `workflow_dispatch`
  (manual "run now" button from the Actions tab or the Pages UI).
- Steps: checkout → setup Python → install requirements → run
  `python src/sync.py --apply` → commit any changed files under `logs/` and
  `.cache/` back to the repo (`git config` a bot identity, `git commit`,
  `git push`, using the workflow's own built-in `GITHUB_TOKEN` — no extra
  secret needed for this part).
- Secrets consumed: `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`,
  `SPOTIFY_REFRESH_TOKEN`.

## 8. Run log format (`logs/YYYY-MM-DD.json`)

```json
{
  "date": "2026-09-21",
  "dry_run": false,
  "evaluated": 42,
  "moved": [
    {"track": "Song A", "artist": "Bonobo", "playlist": "Chillhop Favorites"}
  ],
  "skipped_no_match": 5,
  "skipped_playlist_missing": [
    {"track": "Song B", "target_playlist": "Nonexistent Playlist"}
  ],
  "errors": []
}
```
This is the "database" for the Pages dashboard (§9) — no external storage
needed, it's just committed JSON files read back over the GitHub API.

## 9. GitHub Pages UI (`docs/`)

Build as a **PWA** (installable, works across desktop/mobile, no native app
needed) rather than a native Windows app — see our earlier comparison; the
UX gap is small and this keeps distribution frictionless.

Phase 1 (ship first): static config builder — form-based rule editor with
live YAML preview, "Copy" and "Download config.yaml" buttons. No auth
needed.

Phase 2: GitHub device-flow login (no server required — this is a supported
flow for a purely static site) to commit `config.yaml` changes directly to
the user's repo via the GitHub REST API.

Phase 3: dashboard reading `logs/*.json` via the GitHub API/raw content URLs
to show sync history — what moved where, last run status, errors.

The "analyze mode" output (draft config with rationale comments) should be
viewable/editable in this same UI once Phase 2 exists, so a user can run
`analyze.py` once, then finish reviewing/tweaking the suggested rules in
the browser instead of hand-editing YAML.

## 10. Testing plan (Playwright, for Cursor to execute)

- Rule-matching logic: unit tests in `rules_engine.py` with fabricated track
  objects — no live API needed for this part.
- Live API integration: use `explore_api.py`'s output as fixtures; also test
  against a real (throwaway/test) playlist before ever running `--apply`
  against a real library.
- Pages UI: Playwright browser tests for — rule builder produces valid YAML
  matching the schema in §6; "download" produces a parseable file;
  (Phase 2) GitHub login flow completes and a committed file round-trips
  correctly; (Phase 3) dashboard renders a sample `logs/*.json` fixture
  correctly.
- Always dry-run test the full `sync.py` flow against a disposable test
  playlist/liked-songs state before trusting it against a real library.

## 11. Security notes

- Refresh token, Client ID, Client Secret: GitHub Actions Secrets only.
  Never committed, never logged, never placed in `config.yaml`.
- Repo is public (confirmed acceptable) — rules and logs are visible to
  anyone, which is fine since neither contains credentials or anything
  sensitive beyond playlist/genre preferences.
- No server, no database, no stored data belonging to anyone but the
  repo owner.

## 12. Suggested build order

1. `spotify_client.py` + `rules_engine.py` + `genre_cache.py`, tested via
   `explore_api.py`'s real output as ground truth.
2. `sync.py` in dry-run mode only — verify against a real account with
   `--dry-run` for a while before ever adding `--apply`.
3. `.github/workflows/sync.yml`, tested manually via `workflow_dispatch`
   before trusting the schedule.
4. `analyze.py`.
5. Pages Phase 1 (static config builder).
6. Pages Phase 2 (GitHub-connected editing).
7. Pages Phase 3 (dashboard).

## 13. Open decisions left for implementation

- Exact cron time for the daily run (user preference).
- Genre cache staleness window (suggested default: 90 days, adjustable).
- Whether `release_year_before`/`after` reads from `album.release_date`
  precision `"year"` vs `"day"` — handle both, `release_date_precision`
  field tells you which.
- Log retention/rollup policy once `logs/` grows large (e.g. roll daily
  files into monthly summaries after N days) — not needed for v1, flag for
  later.
