# Phase 2 report — Enrichment (language + genre)

Implementation session, 2026-09-21. **STOPPED AT GATE G1**: both decision-gate thresholds failed on the real library.
Phase 6 was built in parallel (see `phase-6.md`); Phase 3 is code-complete but its live proof is held (see `phase-3.md`).

## 1. Verdict: **PARTIAL** — code complete and tested; criterion 5 (decision gate) FAILED, master decision needed
1. Provider unit tests offline (recorded MB shapes) — PASS: 36 tests in `tests/test_enrichment.py` (+106 script/ISRC, 32 languages/config).
2. Rate limit obeyed — PASS: fake-clock tests assert >= 1.0 s spacing; live cold run had 10 retries after 503/429 in 976 requests, no storm.
3. Cache hit avoids network — PASS: test + live (warm re-run made 11-20 requests, only for previously-failed artists; cold run needed 976).
4. Coverage measured on real library — PASS: `logs/enrichment-coverage.json` committed (sanitised, counts + top-10 names).
5. **Decision gate — FAIL:** genre coverage **49.2 %** of 653 unique primary artists (need >= 60 %); language coverage **3.1 %** of 773 tracks (need >= 85 %).
6. Script detection accuracy — PASS: `tests/test_script_detect.py`, 44 real-looking titles across 14 scripts + 14 negatives.

## 2. Proof
```
$ python -m pytest -q
606 passed, 2 skipped, 68 deselected           (e2e deselected by default; see phase-6)

$ python -m src.enrich --report --config config.local.yaml      (local config, not committed; see §5.2)
tracks 773 | unique_primary_artists 653
genre_coverage_pct_of_artists     49.2   -> gate genre_ge_60: false
language_coverage_pct_of_tracks    3.1   -> gate language_ge_85: false
language_source_counts  {playlist: 17, script: 7, none: 749}
language_distribution   {hindi 14, japanese 4, greek 2, chinese 2, russian 2}
hypothetical_language_pct_with_weak_country_hint  62.0   (NOT applied; artist country in US/GB/AU/CA/IE/NZ or ISRC country)
cold run MusicBrainz: 976 requests (~25 min at 1 req/s), 10 retries, 11 errors (lowercase ISRCs -> HTTP 400; fixed, see below)
```
Cache internals after the run: 653 ISRC lookups, 346 hits (53 %); artists resolved via ISRC 331, via name search 266, unknown to MusicBrainz 56;
321 of 653 artists have >= 1 genre tag (the rest are known to MusicBrainz but untagged, or unknown).
Live encoding check (decision 8): `SPOTISORT_LIVE=1 pytest tests/test_live_readonly.py` -> 1 passed; `contains` accepts `%3A`/`%2C`-encoded
`uris` exactly as `requests` sends them, only GETs seen on the API host. **Encoding risk closed.**

## 3. What was built
- `src/models.py`/`src/config.py`: config schema gains `language_playlists` (name -> language) and `enrichment.musicbrainz`; `language_in` and
  playlist languages normalised via alias table. **Schema is now frozen** (decision 4). Age gate now stops evaluation (decision 2):
  `rules_engine.first_match` + `evaluate`; tests updated (`test_too_young_match_blocks_later_rules_no_fall_through`).
- `src/enrichment/`: `languages.py` (41 languages, ISO 639-1/-3 + native names), `script_detect.py`, `isrc_country.py`, `musicbrainz.py`
  (ISRC -> recording artists+tags; artist search fallback score >= 95 and exact name/alias; 1 req/s; 503/429 retry), `playlist_language.py`
  (artist/track votes from language playlists, > 60 % majority), `cache.py` (`.cache/enrichment.json`, atomic, 90-day staleness, caches negatives),
  `enricher.py` (order: playlist > script > None; MusicBrainz errors are not cached as negatives).
- `src/enrich.py`: `python -m src.enrich --report` -> `logs/enrichment-coverage.json`.
- `genre_cache.py` removed (decision 6, nothing imported it); `.gitattributes` added (decision 11); `.gitignore`: local `.cache/enrichment.json`,
  `logs/2*.json`, `config.local.yaml` (so personal data is never committed by accident).
- Bug found by the live run and fixed: Spotify returns some **lowercase ISRCs**; MusicBrainz answers 400. Now uppercased (+ test).

## 4. GitHub setup
No new gh commands this phase. Pushes to `main` succeeded; `tests` and `e2e` workflows green. The old `sync.yml` still fails at 0 s on every push
("workflow file issue"); untouched, decision 10 (Phase 4).

## 5. Deviations / Questions for master
1. **G1 decision needed.** Options: (a) add Last.fm tags (needs a Last.fm API key -> new Actions secret, breaks the "2 secrets" model) for genre;
   (b) accept lower genre coverage and treat genre rules as best-effort; (c) for language, rely on more/better `language_playlists`, plus an
   optional **weak country/English default** (Latin-script, artist country in an English-speaking country => `english`), which the coverage
   report estimates would lift language coverage from 3.1 % to about 62 % — still < 85 %; (d) LLM/Last.fm classification for the remainder.
   I recommend: language via playlists + English country default, genre via MusicBrainz + optional Last.fm later; and consider relaxing the 85 % target
   to "language known for songs that matter to a rule" since `language_in` rules only need the *target* languages (Hindi/Malayalam/...) identified.
2. **Language playlists were guessed** for the measurement: `Dil`->hindi, `Bas Abb Nahi Sehraha`->hindi, `NewAgeMadrasMail`->tamil,
   `nani mo wakaranai`->japanese, kept in the git-ignored `config.local.yaml`. Only 17 liked songs share artists with them. The user should
   supply the true playlist->language mapping; coverage will change.
3. **MusicBrainz work/release language not implemented** (spec resolution order). The ISRC response has no release language; getting it needs extra
   requests per recording (`work-rels` + work lookup, ~2 more calls/track, ~50 % ISRC hit rate). Skipped pending the G1 decision.
4. Genre = MusicBrainz **tags** (top 5 by votes, count >= 1), not the curated genre list (`genres` inc is invalid on the ISRC endpoint).
5. The enrichment **cache is not committed** (git-ignored: it lists the whole library's artist ids). Phase 4's workflow needs `git add -f`
   (or decide to keep the cache private and rebuild in Actions, ~25 min cold).
6. `config.example.yaml` gained `language_playlists`/`enrichment`.

## 6. Risks & known gaps
- Cold enrichment of a 773-song library takes ~25 min (1 req/s); acceptable once, then incremental.
- Artist-name search can mis-attach a namesake artist (mitigated by score >= 95 + exact name); ISRC path preferred.
- Language-playlist inference assumes playlists are language-pure; > 60 % majority guards mixed artists.
- Coverage file lists the top-10 unresolved artist names (mild taste disclosure in a public repo); say if you want counts only.

7. Spec-reviewer finding 1 ("ISRC artist-credit carries no tags") is **not** a bug: the live response includes `tags` inside each credit artist
   (verified during development; 331 artists got genres through the ISRC path). Fixed from the review: sync log file date now UTC like the `date` field;
   playlists are no longer fetched twice. Not fixed: ISRC `hit` field unused, Cyrillic/Arabic script ambiguity (documented).

## 7. Agents used
- Agent (script/ISRC): wrote `script_detect.py`, `isrc_country.py` + 106 tests; reviewed the test tables, kept as written.
- Agent (PWA): Phase 6, see `phase-6.md`. Agent (planner/sync tests): Phase 3 tests, see `phase-3.md`.
- Main session: schema/engine changes, languages table, MusicBrainz provider, cache, enricher, learning, CLI, live run, tests for these.

## 8. Next (after master decision on G1)
1. Apply the chosen language/genre strategy (e.g. English country default and/or Last.fm) and re-measure coverage with the user's real `language_playlists`.
2. Run the Phase 3 live dry-run (`python -m src.sync`) and review its log (code already written and unit-tested).
3. Phase 5 analyze mode (needs the same enrichment); Phase 4 remains behind gate G2 (user tasks).
Blockers: master answer to §5.1 and the user's language-playlist mapping.

---
## Addendum — master gate decisions applied (Phase 2 review)
1. **Gate changed:** the report now gives language coverage over the whole library AND over "target-language tracks" (tracks whose artist or the track itself appears in a
   user-mapped language playlist); the 85 % whole-library criterion is dropped, genre 49 % accepted as best-effort (`gates` block removed from `logs/enrichment-coverage.json`).
2. **Weak English default added:** Latin-script title/album + primary artist MusicBrainz country in US/GB/AU/CA/IE/NZ => `english`, source `country_default`
   (reported separately). Off-switch `enrichment.english_default` (default true) added to config schema, `Config.english_default`, the Pages builder (validator, form, YAML, tests; SW cache v2) and `config.example.yaml`.
   Note: uses the *artist's* MusicBrainz country (from the cache), not the ISRC country. Order: playlist > script > country_default > none.
3. MusicBrainz work/release language: skipped, as decided. 4. Cache stays git-ignored; `actions/cache` wiring is part of the Phase 4 `sync.yml` rewrite (currently a stub that fails at 0 s, decision 10).
5. `logs/enrichment-coverage.json` is now counts only (no artist names).
6. **BLOCKED / interim:** the user's real language mapping was not in the review message (the `<paste here>` placeholder was left in). Numbers below use my GUESSED mapping (git-ignored `config.local.yaml`), so treat them as interim:
```
tracks 773 | unique primary artists 653 | genre coverage 49.2 % of artists (best-effort, accepted)
language coverage, whole library:            53.6 %   (playlist 17, script 7, country_default 390, none 359)
language coverage, target-language tracks:  100.0 %   (17 of 17 tracks whose artists are in a mapped language playlist)
```
The whole-library figure is dominated by the weak English default (390 tracks); the target-language figure is trivially 100 % until the real mapping (which should cover far more of the library) is supplied. Please paste the mapping and I will re-run `python -m src.enrich --report`.
Tests: 707 default (+75 e2e), all green.
7. Reviewer caveats to note: (a) "target-language coverage" is near-tautological (the same playlist signal defines the denominator and resolves the language), so it says little about `language_in` reliability; a meaningful check needs held-out labelled songs. (b) The English default can mislabel non-English Latin-script songs by US/GB/... artists; the `english_default` switch exists for that. (c) The earlier commit of `logs/enrichment-coverage.json` with top-10 artist names is still in git history (counts-only from now on); say if you want history rewritten (I have not, no force-push).

### Update: user's real (partial) language mapping applied
User supplied 4 mappings ("start with these"): Dil -> hindi, The Simulation Archives -> english, NewAgeMadrasMail -> malayalam (was guessed tamil), nani mo wakaranai -> japanese.
Kept in git-ignored `config.local.yaml`; re-run `python -m src.enrich --report` (warm cache, 0 MusicBrainz requests):
```
learned from playlists: hindi 144, english 145, malayalam 101, japanese 63 tracks
language, whole library:          53.9 %  (country_default 378, playlist 32, script 7, none 356)
language, target-language tracks: 100 %   (32 of 32)   <- still near-tautological, see caveat (a) above
genre: 49.2 % of 653 artists (unchanged, best-effort)
```
Only 32 liked songs share artists/tracks with the four mapped playlists, so target-language coverage stays small. More mappings (e.g. other language playlists) will raise it.
