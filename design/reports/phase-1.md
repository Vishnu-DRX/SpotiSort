# Phase 1 report — Foundation

Implementation session, 2026-09-21. Head before this report commit: `bc8688f` on `main`.

## 1. Verdict: **PASS** (with open questions in §5)
1. Unit tests pass offline — PASS: 329 passed, 1 skipped (live), 0 failed.
2. Engine correctness — PASS: 95 engine tests; every match key plus precedence/threshold cases (list in §2).
3. No write in dry-run — PASS: 11 dry-run tests; fake session sees only GET on api.spotify.com.
4. Secrets never leak — PASS: 15 tests feed fake tokens through error/log/exception/setup paths.
5. CI green on main — PASS: `Tests` run 35608184255 success.
6. Pages live — PASS: HTTP 200, new landing page served, title `SpotiSort`.
7. Live read smoke — PASS with a count discrepancy: 773 liked, 3 collaborative, but **30** owned (spec says 29). See §5.
8. Repo settings applied — PASS: workflow permission now `write`; description/topics/issues/wiki set; Pages `main:/docs` + `https_enforced`.

## 2. Proof
**#1**
```
$ python -m pytest -q
329 passed, 1 skipped in 2.87s     (330 collected: config 132, env/setup 17, engine 95, client 86)
```
**#2** — `python -m pytest --collect-only -q tests/test_rules_engine.py` includes (excerpt):
`test_artist_in_{matches_exact_name,case_and_whitespace_insensitive,matches_second_credited_artist,no_substring_matching}`,
`test_genre_contains_{substring,case_insensitive,matches_any_of_multiple_genres,empty_genres,none_enrichment}`,
`test_language_in_{case_insensitive,none_language,none_enrichment,not_in_list}`,
`test_release_year_{before,after}_strict_boundary_equal_fails`, `test_release_year_helper[year|month|day|garbage...]`,
`test_explicit_*` (4), `test_track_name_contains_*`, `test_album_name_contains_*`.
Precedence: `test_first_match_wins`, `test_rule_order_matters`, `test_disabled_rule_is_skipped`,
`test_empty_match_rule_is_skipped_not_match_all`. Threshold: `test_rule_threshold_lower_lets_younger_track_match`,
`test_rule_threshold_higher_blocks_track`, `test_age_exactly_equal_to_threshold_matches`,
`test_younger_earlier_rule_falls_through_to_later_rule`, `test_added_at_none_never_matches`,
`test_naive_datetimes_are_treated_as_utc`.

**#3**
```
$ python -m pytest -q -k dry_run        -> 11 passed
```
Key tests: `test_dry_run_refuses_every_write_and_makes_no_http_call` (7 write calls, `session.calls == []`),
`test_dry_run_low_level_request_refuses_non_get`, `test_full_read_workflow_in_dry_run_sees_only_gets_on_api`
(saved tracks, playlists, playlist items, contains: the API host receives only GET; the single non-GET is the OAuth
refresh POST to accounts.spotify.com/api/token, which is not a data write). Mutation check: removing the guard makes
tests fail (done locally, then reverted).

**#4**
```
$ python -m pytest -q -k "secret or scrub or leak or redact or scrubbed or no_tokens or no_secret or no_code"  -> 15 passed
```
Covers servers echoing access/refresh/secret/Bearer in 4xx/5xx bodies, a `requests.ConnectionError` containing the token,
token-endpoint errors, `--setup` stdout/stderr and a failed exchange, and DEBUG logs of a full run: none contain the values.
Mutation check: disabling `_scrub` makes 3 leak tests fail (then reverted).

**#5**
```
$ gh run list --workflow tests.yml -L 1
completed  success  Treat naive datetimes as UTC in age gate; ...  Tests  main  push  35608184255  11s
```

**#6**
```
$ curl -sI https://vishnu-drx.github.io/SpotiSort/ | head -1     -> HTTP/1.1 200 OK
$ curl -s  https://vishnu-drx.github.io/SpotiSort/ | grep -o "<title>[^<]*</title>"   -> <title>SpotiSort</title>
```
Body confirmed to contain the new tagline "Turn your Liked Songs into an inbox."

**#7**
```
$ SPOTISORT_LIVE=1 python -m src.spotify_client --smoke
liked: 773
owned_playlists: 30
collaborative_playlists: 3
followed_unusable_playlists: 21
skipped_entries: 0
```
Read-only (`dry_run=True`); prints counts only.

**#8** see §4.

## 3. What was built
- `src/models.py` — frozen dataclasses: Artist, Track, Playlist (+`usable`), Enrichment, Rule, Config, Match.
- `src/spotify_client.py` — `.env` loader (env wins), PKCE `--setup`, `SpotifyClient` (refresh, 401 -> refresh once,
  429 Retry-After up to 5 retries, paging, normalisation, guarded writes, `contains_saved`), redaction, `--smoke`.
- `src/config.py` — validating loader; all errors reported with rule index + name; unknown keys rejected.
- `src/rules_engine.py` — pure `evaluate(track, enrichment, rules, now, default_days_threshold)`, `release_year`, `age_days`.
- `tests/` — 4 test files, `conftest.py` (live skip), 5 sanitised fixtures built from a sample of the real library
  (ids/owners/names replaced, dates synthesised, null/local/episode edge entries added).
- `pytest.ini`, `requirements-dev.txt`, `.env.example`, `.github/workflows/tests.yml`, `scripts/set_secrets.ps1`,
  `docs/index.html` + `style.css` (landing page), `README.md` (setup guide), `config.example.yaml` (+`language_in` rule).
- Untouched stubs: `sync.py`, `analyze.py`, `genre_cache.py`, `sync.yml` (later phases).

## 4. GitHub setup (commands run; `R=Vishnu-DRX/SpotiSort`)
```
gh api repos/$R/actions/permissions/workflow
   -> {"default_workflow_permissions":"read","can_approve_pull_request_reviews":false}
gh api -X PUT repos/$R/actions/permissions/workflow -f default_workflow_permissions=write   -> ok
gh api repos/$R/actions/permissions/workflow
   -> {"default_workflow_permissions":"write","can_approve_pull_request_reviews":false}
gh repo edit $R --description "Rules-based auto-sorter for Spotify Liked Songs: ..." \
   --add-topic spotify --add-topic playlist --add-topic github-actions --add-topic python \
   --add-topic automation --add-topic liked-songs --enable-issues --enable-wiki=false      -> ok
gh api repos/$R --jq '{description,topics,has_issues,has_wiki,visibility,default_branch}'
   -> topics [automation,github-actions,liked-songs,playlist,python,spotify], has_issues true,
      has_wiki false, public, main
gh api repos/$R/pages --jq '{status,html_url,source,https_enforced}'
   -> html_url https://vishnu-drx.github.io/SpotiSort/, source {branch:main,path:/docs}, https_enforced true
gh run list --workflow tests.yml -L 1        (success, above)
gh auth status                               (scopes include repo, workflow)
git push origin main                         (HTTPS remote; worked)
```
Pages was already configured as required before I started (status `built`); no change was needed.
Secrets: **not set** (by design; user runs `powershell scripts/set_secrets.ps1` once).

## 5. Deviations / Questions for master
1. **Owned-playlist count 30, not 29.** Followed (non-owned, non-collab) = 21, collab = 3, total 54 vs 53 in FINDINGS.
   Likely a playlist created since the findings run; not investigated. Please confirm this is acceptable drift.
2. **Age gate is per rule.** `days_threshold` (rule, else default) is part of each rule's condition, so a track too young
   for an earlier rule falls through to later rules. Plan §5.2 step 3 (global pre-filter) cannot support per-rule
   thresholds below the default. Confirm, or say "a too-young match blocks later rules".
3. **Config is stricter than the plan:** empty `match`, empty lists, empty strings and duplicate rule names
   (case-insensitive) are rejected (an empty match would match everything). The engine also skips empty-match rules.
4. **Config schema does not yet accept `language_playlists` / `enrichment`** (unknown keys rejected). Phase 2 must extend
   it; Phase 6 says the schema is frozen after Phase 1, so please decide whether these two keys belong to the frozen schema.
5. **`language_in` representation** (names such as "hindi" vs ISO codes "hi") is undefined; the engine does a
   case-insensitive equality on whatever `Enrichment.language` holds. Needs a Phase 2 decision (I suggest lowercase
   English names, matching the `language_playlists` example in the spec).
6. **`--apply` guard gap:** `.claude/settings.json` denies only `python src/sync.py --apply`. Modules use package-relative
   imports, so the real invocation is `python -m src.sync ...` (as the Phase 4 spec writes), which the deny rule does not
   match. Recommend adding `Bash(python -m src.sync --apply:*)` and the PowerShell equivalent to `deny`. CLAUDE.md
   "Commands" still says `python src/sync.py`.
7. `spec-reviewer` is not registered as an Agent subagent type here; I ran a general-purpose agent with the definition
   from `.claude/agents/spec-reviewer.md`.
8. I ran a key-names-only grep on `.env` once (no values printed) to confirm the three keys exist. `.env` also holds an
   unused `SPOTIFY_CLIENT_SECRET`. Otherwise `.env` was read only by the code.
9. `sync.yml` (untouched; cron 03:00 UTC daily) still passes `SPOTIFY_CLIENT_SECRET` and only echoes a TODO. Harmless now;
   fix in Phase 4.

## 6. Risks & known gaps
- Write paths are **unverified live** through this client (unit-tested against the documented shapes only). `requests`
  percent-encodes `:` and `,` in `uris`; FINDINGS says encoded is accepted, but Phase 4's first `SpotiSort Test` run must confirm.
- `--setup` (PKCE login) was not run live (it would replace the working refresh token). It is unit-tested, including the
  real localhost server on 8888 (state mismatch, denied, missing code, timeout). Those tests bind port 8888.
- Multi-batch writes raise on a mid-way failure without reporting which batches committed; Phase 4 needs per-batch results.
- Followed-playlist write rejection and 429 behaviour remain unverified live (as the spec notes).
- Local Python is 3.14; CI runs 3.12 (green). Git shows LF->CRLF warnings (no `.gitattributes`).
- The scrubber redacts anything shaped like `code=...`, which can over-redact diagnostics (safe direction).
- `parse_env` does not strip trailing inline `# comments`.

## 7. Agents used
- Agent A (docs/CI): wrote `tests.yml`, `requirements-dev.txt`, `set_secrets.ps1`, landing page + CSS, README. Reviewed all;
  kept as written. I added `.env.example` and the `language_in` config example myself.
- Agent B (tests): wrote the engine (95) and config (132) test files. Reviewed the test list and ran them; they encode the
  semantics documented in the module docstrings.
- Agent C (spec-reviewer role): found no hard-constraint violations. Acted on: naive-datetime crash (fixed + test), untested
  redirect server (tests added), all-liked `save_tracks` and `--smoke` output tests (added). Not acted on: items in §6.
- Main session: all client/config/engine code, client + env/setup tests, fixtures, GitHub setup, this report.

## 8. Next (Phase 2)
1. `src/enrichment/` skeleton: `Enricher.resolve(track) -> Enrichment` interface + `script_detect.py` with the >=25-title test table (pure, offline).
2. `musicbrainz.py`: ISRC -> recording -> artist, User-Agent, >=1.0 s spacing via injectable clock, 503 retry, recorded fixtures; plus `isrc_country.py`.
3. `.cache/enrichment.json` (atomic writes, 90-day staleness) + config keys `language_playlists` / `enrichment.musicbrainz`, then `playlist_language.py`.

Blockers: master answers on §5 items 4 and 5 (schema keys, language representation); also confirm removing `genre_cache.py`.
