# Phase 5 report — Analyze mode

## 1. Verdict: **PASS**
1. Reads owned + collaborative playlists only; followed (403) skipped and reported — PASS (live: 32 analysed, 21 followed skipped, 0 unreadable; unit test asserts followed playlists are never read; a 403 on an owned/collab playlist is skipped and listed).
2. Per playlist: top genres, top artists, language distribution, year spread/era, explicit ratio — PASS (`analyze_playlist`, pure).
3. Draft rules all `enabled: false` with rationale comments; `language_playlists` suggestions at >= 70 % — PASS.
4. Never writes to Spotify or applies config — PASS (dry-run client; test asserts `dry_run=True`; output goes only to `config.draft.yaml`).
5. Real run produces a draft that passes `config.py` validation — PASS.

## 2. Proof
```
$ python -m pytest -q          -> 707 passed, 2 skipped, 75 deselected     (tests/test_analyze.py: 84 cases)
$ python -m src.analyze --no-network --config config.local.yaml
wrote config.draft.yaml: 32 playlists analysed, 21 followed skipped, 0 unreadable
$ python -c "from src.config import load_config; c=load_config('config.draft.yaml')"   -> 11 rules valid, all enabled=false
```
11 of 32 playlists received a rule; the other 21 are listed in trailing comments with the reason (too few tracks, or no distinguishing pattern).
Sample rationale (anonymised): `"<playlist>" inferred from 28 tracks: 57% of tracks are by <artist A>, <artist B>, <artist C>; 80% of tracks released 2021-2024. Review before enabling.`
Draft file is git-ignored (it contains playlist and artist names).

## 3. What was built
`src/analyze.py`: `analyze_playlist` -> `Profile`; `infer_rule` (language >= 70 %, genre >= 40 % of tagged tracks, artist group >= 3 tracks and >= 30 % coverage;
era window p10-p90 <= 15 years and explicit >= 90 % only *refine* a rule that already has a language/genre/artist condition; < 10 tracks skipped);
`render_draft` (YAML-safe quoting incl. U+2028/2029/0085, single-line comments, `language_playlists` suggestions for non-English languages, playlist names > 200 chars get no suggestion);
CLI `python -m src.analyze [--output] [--config] [--no-network]`. Language in a profile uses content signals only (script + English country default), never the user's own `language_playlists`.
`tests/test_analyze.py` written by an agent; it found two real YAML-quoting bugs (line-separator characters, >1024-char implicit keys), both fixed here.

## 4. GitHub setup
None.

## 5. Deviations / Questions for master
1. First version emitted era-only rules ("80 % released 2015-2023"), which match half the library; I changed it so era/explicit never create a rule alone. Please sanity-check the thresholds (70/40/30/15) on a real review.
2. Analysis ran `--no-network` (cache built from Liked Songs), so genres for artists that appear only in playlists are missing; a networked run would look up those artists (~1 req/s).
3. English is never suggested in `language_playlists` and never forms a drafted rule on its own (it is the weak country default; reviewer flagged it would match ~half the library). Duplicate playlist names give one suggestion.

## 6. Risks & known gaps
- "Genre" rules rely on MusicBrainz tags (49 % artist coverage); many drafted rules are therefore artist/language/era based.
- Draft quality has been reviewed by me on one library only; master review of rationale quality is still requested by the spec.

## 7. Agents used
Test-writing agent (84 cases, reviewed); spec-reviewer agent run after the code (findings in the final summary).

## 8. Next
Gate G2 for Phase 4 (see phase-3.md §8).
