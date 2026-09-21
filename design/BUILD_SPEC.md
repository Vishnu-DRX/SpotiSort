# SpotiSort — Build Spec (phase by phase)

Read `CLAUDE.md` and `IMPLEMENTATION_PLAN.md` (incl. its **Revision 2 errata**) first. API ground truth is
`spotify-api-explore/FINDINGS.md` (kept outside the repo, contains account data — never commit it).
Where this spec and the original plan conflict, **this spec wins**.

## How to work (implementation session)
- Work **one phase at a time, in order**. A phase is done only when every *Success criterion* has its
  *Proof* attached in the phase report `design/reports/phase-N.md` (commands run + output excerpts).
- Use **background agents for grunt work** (fixture generation, test writing, MusicBrainz coverage runs,
  Playwright tests, README). Keep design decisions and safety-critical code (anything that writes to
  Spotify) in the main session. Give agents a narrow file scope; review their diffs before committing.
- Run the `spec-reviewer` agent (`.claude/agents/spec-reviewer.md`) at the end of each phase.
- Do not exceed a phase's scope. If reality contradicts the spec, stop, write the deviation into the phase
  report, and ask the master session. Do not silently redesign.
- Commit per logical unit; push to `main` at the end of each phase. Never force-push.
- Never read/print `.env`. Never run `--apply` against the real library except as Phase 4 prescribes.

## Master decisions (after Phase 1 review) — these are binding
1. **Playlist drift 30 vs 29 is fine** (the `SpotiSort Test` playlist was created after the findings run).
2. **Age gate blocks, it does not fall through.** Rules are matched on their conditions first-match-wins; if the
   matched rule's threshold (rule override, else default) is not yet met, the song is **left in Liked Songs and
   evaluation stops** (a too-young match must not leak into a later, broader rule). Change the engine and its
   tests (`test_younger_earlier_rule_falls_through_to_later_rule` etc.) accordingly.
3. Stricter config validation is accepted.
4. **Config schema gains `language_playlists` (map playlist-name → language) and `enrichment` (`musicbrainz:
   bool`) as the first Phase 2 task, then the schema is frozen** (Phase 6 builds against it).
5. **Language values are lowercase English names** (`hindi`, `malayalam`, `tamil`, `telugu`, `kannada`,
   `bengali`, `punjabi`, `marathi`, `english`, `japanese`, `korean`, `spanish`, …). Provide one alias table in
   `src/enrichment/languages.py` mapping ISO 639-1/-3 codes and native names to these; `language_in` in config is
   normalised through it (so `hi` works but is stored as `hindi`).
6. `genre_cache.py` is to be removed (no shim needed if nothing imports it).
7. **`--apply` deny rule:** the master has added `python -m src.sync --apply` variants to `.claude/settings.json`
   and fixed CLAUDE.md. Always invoke as `python -m src.<module>`.
8. Phase 3 must add a live **read-only** check that `contains` works with percent-encoded `uris` as `requests`
   sends them (`:` → `%3A`, `,` → `%2C`), so the encoding risk is closed before any write.
9. Phase 4 writers must return **per-batch results** (which batches committed) and never raise away that
   information on a mid-way failure; reconciliation must use it.
10. Investigate the stray `sync.yml` push-run failure ("workflow file issue", 0 s) in Phase 4 when rewriting it.
11. Add a `.gitattributes` (`* text=auto eol=lf`) in Phase 2 to end the CRLF warnings.

## Autonomy & gates (how to power through)
Run **Phases 2 → 3 → 5 → 6 back-to-back without waiting** for the master, writing `design/reports/phase-N.md`
at the end of each, pushing, and starting the next immediately. Use parallel background agents (e.g. Phase 6
UI + Playwright while Phase 2/3 code is being written). Stop only for these **hard gates**:
- **G1 (Phase 2 decision gate):** if genre coverage < 60 % of unique artists or language coverage < 85 % of
  tracks, finish the phase, report, and stop.
- **G2 (before Phase 4):** needs the **user**: designate 3 test songs, run `scripts/set_secrets.ps1`, confirm cron
  time, and hand-verify the first `--apply` in Spotify. Phase 4 also needs master sign-off of a real dry-run log.
  Do everything in Phase 4 that does not touch the real library first (failure-injection tests, workflow
  rewrite, `--restore`), then stop and ask.
- **G3:** any deviation from a "binding" decision or cross-cutting rule → stop and ask.
Phases 7–8 follow Phase 4. A phase report is required even when you do not stop.

## Master decisions 2 (product reality) — binding, override earlier text where they conflict
The user's *current* Liked Songs (773) is a stale archive (last archived to `Vault_drx` in 2023). **The tool is
designed for a fresh, near-empty Liked Songs inbox.** Therefore:
12. **Never operate on the existing library.** Reads for analysis/backtests are fine; no `--apply` may ever touch
    the 773 legacy songs. Hard guards: `--apply` requires an explicit selector (`--only-uris`, `--newest N`) for the
    first live tests, and a **`--max-moves N` cap (default 50)** that aborts (exit non-zero) if a plan exceeds it. The
    Actions workflow uses the same cap. Coverage numbers on the legacy library are informational only.
13. **Backtest instead of judging on the legacy inbox:** `python -m src.backtest` simulates an inbox from the user's
    owned playlists (each track's true home = the playlist it is in), runs the real planner with the given config, and
    reports per-playlist precision/recall and top confusions. Repo output is counts-only; detail goes to git-ignored
    `logs/backtest-detail.md`. This is the master's sign-off evidence for rule quality (replaces "review a real
    dry-run log"). Per-signal precision (script / hint / country_default) is computed from the same ground truth.
14. **Insert position (needed for `Vault_drx`, whose existing order must be preserved and newer songs go on top):**
    new per-rule key **`target_position: top | bottom`** (default `bottom`). `top` sends `position: 0` in the
    `POST /playlists/{id}/items` body (existing order untouched). Ordering rule: within a run, songs bound for the
    same playlist are ordered **newest liked first**; for `top`, insert the batches **oldest chunk first** so the
    newest ends up at index 0 (batches of ≤100; inserting chunks newest-first would invert order). The `position`
    body field is **unverified live** — verify on `SpotiSort Test` in G2 (add 3 tracks to top, read back, confirm
    order and that pre-existing items kept their relative order). Extend `config.py`, `docs/builder/validate.js`,
    the builder UI, sync tests (the JS/Python parity tests must stay green). This is a deliberate exception to the
    schema freeze.
15. **G2 test protocol changes:** the user does NOT designate legacy songs. They **like 3 fresh songs** in Spotify right
    before the test; the session runs `--apply --newest 3` with a test rule (`days_threshold: 0`, target
    `SpotiSort Test`, `target_position: top`) and verifies add → journal → remove → reconcile, then `--restore`.
    Existing liked songs are never in scope.
16. **Optional later phase (do not build yet): "Liked-songs guardian".** Spotify has silently dropped some liked
    songs for this user. Keep a snapshot of liked ids from each run (private `actions/cache`, not committed); if an id
    vanishes and the tool did not remove it, warn in the run log (and offer `--restore-vanished`).
17. One-off **legacy-to-Vault migration** (liked since 2023 → top of `Vault_drx`, ordered newest first) is out of scope
    now; decision 14 makes it a trivial follow-up run later.

## Verified write shapes (live-tested 2026-09-21 on `SpotiSort Test`; liked count 773 preserved)
- Add to playlist: `POST /playlists/{id}/items`, JSON body `{"uris":["spotify:track:..."]}` → **201**
  `{"snapshot_id"}`. Max 100 (101 → 400).
- Remove from playlist: `DELETE /playlists/{id}/items`, JSON body `{"items":[{"uri":"..."}]}` (optional
  `"snapshot_id"`) → **200** `{"snapshot_id"}`.
- Save/remove liked: `PUT` / `DELETE /me/library?uris=spotify:track:A,spotify:track:B` — URIs in the **query
  string** (JSON body → 400) → **200**, empty body. Max **40**. `GET /me/library/contains?uris=...` max 40.
- **Read-after-write lag:** a GET straight after a write can be stale. Use the `snapshot_id` returned by the
  previous *write* (never one from a fresh GET), and verify with a short poll (e.g. up to 5 tries, 1 s apart)
  before concluding a write failed.
- **Re-saving an already-liked track resets its `added_at`.** Therefore never `PUT` tracks that are already
  liked (skip via `contains` first); `--restore` is the only path that re-saves, and it is expected to reset dates.
- Not verified: writes to followed playlists (reads already 403, so expect failure — treat any non-2xx as
  "do not remove from Liked Songs"). 429 `Retry-After` never occurred live; keep the unit-tested handling.

## Cross-cutting rules (apply to every phase)
1. **No liked song may be lost.** Before ANY removal from Liked Songs: (a) the track was confirmed present in
   the target playlist by re-reading it; (b) a **journal** entry `{uri, name, artists, original_added_at,
   target_playlist_id}` has been written to `logs/YYYY-MM-DD.json` *before* the DELETE call; (c) after the
   DELETE, `/me/library/contains` confirms removal, and totals reconcile (`before - removed == after`).
   Any mismatch → abort run, re-add via `PUT /me/library`, exit non-zero. Note: re-saving a track resets its
   `added_at` to now; the journal keeps the original for reference.
2. Dry-run is default; every write path has a dry-run branch that performs zero write HTTP calls (tested by
   asserting the HTTP layer is never called with PUT/POST/DELETE).
3. Only `spotify:track:` URIs may be sent to `/me/library` (that endpoint also unfollows albums/playlists).
4. Skip `is_local`, null `item`, and non-track (`episode`) entries everywhere.
5. Secrets never logged; `Authorization` headers and tokens redacted in any debug output (unit-tested).
6. Batch limits: `/me/library` + `contains` **40**, playlist items **100**, `/me/tracks` page **50**,
   `/me/playlists` page **50**, `/playlists/{id}/items` page **100**.
7. Tests must run offline (fixtures) with `python -m pytest -q`; live tests are marked `@pytest.mark.live`
   and skipped unless `SPOTISORT_LIVE=1`.

---

## Phase 1 — Foundation (offline core + GitHub setup + live site)
**Goal:** a tested, offline-capable core (auth client, config loader, rules engine) and a repo whose CI, Pages
site and Actions settings are configured — no Spotify writes, no sorting yet.

**Deliverables**
1. `src/spotify_client.py`: `.env` loader (tiny parser, no dependency, env vars win); PKCE-based
   `--setup` login (localhost:8888, S256, prints nothing secret, writes `SPOTIFY_REFRESH_TOKEN` to `.env`
   only); `SpotifyClient` with refresh-token → access-token exchange (client_id only; secret optional and
   used if present), token auto-refresh on 401 once, 429 `Retry-After` sleep/retry (max 5), paging
   helpers (`iter_saved_tracks`, `iter_my_playlists`, `iter_playlist_items`) that normalise to plain
   dataclasses (`Track`, `Playlist`), write methods (`add_playlist_items`, `remove_playlist_items`,
   `save_tracks`, `remove_saved_tracks`, `contains_saved`) that **refuse** to run when `dry_run=True` and
   enforce batch limits + track-URI-only validation. Request shapes per FINDINGS.md §4/§6.
2. `src/config.py`: load + validate `config.yaml` against schema §6 of the plan **plus** `language` match key
   (see Revision 2). Clear error messages with rule name/index. Unknown keys rejected.
3. `src/rules_engine.py`: pure `evaluate(track, enrichment, rules, now) -> Match|None`; first-match-wins;
   AND within a rule; keys: `artist_in`, `genre_contains`, `language_in`, `release_year_before/after`,
   `explicit`, `track_name_contains`, `album_name_contains`. Case-insensitive; artist match on any credited
   artist; year parses `release_date` at `year|month|day` precision; per-rule `days_threshold` override;
   disabled rules skipped. Missing enrichment ⇒ genre/language conditions are simply *false*, never errors.
4. `tests/`: unit tests for the engine (≥ 30 cases incl. precision edge cases, empty lists, disabled rules,
   threshold override, multi-artist), config validation, client behaviours using a fake HTTP session
   (429, 401-refresh, batch splitting, dry-run refusal, token redaction), fixtures built from a sanitised
   subset of `liked_all.json`/`playlists.json` (strip account ids; commit only sanitised fixtures).
5. `.github/workflows/tests.yml`: on push/PR run pytest on Python 3.12 — the required CI.
6. GitHub setup via CLI (record commands in `design/reports/phase-1.md`):
   - confirm Pages: `gh api repos/Vishnu-DRX/SpotiSort/pages` → source `main:/docs`, `https_enforced`.
   - `gh api -X PUT repos/Vishnu-DRX/SpotiSort/actions/permissions/workflow -f default_workflow_permissions=write`
     (needed for log commit-back).
   - repo description + topics via `gh repo edit`; enable issues; disable wiki.
   - `scripts/set_secrets.ps1`: reads `.env`, calls `gh secret set SPOTIFY_CLIENT_ID` and
     `SPOTIFY_REFRESH_TOKEN` via stdin (never echoing values); **user runs it once**, not the session.
   - update `docs/index.html` placeholder to a real landing page (what it is, status, link to repo) so the
     `.github.io` site is visibly live.
7. `README.md`: prerequisites (Premium), Developer-app setup, `.env`, `--setup`, status.

**Success criteria & proof**
| # | Criterion | Proof |
|---|---|---|
| 1 | Unit tests pass offline | `python -m pytest -q` output, ≥ 60 tests, 0 fail |
| 2 | Engine correctness | test list showing each match key + precedence cases |
| 3 | No write can happen in dry-run | test asserting fake session saw only GETs |
| 4 | Secrets never leak | test feeding a fake token through error paths and asserting absence in logs/exceptions |
| 5 | CI green on `main` | `gh run list --workflow tests.yml -L 1` shows success |
| 6 | Pages live | `curl -sI https://vishnu-drx.github.io/SpotiSort/` → 200, page contains project name |
| 7 | Live read smoke test (`SPOTISORT_LIVE=1`) | `python -m src.spotify_client --smoke` prints counts: 773 liked, 29 owned + 3 collab playlists, no secrets |
| 8 | Repo settings applied | `gh api` outputs captured in report |

**After Phase 1 you have:** a verified core library, green CI, a live (placeholder-quality) Pages site, correct
Actions permissions, secrets script ready. **Nothing sorts yet** and no metadata enrichment exists.

---

## Phase 2 — Enrichment: language + genre (MusicBrainz) and cache
**Goal:** resolve language and genre for every liked track cheaply and cache the results.

**Deliverables**
1. `src/enrichment/` (replace `genre_cache.py`; keep a thin shim if imports demand): `Enricher` combining
   providers behind one interface `resolve(track) -> Enrichment{genres[], language, sources[]}`:
   - `musicbrainz.py`: ISRC → recording → artist (`/ws/2/isrc/{isrc}?inc=artists+releases`, then artist
     `inc=tags+genres`); User-Agent `SpotiSort/<ver> (https://github.com/Vishnu-DRX/SpotiSort)`; ≤ 1 req/s;
     retry on 503; fallback to artist name search only if ISRC has no hit (with score threshold).
   - `playlist_language.py`: **learned language map** — `artist_id → language` derived from the user's owned
     playlists whose config maps them to a language (see `language_playlists` in config: e.g.
     `{"Chill Hindi": "hindi", "Malayalam ...": "malayalam"}`); strongest signal.
   - `script_detect.py`: Unicode-script detection on track/album/artist names (Devanagari→hi/mr,
     Malayalam, Tamil, Telugu, Kannada, Bengali, Gurmukhi, Japanese kana, Hangul, CJK, Cyrillic, Arabic).
   - `isrc_country.py`: ISRC prefix → country (weak hint, only used to break ties / label `region`).
   Resolution order for `language`: playlist-learned > script > MusicBrainz release/work language > None.
2. Cache `.cache/enrichment.json` keyed by artist id (genres, area) and ISRC (language hints), with
   `fetched_at` and 90-day staleness; atomic writes; committed by the workflow.
3. `python -m src.enrich --report`: coverage report over all liked tracks — % with genres, % with language,
   top unresolved artists, per-source hit counts. Writes `logs/enrichment-coverage.json`.
4. Config: `language_playlists` mapping + `enrichment.musicbrainz: true/false`.

**Success criteria & proof**
| # | Criterion | Proof |
|---|---|---|
| 1 | Provider unit tests offline (recorded MB fixtures) | pytest output |
| 2 | Rate limit obeyed | test with fake clock asserting ≥ 1.0 s spacing; live run log shows no 503 storms |
| 3 | Cache hit avoids network | test: second run makes 0 MB calls |
| 4 | Coverage measured on the real library | committed sanitised `logs/enrichment-coverage.json` with numbers |
| 5 | **Decision gate:** genre coverage ≥ 60 % of unique artists, language coverage ≥ 85 % of tracks | else report and master decides on adding Last.fm |
| 6 | Script detection accuracy | test table of ≥ 25 real-looking titles across scripts |

---

## Phase 3 — Sync in dry-run
**Goal:** full pipeline, zero writes, an honest preview on the real account.

**Deliverables:** `src/sync.py` — auth → fetch liked → filter by age → enrich → evaluate → resolve targets by name
among **owned or collaborative** playlists only (case-insensitive exact match, warn on duplicates/ambiguity, skip
+ log when missing; `create_missing_playlists` honoured only when true) → build plan → print + write
`logs/YYYY-MM-DD.json` (schema §8 of the plan plus `journal`, `warnings`, `dry_run`). Idempotent: songs already in
the target playlist are still "moved" (only the removal happens) and flagged `already_in_target`.
Also `--limit N`, `--since`, `--rule NAME` filters for safe partial runs.

**Success criteria & proof**
| # | Criterion | Proof |
|---|---|---|
| 1 | Dry-run on real library performs 0 write calls | HTTP audit log (methods histogram) in report |
| 2 | Plan is explainable | each planned move records the matching rule + which fields matched |
| 3 | Missing/ambiguous playlist handled | tests + a live case with a deliberately wrong name |
| 4 | Runtime | full dry-run < 3 min with warm cache |
| 5 | Master review of a real dry-run log | report includes log excerpt; master signs off before Phase 4 |

---

## Phase 4 — Apply (guarded) + Actions automation
**Goal:** safe writes, proven on `SpotiSort Test` first, then scheduled.

**Deliverables:** `--apply` path implementing cross-cutting rule 1 exactly (add → verify in playlist → journal →
remove → verify gone → reconcile); `python -m src.sync --restore logs/<file>.json` re-adds journaled removals;
`sync.yml` wired (`python -m src.sync --apply`, concurrency group so runs don't overlap, commit-back of `logs/`
and `.cache/` with bot identity, `[skip ci]`), cron confirmed with user, `workflow_dispatch` input `dry_run`
(default true) so the first cloud run is a dry-run.

**Test protocol (mandatory order)**
1. Local `--apply` with a config whose only rule targets `SpotiSort Test` and `--limit 3` on 3 *test* songs the
   user has designated; verify each by hand-check in Spotify UI (ask the user).
2. `--restore` those 3, confirm they're back in Liked Songs and out of the test playlist.
3. Failure injection tests (unit, fake session): playlist add fails → track NOT removed; removal call fails
   → reconcile aborts and reports; partial batch failure → only confirmed tracks removed.
4. `gh secret set` (user runs `scripts/set_secrets.ps1`), then
   `gh workflow run sync.yml -f dry_run=true`, inspect via `gh run view --log`, then one real run.

**Success criteria & proof**
| # | Criterion | Proof |
|---|---|---|
| 1 | Liked count preserved except intended moves | before/after counts + journal in report |
| 2 | Injected failures never lose a song | failure-injection test output |
| 3 | Restore works | log + Spotify confirmation from user |
| 4 | Cloud dry-run then real run succeed | `gh run list` outputs, committed log files |
| 5 | Secrets absent from logs | `gh run view --log` grep for token patterns returns nothing |

---

## Phase 5 — Analyze mode
**Goal:** draft `config.yaml` from existing playlists.
**Deliverables:** `src/analyze.py` reading owned + collaborative playlists only (403 on followed → skipped and
reported); per playlist: top genres, top artists, language distribution, year spread/era, explicit ratio;
draft rules all `enabled: false` with rationale comments; `language_playlists` suggestions (a playlist whose
dominant language ≥ 70 %). Never writes to Spotify or applies config.
**Proof:** unit tests on synthetic playlists; a real run producing `config.draft.yaml` that passes
`config.py` validation; master reviews sample rationale quality.

---

## Phase 6 — Pages: config builder (PWA)  *(can run in parallel with 2–5 once Phase 1 config schema is frozen)*
**Goal:** form-based rule editor → live YAML → copy/download; installable PWA; offline.
**Deliverables:** `docs/` static app (no build step, vanilla JS + js-yaml from cdn.jsdelivr pinned with SRI or
vendored), manifest + service worker + icons, schema-driven validation mirroring `config.py`, import existing
YAML, dark/light, mobile layout. Use the `artifact-design`-style rigor: accessible, keyboard-usable.
**Proof:** Playwright tests (`tests/e2e`, run in CI): builds each rule type, YAML round-trips through Python
`config.py` validation (test invokes the real validator on downloaded output); Lighthouse PWA installable
check; screenshot at 375px and 1280px.

## Phase 7 — Pages: GitHub write-back
GitHub device-flow login (client id of a GitHub OAuth App owned by the user; document creation via `gh`/UI),
commit `config.yaml` via Contents API, token kept in `sessionStorage`. Proof: Playwright with mocked GitHub API
+ one manual live round trip; `git log` shows the commit made from the UI. No secrets in the site.

## Phase 8 — Pages: dashboard
Reads `logs/*.json` through the GitHub API/raw URLs: last run status, moves per playlist, warnings, journal, and a
"run now" button (dispatches `workflow_dispatch` via the API, needs Phase 7 auth). Proof: Playwright against
fixture logs; a live render of the real logs.

---

## Definition of done for the whole project
Fork → set 2 secrets → set config → daily run moves songs correctly; README lets a stranger do this in
< 20 min; CI green; site live; no known way for a run to lose a liked song (failure-injection tested).
