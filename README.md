# SpotiSort

A rules-based, fork-and-run tool that treats Spotify **Liked Songs as an inbox**. After a configurable number of days, liked tracks are matched against your rules and **moved into playlists you already have**. It never creates playlists unless a rule explicitly allows it. It runs on a schedule via GitHub Actions. There is no backend.

## Status

**Phase 1 done:** a tested, offline core (auth client, config loader, rules engine) plus CI. **Nothing sorts yet**, and there is no metadata enrichment yet.

## Prerequisites

- Spotify Premium (required to create a Developer app). It cannot be verified via the API, so this is documentation only.
- Python 3.12+
- A GitHub account (and the `gh` CLI for the secrets step)

## Setup

1. Fork this repo.
2. Create a Spotify Developer app at <https://developer.spotify.com/dashboard> with the redirect URI exactly `http://127.0.0.1:8888/callback`. Note the Client ID. No Client Secret is needed (PKCE).
3. Copy `.env.example` to `.env` and fill in `SPOTIFY_CLIENT_ID`.
4. `python -m pip install -r requirements.txt`
5. `python -m src.spotify_client --setup` opens the browser, captures the code on localhost:8888 and writes `SPOTIFY_REFRESH_TOKEN` to `.env`. Nothing secret is printed.
6. Optional live read-only check: `SPOTISORT_LIVE=1 python -m src.spotify_client --smoke` (PowerShell: `$env:SPOTISORT_LIVE=1` first).
7. `powershell scripts/set_secrets.ps1` once, to store the two Actions secrets (`SPOTIFY_CLIENT_ID`, `SPOTIFY_REFRESH_TOKEN`). The script reads `.env` locally and pipes the values to `gh` without echoing them.

## Config

Copy `config.example.yaml` to `config.yaml`, or build it with the form-based **config builder** at `docs/builder/` (on GitHub Pages: `https://<your-user>.github.io/SpotiSort/builder/`). It validates with the same rules as the sorter, previews the YAML live, imports an existing file, works offline and can be installed as an app; nothing leaves your browser. Supported match keys:

`artist_in`, `genre_contains`, `language_in`, `release_year_before`, `release_year_after`, `explicit`, `track_name_contains`, `album_name_contains`

- Conditions within a rule are ANDed.
- The first matching rule wins.
- Rules can be disabled.
- Each rule may set its own `days_threshold`.

Spotify no longer provides genres or language. In Phase 2 these come from MusicBrainz plus heuristics, so expect them to be best-effort.

## Try it (read-only)

- `python -m src.sync` previews what would move (dry-run; writes nothing, logs to `logs/`). `--apply` is not available yet.
- `python -m src.analyze` drafts `config.draft.yaml` from your existing playlists (all rules disabled; review, then copy into `config.yaml`).
- `python -m src.enrich --report` measures genre/language coverage of your Liked Songs.
- `python -m src.dashboard` opens the read-only dashboard on your own logs (see How to read the dashboard).

## How to read the dashboard

The dashboard is read-only: it cannot change Spotify. Launch it locally with `python -m src.dashboard` (add `--port 8787`, `--logs logs`, `--no-browser` if you like). It listens on 127.0.0.1 only and opens `/dashboard/?source=local`. On the website you can instead pick **Repo** (reads your fork's `logs/` folder from raw.githubusercontent.com) or **Demo data**. Every view shows when its data was made; a yellow banner appears if it is more than 2 days old.

- **Overview** asks "is it healthy?": last run and its verdict, next scheduled run (or "Not scheduled"), liked songs, how many are pending, moves this week, errors and warnings, the safety verdict, and one sentence on what the next run would do.
- **Inbox** asks "what is waiting, and why?": every liked song with its decision. Search, filter and sort it, then click a title to open the **Explain** drawer: each rule in order with passed and failed conditions, and the language and genre signals behind the decision.
- **Rules** asks "what does each rule do?": how many songs each rule matches and wins, when it last matched, and flags for problem rules.
- **Playlists** asks "can every target be written to?": found, missing, not writable or ambiguous, its size and how many songs the next run adds.
- **Runs** is the history, with a detail page per run and a side-by-side comparison of two runs.
- **Safety** asks "has anything been lost, and can I undo it?": the liked-count timeline, reconcile result and restore command for each apply run, and the journal of removals. Vanished-song warnings are a placeholder until that feature exists.
- **Signals** asks "how far can each language signal be trusted?": coverage, and precision per signal and language.
- **Backtest** asks "would the rules route songs correctly?": precision and recall per playlist, confusions and worst misroutes. Names appear only in Local mode; elsewhere playlists are P01, P02 and rules R01, R02.

Colours are never the only clue; every badge has a word. Green (ok) means fine, blue (info) means neutral information such as a dry run or a song that is too young, amber (warning) means look at this, red means a problem.

Language tiers: **Playlist** (learned from your own language playlists) and **Script** (the writing system of the title) are trusted. **Hint** and **Country default** are guesses; they may drive a rule only when measured at 90% precision or better ("qualified").

Terms: **Dead** rule: no song matches it. **Shadowed** rule: songs match, but an earlier rule always takes them first. **Blocked** song: a rule would have matched, but only through a language signal that is not qualified. **Withheld** signal: the language was found but hidden from the rules for that reason. **What-if**: a preview in which disabled rules count as enabled; it is not what a normal run does. **Legacy library**: the data comes from your old Liked Songs archive, not a live inbox.

## Safety guarantees

These are the design, and are fully enforced as the phases land:

- Dry-run by default.
- Journal before any removal.
- Verify after every move.
- Reconcile against the journal on each run.
- Restore from the journal if needed.
- Only `spotify:track` URIs are touched.
- Only playlists you own or that are collaborative are written to.

## Development

```
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Live tests are skipped unless `SPOTISORT_LIVE=1`.

## Roadmap

- Phase 2: enrichment via MusicBrainz (language, genre)
- Phase 3: dry-run sync
- Phase 4: guarded apply + Actions
- Phase 5: analyze mode (done)
- Phase 6: Pages config builder / PWA
- Phase 7: GitHub write-back
- Phase 8: dashboard

## License

Open source — fork and run against your own Spotify Developer app and GitHub Actions secrets. No shared backend.
