# Dashboard data contract (all files are JSON, `"version": 1`)

The dashboard is static. It reads these files from a *source*: **Local** (`/data/<file>` served by `python -m src.dashboard`
from the repo's `logs/` folder) or **Repo** (`https://raw.githubusercontent.com/<owner>/<repo>/main/logs/<file>`).
Every file carries `generated_at` (ISO-8601 UTC): show it as the **data-freshness stamp**; older than 2 days => warning banner.
Missing file => empty state that says which command produces it. Song/playlist names appear in the plan/detail files.

## `runs.json` — rolling index (newest first, max 90)
`{version, generated_at, schedule:{cron, description, next_run}|null, runs:[{run_id, time, mode ("dry_run"|"apply"), what_if, planned_moves, moved, too_young, no_match,
blocked, target_problems, errors, warnings, liked_before, liked_after, duration_seconds, verdict ("dry_run"|"ok"|"mismatch"|"error"),
rule_counts:{rule_name: wins}, moves_by_playlist:{playlist_name: n}, log:"YYYY-MM-DD.json"}]}`
`schedule` is written by the workflow from its cron (decision 34); null/absent = "Not scheduled" on the Overview.

## `YYYY-MM-DD.json` — per-run log (fetched on demand from `runs[].log`)
`{date, run_id, mode, dry_run, what_if, evaluated, moved:[{track, artist, uri, playlist, playlist_id, rule, matched, age_days,
threshold_days, already_in_target, original_added_at, target_position}], skipped_no_match, skipped_too_young:[...],
skipped_playlist_missing:[{track,target_playlist,rule,reason,would_create}], errors:[str], warnings:[str],
journal:[{uri,name,artists,original_added_at,target_playlist_id}], liked_before, liked_after, verdict, rule_counts, config_hash,
plan_counts, http_audit:{"GET api.spotify.com":n,...}, runtime_seconds, titles_hidden (present+true when logging.include_track_names is false on a GitHub Actions run: track/artist fields are null; local runs always keep titles)}`
Apply runs (Phase 4) add `reconcile:{expected_after, actual_after, ok}`, `restore_command` (string), `batches:[{playlist_id, size, committed}]`.

## `latest-plan.json` — inbox snapshot
`{version, generated_at, run_id, mode, what_if, inbox_kind ("legacy_library"|"fresh_inbox"), config_hash, liked_total,
default_days_threshold, english_default, counts:{will_move,too_young,no_match,target_problem,blocked},
rules:[{name, enabled, target_playlist, target_position ("top"|"bottom"), threshold_days, conditions:{key:value}, uses_language,
weak_signals_possible:[..], would_match, wins, target_status ("resolved"|"missing"|"not_writable"|"ambiguous"),
status ("ok"|"dead"|"shadowed"|"disabled")}],
playlists:[{name, status, size, planned_in, rules:[rule names]}],
songs:[{title, artists:[..], uri, added_at, age_days, decision ("will_move"|"too_young"|"no_match"|"target_problem"|"blocked"),
reason, rule|null, target_playlist|null, target_status|null, eligible_on|null, target_position|null,
language:{value|null, source ("playlist"|"script"|"hint"|"country_default")|null, confidence 0..1|null, used_for_rules:bool, withheld:{language,source,precision,samples,reason}|null},
genres:{values:[..], source|null, confidence|null},
titles_hidden (present+true on a titles-redacted snapshot: title/artists are null; open local files to see them),
explain:{trace:[{rule, enabled, threshold_days, conditions:[{key,wanted,actual,passed}],
  result ("matched"|"matched_too_young"|"failed"|"not_reached"|"not_reached_but_would_match"|"skipped_disabled"|"skipped_empty")}],
  decided_by|null, age_days}}]}`
Rule `status`: `dead` = no song would match it; `shadowed` = songs would match but an earlier rule always wins; `disabled`.
`what_if:true` means disabled rules were treated as enabled (preview) — show a clear banner.

## `enrichment-coverage.json` (counts only)
`{date, tracks, unique_primary_artists, genre_coverage_pct_of_artists, language_coverage_pct_whole_library,
language_coverage_pct_target_language_tracks, target_language_tracks, target_language_tracks_resolved,
language_source_counts:{playlist,script,hint,country_default,none}, language_distribution:{lang:n}, genre_source_counts, musicbrainz:{requests,retries_after_503_or_429,errors}}`

## `signal-precision.json` (counts only) — per-signal accuracy from backtest ground truth
`{version, generated_at, min_precision:0.9, min_samples:10, by_signal:{ "<signal>": { "<language>": {truth, predicted, correct, precision|null, recall|null} } },
qualified:{ "<language>": ["playlist","script",...] }}` where signals are `playlist` (leave-one-out), `script`, `hint`, `country_default`.

## `backtest.json` (counts only; playlists labelled P01..)
`{version, generated_at, config_hash, all_rules_enabled:bool, inbox:{tracks, playlists}, playlists:[{id, tracks, predicted, tp, precision|null, recall|null, unrouted}],
confusions:[{true, predicted, count}], totals:{tracks, routed, correct, misrouted, unrouted, precision|null, recall|null},
rules:[{name_id ("R01"..), predicted, correct, precision|null}]}`

## `backtest-detail.json` (git-ignored; Local mode only — has names)
Same shape as `backtest.json` plus `playlists[].name`, `rules[].name`, and `top_misroutes:[{title, artists, true:[playlist names], predicted, rule}]`.
When present (Local mode) the Backtest view shows names instead of P01/R01 labels.
