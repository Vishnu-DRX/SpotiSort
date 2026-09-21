# Phase 3 report — Sync in dry-run (code complete; live proof HELD at gate G1)

## 1. Verdict: **PARTIAL** (built + unit-tested; live real-library dry-run deliberately not run)
1. Dry-run makes 0 write calls — PASS in tests (real `SpotifyClient` on fake HTTP: only GET on api.spotify.com, token POST to accounts.spotify.com allowed; `http_audit` in the log). **Live audit: not run.**
2. Plan is explainable — PASS in tests: each move records rule, matched fields, age_days, threshold, playlist, `already_in_target`, original_added_at.
3. Missing/ambiguous playlist — PASS in tests (`missing`, `ambiguous`, `not_writable`, `would_create` only with `create_missing_playlists`). Live wrong-name case: not run.
4. Runtime < 3 min warm — not measured (warm enrichment alone takes ~40 s incl. reads, so expected to pass).
5. Master review of a real dry-run log — **pending**.

## 2. Proof
```
$ python -m pytest -q
606 passed, 2 skipped, 68 deselected     (planner 71 tests, sync dry-run 30 tests, from tests/test_planner.py + tests/test_sync_dry_run.py)
$ SPOTISORT_LIVE=1 python -m pytest tests/test_live_readonly.py -q   -> 1 passed   (decision 8: percent-encoded contains works)
```

## 3. What was built
- `src/planner.py` — pure `decide` / `resolve_target` / `build_plan` / `targets_needed`. Age gate blocks (decision 2); `--rule` keeps precedence;
  fallback playlist only for unmatched songs older than the default threshold; `--limit` takes oldest liked first; `--since`.
- `src/sync.py` — `python -m src.sync` (dry-run only). `--apply` prints "not implemented (Phase 4)" and exits 2 without touching anything.
  Writes `logs/YYYY-MM-DD.json` (schema §8 + `skipped_too_young`, `warnings`, `journal` = entries that WOULD be journalled, `http_audit`, `runtime_seconds`).
  An `AuditSession` counts every HTTP call; the run aborts with exit 3 if any non-GET reaches the Spotify API.
- Tests by an agent, reviewed; two pinned behaviours: an `added_at=None` match is reported as `too_young` (never moved); target-name matching
  does not collapse inner whitespace.

## 4. GitHub setup
None this phase.

## 5. Deviations / Questions for master
1. **Why the live dry-run was not run:** gate G1 failed in Phase 2 (`phase-2.md`); language/genre rules would mostly not fire on the current
   enrichment, so a dry-run now would not be a meaningful sign-off log. It is read-only and takes about a minute once you say go.
2. Dry-run logs are written to `logs/YYYY-MM-DD.json` as the spec says but are git-ignored locally (`logs/2*.json`); the Phase 4 workflow will `git add -f`.
   Real logs name the user's songs; decide whether the public repo should hold them.

## 6. Risks & known gaps
- No live evidence yet of `already_in_target` membership reads on a real target (read path is the same tested `iter_playlist_items`).
- `contains` percent-encoding verified live (read-only); write endpoints still unverified through this client (Phase 4).

## 7. Agents used
One test-writing agent (planner + sync dry-run tests); reviewed, ran green; all `src` code written in the main session.

## 8. Next
1. Master resolves G1. 2. Run `python -m src.sync` against the real library (read-only), review the log with the master. 3. Phase 5 (analyze) or, after G2, Phase 4.
