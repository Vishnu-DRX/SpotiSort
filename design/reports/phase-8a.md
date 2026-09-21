# Phase 8a report — Visibility: artifacts, backtest, language tiers, target_position, dashboard

Implementation session, 2026-09-21/22. Steps 1-6 of the master's brief. **No `--apply` of any kind was run** (denied by settings; all
write paths are proven against an in-memory simulator only). No song or playlist names appear in this report.

## 1. Verdict: **PASS** (visibility complete; master + user review of the local dashboard is the next gate)
1. Artifacts (decision 18) — PASS: `runs.json`, per-run log extensions, `latest-plan.json` (explain traces, tiers/confidence), counts-only coverage/backtest/signal JSON.
2. Backtest (decision 13) — PASS: `python -m src.backtest`, per-playlist precision/recall + confusion, per-signal precision, names only in git-ignored files.
3. Language upgrades — PASS: hint tier (MusicBrainz tag/area), `english_default` default FALSE, only qualified signals drive rules.
4. `target_position` (decision 14) — PASS offline (config, builder, planner ordering, `insert_batches`, client `position` body); **not verified live** (by instruction).
5. Dashboard (decision 19) — PASS: 8 views + Explain drawer, Local + Repo + Demo sources, freshness/stale/empty/error states, dark/light, 375/1280.
6. Real data for the user — PASS: real dry-run (what-if) + backtest rendered locally; dashboard running at http://127.0.0.1:8787/dashboard/?source=local

## 2. Proof
```
$ python -m pytest -q                 -> 1481 passed, 2 skipped        (e2e deselected by default)
$ python -m pytest tests/e2e -q -m e2e -> 141 passed                   (52 dashboard tests + builder/PWA; Edge locally)
$ python -m src.backtest --config config.local.yaml --all-rules
  2625 unique tracks from 32 playlists | routed 2623 | correct 917 | misrouted 1706 | unrouted 2 | precision 0.35 | recall 0.35
$ python -m src.sync --config config.local.yaml --what-if-enable-all      (real library, read-only, 15 s, warm cache)
  DRY RUN: evaluated 773 liked songs; no writes performed. would move 773 (what-if: all draft rules enabled)
$ dashboard smoke: /dashboard/ -> 200; /data/runs.json -> 200; /data/../config.local.yaml -> 404; port bound exclusively (see §5.3)
```
Local screenshots of every view at 375 and 1280 px (real data): git-ignored `logs/screens/` (no console errors, no horizontal overflow at 375 on any view).
Fixture-based screenshots for review are committed: `docs/screenshots/dashboard-<view>-{375,1280}.png`.

Backtest, counts only (draft rules from the user's four language mappings + a top-position catch-all, all enabled for the test):
| rule (draft) | predicted | correct | precision |
|---|---|---|---|
| hindi -> its playlist | 123 | 102 | 83 % |
| malayalam -> its playlist | 102 | 83 | 81 % |
| japanese -> its playlist | 70 | 40 | 57 % |
| english -> its playlist | 95 | 10 | 11 % |
| catch-all -> vault (top) | 2233 | 682 | 31 % (a vault contains only some songs; not a quality target) |

Per-signal precision (measured on tracks inside the four mapped language playlists; playlist signal is leave-one-out):
| language | playlist | script | hint | country_default |
|---|---|---|---|---|
| hindi | 100 % (102 of 102), recall 71 % | no predictions (titles are romanised) | 100 % (10 of 10) | none |
| malayalam | 99 % (83 of 84), recall 82 % | none | none | none |
| japanese | 100 % (20/20), recall 32 % | 100 % (24/24), recall 38 % | 97 % (32/33), recall 51 % | none |
| english | 100 % (10/10), recall 7 % | none | 100 % (2/2) | 93 % (78/84), recall 54 % |
Qualification (>= 90 % precision and >= 10 predictions, or trusted-by-design playlist/script): hint qualifies for **japanese**; hint for hindi has only 10 samples
(qualifies at exactly the minimum); `country_default` qualifies for **english**. Full table in `logs/signal-precision.json` (`qualified`).

## 3. What was built
- **Artifacts** (`src/artifacts.py`, `src/signals.py`, `src/rules_engine.explain`): `latest-plan.json` = every liked song with decision (`will_move|too_young|no_match|target_problem|blocked`),
  rule, target, `eligible_on`, `target_position`, language/genre with source tier + confidence + *withheld* info, and a rule-by-rule explain trace; rules get `would_match`/`wins`/status
  (`ok|dead|shadowed|disabled`); `runs.json` rolling 90; per-run log gains run_id, mode, liked_before/after, verdict, rule_counts, config hash, plan counts, batches/reconcile (apply).
  `--what-if-enable-all` previews disabled draft rules.
- **Backtest** (`src/backtest.py`): simulated inbox = tracks of owned/collaborative playlists (true home = the playlist(s) they are in); real first-match logic, age ignored; outputs
  `backtest.json` + `signal-precision.json` (counts, playlists P01.., rules R01..) and git-ignored `backtest-detail.{json,md}` with names and top misroutes.
- **Language tiers**: playlist (leave-one-out capable) > script > **hint** (`src/enrichment/hints.py`: MusicBrainz tags such as scene/language names + mono-lingual artist country) > `country_default`
  (only if `enrichment.english_default: true`, now default false). Gate (`signals.gate`): playlist/script trusted by design; hint/country_default must have measured precision >= 90 % with >= 10 samples,
  else the language is *withheld* from rule matching and shown as `blocked` in the dashboard.
- **target_position** (`top|bottom`, default bottom): `config.py`, builder (validator, form, YAML, parity tests), planner ordering (newest first per playlist), `insert_batches` (top: oldest chunk first at position 0), client `position` body field.
- **Dashboard** (`docs/dashboard/`, `docs/assets/tokens.css`, `src/dashboard.py`): Overview, Inbox (+Explain drawer), Rules, Playlists, Runs (+diff), Safety, Signals, Backtest; data contract in `docs/dashboard/DATA.md`;
  fixtures generated from the real builders (`scripts/make_dashboard_fixtures.py`); README "How to read the dashboard".
- Config: `enrichment.english_default` default false; `config.example.yaml` updated with a top-position vault example (disabled). SW cache bumped to v4; builder header links to the dashboard.

## 4. GitHub setup
`sync.yml` rewritten (see `phase-4-nonlive.md`). No repo settings changed.

## 5. Deviations / Questions for master
1. **Master decisions 4 (product-quality site, U1 design system -> U2 Configure -> U3 dashboard) arrived while the dashboard agent was mid-flight.** I did not restart it; instead the dashboard was told to
   consume a tokens file (`docs/assets/tokens.css`, decision-22 tokens) so the later re-skin is a token/component swap. The site shell, Home, Setup guide, Configure redesign (stepper, templates, versions),
   kitchen-sink, axe/Lighthouse gates and 3-browser matrix are **not built yet** — that is the next block of work. Please confirm the order (dashboard first was your explicit instruction to me).
2. Hindi/Malayalam **script** signal never fires on this library (Spotify titles are romanised), so those languages depend on the playlist-learned tier (recall 71 % / 82 % leave-one-out) — expected, but it means
   language rules only work for artists the user has already mapped; a fresh user starts with low recall until language playlists exist.
3. **The dashboard server shares nothing**: another program on this machine already listened on port 8765 and, because Windows allows two sockets on one port with SO_REUSEADDR, my server silently co-bound it
   (requests would have been split between the two programs). Fixed: default port is now 8787 and the server binds exclusively. Worth a line in your review.
4. Precision is estimated only inside the four mapped language playlists; languages without a mapped playlist (e.g. tamil) cannot be measured and therefore cannot be qualified for hint/country_default.
5. `enrichment-coverage.json`: whole-library language coverage is now 17 % (hint tier only 93 tracks; english_default off) — informational on the legacy library.

## 6. Risks & known gaps
- `target_position` / `position` in the POST body is unverified against Spotify; verify on `SpotiSort Test` at G2 (3 new likes, add at top, read back).
- Dashboard: Playlists view has no "moves out" column (not derivable), Safety "vanished songs" is a placeholder (decision 16 not built), Overview reads an optional `schedule` field that nothing writes yet.
- Repo mode of the dashboard is only tested against fixtures (the real fork logs do not exist until the workflow commits them).
- The backtest treats playlist membership as truth; songs that legitimately fit several playlists count as misroutes when the rule picks another home.

## 7. Agents used
Dashboard UI + server + e2e (1 long agent); builder update for target_position/english default; test agents for artifacts/signals/backtest/hints/insert_batches (~200 cases) and apply/restore failure injection
(see phase-4-nonlive.md). I wrote artifacts, signals, backtest, hint tier, client/apply changes, and reviewed/fixed agent findings (all agent-reported src bugs were fixed).

## 8. Next
1. Review the local dashboard with the user (real data). 2. Master decisions 4: U1 design system + site shell, U2 Configure, U3 dashboard re-skin + quality gates. 3. Gate G2 (user tasks) then live `SpotiSort Test` protocol.
