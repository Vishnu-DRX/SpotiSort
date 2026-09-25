# Gate G2 report — secrets, cloud dry-run, first live write

Implementation session, 2026-09-25. Covers G2a (visibility review) and the start of G2b (live write proof).
**One deliberate deviation from the written protocol is called out below — please review it specifically.**

## 1. Verdict
- **G2a: PASS.** User ran `scripts/set_secrets.ps1` (two secrets set: `SPOTIFY_CLIENT_ID`, `SPOTIFY_REFRESH_TOKEN`). A cloud
  dry-run (`gh workflow run sync.yml -f dry_run=true`) succeeded and committed real `logs/runs.json` /
  `logs/latest-plan.json` to the repo, so Repo mode on the live dashboard now has real data.
- **G2b: PARTIAL — live write proven, but not via the specified protocol (see §3 deviation).** A single real
  `--apply` run against a real target playlist succeeded cleanly: add → verify → journal → remove → reconcile,
  verdict `ok`, nothing lost. The master's written protocol (3 test songs, target `SpotiSort Test`, then
  `--restore`) was not followed — the user explicitly chose to skip that staging step after I recommended it and
  laid out the risk. **This is a deviation from decision 15 / the Phase 4 test protocol, done with the user's
  informed, explicit consent, not a silent shortcut.**
- Not done yet: the 3-song protocol, a `--restore` round-trip proof, cron confirmation, Phase 7, Phase 8b.

## 2. Proof
```
$ gh workflow run sync.yml -f dry_run=true          (cloud, read-only)
run 36168073709: success. "DRY RUN: evaluated 774 liked songs; no writes performed. would move: 1"
-> logs/runs.json, logs/latest-plan.json committed to main by the workflow (bce4ac7 "Update run logs [skip ci]")
```
Config used (`config.yaml`, committed at `870dcfd`): 5 rules, 4 mirroring the user's real language playlists plus a
disabled catch-all, **all disabled except one** (`"Malayalam -> NewAgeMadrasMail (draft)"`, `days_threshold: 0` —
a deliberate test-only override so a same-day like would show as eligible immediately instead of after 14 days).

User liked one real Malayalam-language song, confirmed by the dry-run as correctly detected (`language_in:
malayalam`, decision `will_move`, target `NewAgeMadrasMail`).

Live apply, run **locally by the user** (not through this session — `--apply` is denied to me in
`.claude/settings.json` and I did not attempt to work around that):
```
PS> python -m src.sync --apply --newest 1 --config config.yaml
APPLIED: evaluated 1 liked songs; moved 1, confirmed in playlists 1, errors 0.
  -> NewAgeMadrasMail: 1
log: logs\2026-09-25-2.json
```
Log detail (local file, git-ignored, contains the real title — not shown here; sanitised):
```
mode: apply | verdict: ok | liked_before: 774 | liked_after: 773
reconcile: {removed: 1, expected_after: 773, actual_after: 773, lost: 0, resurrected: 0, gone_from_target: 0, ok: True}
batches: add_to_playlist committed=True, remove_from_liked committed=True
journal: 1 entry (uri, original title/artist, original_added_at, target_playlist_id) — kept locally for --restore
```
**User confirmed visually in the Spotify app:** song present in `NewAgeMadrasMail`, gone from Liked Songs.
User chose to leave it moved (no `--restore` was run).

## 3. Deviation — please review
The written protocol (Master decisions 2 item 15, Phase 4 test protocol) specifies the *first* live `--apply`
should target the disposable `SpotiSort Test` playlist, verified, then restored, before ever pointing a rule at a
real playlist. I proposed exactly that to the user, including preparing the config change for them. **The user
explicitly declined the staging step and asked to run directly against their real `NewAgeMadrasMail` playlist.**
I stated the restriction and the reasoning, confirmed they understood the write path was unproven live, and once
they still chose to proceed I gave them the exact command to run themselves (I remained blocked from running it).
The result was clean (see §2), which is reassuring but does not retroactively make this the specified test
sequence. Flagging for the record rather than treating it as equivalent to the planned protocol.

## 4. What was built / changed
- `config.yaml` — first committed live config. All 5 rules present, 4 disabled drafts, one enabled for this test
  with a temporary `days_threshold: 0`. **This override should be reviewed** — it is fine for a single test but is
  not what you'd want for real operation (14 days is the intended default; the override was scoped to this one
  rule only, not the global default).
- No `src/` or workflow changes this round; U1/U2/U3 code from the previous report is what carried this out.

## 5. Open items before G2b can be called done
1. **Cron time not confirmed with the user** — `sync.yml` has no `schedule:` trigger yet; `SPOTISORT_CRON` repo
   variable is unset (Overview correctly shows "Not scheduled").
2. **No `--restore` round-trip has been exercised live** — the restore path is fully unit-tested against a
   simulator (Phase 4 non-live report) but never run against real Spotify. The user's own song stayed moved, so
   this remains unproven live.
3. **`days_threshold: 0` on the live rule should be reviewed/removed** now that the test is over, or intentionally
   kept if the user wants Malayalam songs to move immediately going forward rather than after 14 days.
4. Master should decide whether §3's deviation needs anything further (e.g. still wants a `SpotiSort Test` proof
   done at some point, or considers the real-playlist proof sufficient going forward).

## 6. Risks & known gaps
- Only one live write has ever happened; batch behaviour at scale (>1 song, >100 items, multiple playlists in one
  run) remains unverified live, only against the fake-based test suite.
- The moved song's `NewAgeMadrasMail` entry uses `target_position: bottom` (the rule's default) — `top` insertion
  (`position: 0` in the API body) is still unverified live, since this test rule doesn't use it.

## 7. Next
1. Ask the user for a cron time if/when they want scheduled runs; wire `schedule:` + `SPOTISORT_CRON` accordingly.
2. Optionally prove `--restore` live on a low-stakes song.
3. Master's call on Phase 7 (GitHub write-back — PAT-flow, per the CORS finding in `phase-U.md`) vs. 8b (run-now
   button, liked-songs guardian) as the next body of work.
