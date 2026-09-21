# Phase 3 report — Sync in dry-run

## 1. Verdict: **PASS** (real-library dry-run run; master sign-off of the log pending)
1. Dry-run on real library performs 0 write calls — PASS: HTTP audit `{"GET api.spotify.com": 26, "POST accounts.spotify.com": 1}` (the single POST is the OAuth token refresh).
2. Plan is explainable — PASS: every planned move records rule, matched fields, age_days, threshold, playlist, `already_in_target`, `original_added_at`.
3. Missing/ambiguous playlist handled — PASS: unit tests (missing, ambiguous, followed/not_writable, would_create) + live case with a deliberately wrong name.
4. Runtime < 3 min with warm cache — PASS: 25 s.
5. Master review of a real dry-run log — PENDING (excerpt below; full log is local and git-ignored because it names the user's songs).

## 2. Proof
```
$ python -m pytest -q
706 passed, 2 skipped, 75 deselected          (planner 71, sync dry-run 30; e2e deselected)

$ python -m src.sync --config config.local.yaml     (local config with 3 TEST rules; real library, warm cache)
DRY RUN: evaluated 773 liked songs; no writes performed.
  would move: 366   too young: 48   no rule matched: 345   target problems: 14
    -> SpotiSort Test: 366
  warning: target playlist not found: 'SpotiSort Nonexistent Playlist'
real 0m25s
```
Log excerpt (sanitised; no song/artist/playlist names except the test playlist):
```
{"date": "2026-09-21", "dry_run": true, "evaluated": 773, "errors": 0, "warnings": 1,
 "http_audit": {"POST accounts.spotify.com": 1, "GET api.spotify.com": 26}, "runtime_seconds": 24.8, "journal": 366 entries,
 "moved[0]": {"rule": "TEST english to SpotiSort Test", "matched": {"language_in": "english", "explicit": false},
              "age_days": 2584.1, "threshold_days": 14, "playlist": "SpotiSort Test", "already_in_target": false},
 "skipped_playlist_missing[0]": {"reason": "missing", "target_playlist": "SpotiSort Nonexistent Playlist", "would_create": false},
 "skipped_too_young": 48 (rule with a 100000-day threshold: matched but blocked, evaluation stopped, songs stay in Liked Songs)}
```
The three TEST rules target only `SpotiSort Test` (a real, empty, user-designated test playlist) or a nonexistent name; nothing was written.
`--apply` still exits 2 ("not implemented", Phase 4).
Decision 8 (percent-encoded `contains`) was closed in the previous phase (`tests/test_live_readonly.py`, live pass).

## 3. What was built
`src/planner.py` (pure decide/resolve_target/build_plan/targets_needed; age gate blocks per decision 2), `src/sync.py` (dry-run pipeline, `AuditSession`
HTTP histogram, exit 3 if a write reaches the API, log per plan §8 + `skipped_too_young`, `warnings`, `journal` (would-be entries), `http_audit`, `runtime_seconds`),
filters `--limit` (oldest first), `--since`, `--rule`, `--no-network`. `Enricher` now also takes `english_default` from config (see phase-2 addendum).

## 4. GitHub setup
None.

## 5. Deviations / Questions for master
1. The test rules used for the live run are not the user's real rules (there is no real `config.yaml` yet); a sign-off log with real rules needs the user's config
   (the Pages builder or `python -m src.analyze` draft can produce it).
2. Dry-run logs are git-ignored (`logs/2*.json`); Phase 4's workflow will `git add -f` real run logs. Real logs name songs: confirm that is acceptable in a public repo.

## 6. Risks & known gaps
- `already_in_target` was exercised live only through the same read path as other playlist reads (target playlist was empty).
- `age_days` up to ~2,500 shows liked dates go back years; per-song ages come straight from Spotify `added_at`.

## 7. Agents used
One agent wrote the planner + sync dry-run tests (reviewed, green). All `src` code in the main session.

## 8. Next
Phase 4 after gate G2 (user must designate 3 test songs, run `scripts/set_secrets.ps1`, confirm cron). Non-live Phase 4 work first: failure-injection tests, `--restore`, `sync.yml` rewrite (incl. `actions/cache` for `.cache/enrichment.json`, decision 10 investigation).
