# Phase 4 (non-live) report — guarded apply, restore, guards, workflow

**Nothing here has touched the real Spotify library.** `--apply` and `--restore --apply` were never run by this session (denied in settings and not attempted);
every write path is proven against an in-memory Spotify simulator with fault injection. Live proof is the G2 protocol (user + master present).

## 1. Verdict: **PASS for the non-live scope** (live criteria 1, 3, 4, 5 of Phase 4 remain for G2)
- Add -> confirm -> journal -> remove -> verify -> reconcile implemented exactly as cross-cutting rule 1 — PASS (simulator).
- Injected failures never lose a song — PASS (see proof).
- `--restore` — PASS (simulator); live restore is part of G2.
- Per-batch results (decision 9), guards (decision 12), `sync.yml` rewrite + cache (decision 10) — PASS.

## 2. Proof
```
$ python -m pytest -q      -> 1485 passed, 2 skipped        (apply 115, restore 47, sync-apply 42, client-batched 92, workflows 12 among them)
```
- Property test (250 seeded random fault schedules over random libraries/plans): for every song in the plan, the song is still liked **or** present in the playlist it was journaled to (never neither);
  songs outside the plan never leave Liked Songs; every removed song has a journal entry; the journal is written before the first removal; a journal failure means zero removals.
- Directed failure injection (all pass): add fails / fails mid-way / phantom add (never shows) / read-after-write lag within and beyond the poll / journal writer raises / remove batch fails /
  removal reports ok but does not stick / a liked song vanishes unrelated to us (re-added) / contains() lies / new like during the run / API error while verifying (result returned, journal on disk, exit non-zero).
- Ordering assertions: adds before journal before first removal; nothing removed that was not confirmed present in its playlist.
- `top` insertion end-to-end in the simulator: newest ends at index 0, existing order untouched below, >1 batch (oldest chunk inserted first).

## 3. What was built
- `src/apply.py`: `apply_moves` (guards, add, confirm by re-read, journal callback before removal, **fresh Liked-Songs baseline right before removal**, remove, verify with contains + list, reconcile by ID sets, **re-read target playlists after removal**),
  exit codes 0 ok / 4 too many moves / 5 reconcile mismatch / 6 partial failure; `restore_from_log` (re-adds only songs not liked; `--remove-from-target` optional and never removes songs that were already in the playlist before the run).
- `src/spotify_client.py`: `*_batched` writers returning per-batch `BatchOutcome`s (a failed batch stops the rest and is reported, never raised away); `position` body field for playlist adds; legacy wrappers unchanged.
- `src/sync.py`: `--apply` requires `--newest N` or `--only-uris` (or `--allow-unselected`, not exposed by the workflow), `--max-moves` (default 50, hard ceiling 500), `--restore LOG [--remove-from-target]`, apply logs never overwritten
  (`YYYY-MM-DD-2.json`...) and dry runs never overwrite an apply log; run log gets journal, batches, reconcile, `restore_command`, verdict; `runs.json`/`latest-plan.json` updated for every run.
- `.github/workflows/sync.yml`: manual only (`workflow_dispatch`); `dry_run` input default **true**; live run requires the `newest` input; `max_moves` capped in-script; concurrency group; `actions/cache` for `.cache/enrichment.json`
  (unique key per run + `restore-keys` prefix; cache never committed); only the two Spotify secrets; inputs reach the shell only via `env:`; run logs force-added with `git add -f` and a bot identity, `[skip ci]`.
  `tests/test_workflows.py` pins these properties. **No schedule is enabled** until you confirm the cron time at G2. No secrets were set.
- Decision 10 (the 0 s workflow failure): every push to `main` produced a run of the *old* `sync.yml` that GitHub reported as "workflow file issue" (0 s, no jobs). The rewritten file parses (workflow listed as "Sync", active) and no longer runs on push.
  I could not identify the exact defect in the old file (GitHub gives no message); it is gone with the rewrite.

## 4. GitHub setup
`gh` used read-only (`gh run list/view`, `gh api .../actions/workflows`) to investigate; no settings or secrets were changed.

## 5. Deviations / Questions for master
1. An adversarial review of `apply.py` found no path that loses a liked song or writes in dry-run, and listed hardening items, all fixed: restoring a **dry-run** log would have removed songs from playlists
   (now `load_journal` accepts apply logs only); journals could be overwritten by a later same-day run (unique names); a read error after removal left an `in_progress` log (now a reported result, exit 5);
   the reconcile baseline was stale (fresh read before removal); a playlist could drop a confirmed song after removal (re-read + re-add to Liked Songs); the workflow exposed an unselected live run (removed) and an unbounded `max_moves` (capped at 500).
2. Journal durability on Actions: the journal is only committed by the last workflow step; a hard-killed runner loses it (songs are still in their playlists). Acceptable? Alternative: commit the journal right after the playlist adds.
3. Log files contain song titles; the workflow force-adds them to a public repo (accepted by the user). The `logs/.tmp-*` atomic-write temp files are now git-ignored.

## 6. Risks & known gaps
- Live behaviour of `position: 0`, of batch chunking near 100, and of Spotify's read-after-write lag windows is unverified; the simulator encodes the documented behaviour.
- Reconcile treats a concurrent unlike by the user as `lost` only if it happens between the baseline read and the after-read (small window); the tool then re-adds it (resetting `added_at`).
- `contains_saved` lag beyond 5 polls is handled by trusting the Liked Songs list, which is itself eventually consistent.

## 7. Agents used
One test agent wrote `tests/fakes.py` (simulator) and the apply/restore/sync-apply/batched-client suites (~490 cases) and reported 6 src issues, all fixed; an adversarial reviewer agent reported 9 findings, the material ones fixed (§5.1). I wrote all of `src/apply.py`, the client writers, and the sync integration.

## 8. Next — Gate G2 (needs the user)
1. Master signs off the backtest + dashboard. 2. User: run `scripts/set_secrets.ps1`, confirm cron time, like 3 fresh songs. 3. Session runs the live `SpotiSort Test` protocol (`--apply --newest 3` with a `days_threshold: 0`, `target_position: top` test rule,
   verify with the user in Spotify, `--restore`), then a cloud dry-run and one real run.
