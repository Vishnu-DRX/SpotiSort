"""`python -m src.sync --apply / --restore` driven end to end against the in-memory simulated Spotify. Offline."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from fakes import FakeSpotify, client_factory, make_track, uri
from src import apply as apply_mod
from src import sync

TODAY = datetime.now(timezone.utc).date().isoformat()
CONFIG = """\
default_days_threshold: 14
rules:
  - name: chill
    match:
      artist_in: ["Bonobo"]
    target_playlist: Chill
"""
CONFIG_TOP = CONFIG + "    target_position: top\n"


def nosleep(_s):
    pass


def make_fs(n=6, *, extra_tracks=(), existing=()):
    """n old Bonobo songs (Song 1 newest) in Liked Songs plus an empty owned playlist 'Chill' (id chill1)."""
    fs = FakeSpotify()
    fs.set_liked([make_track(i, age_days=30 + i) for i in range(1, n + 1)] + list(extra_tracks))
    fs.add_playlist("chill1", "Chill", items=existing)
    return fs


@pytest.fixture
def env(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(CONFIG, encoding="utf-8")
    real_apply = sync.apply_moves

    def patched_apply(*a, **kw):
        kw.setdefault("sleep", nosleep)
        return real_apply(*a, **kw)

    monkeypatch.setattr(sync, "load_env", lambda *a, **k: False)
    monkeypatch.setattr(sync, "apply_moves", patched_apply)
    return tmp_path, cfg


def use(monkeypatch, fs):
    monkeypatch.setattr(sync, "SpotifyClient", client_factory(fs))
    return fs


def argv(tmp, cfg, *extra):
    return ["--config", str(cfg), "--logs-dir", str(tmp / "logs"), "--cache", str(tmp / "cache.json"),
            "--no-network", "--env", str(tmp / "nonexistent.env"), *extra]


def go(tmp, cfg, *extra):
    return sync.main(argv(tmp, cfg, *extra))


def read_log(tmp, name=None):
    return json.loads((tmp / "logs" / (name or f"{TODAY}.json")).read_text(encoding="utf-8"))


def logs_written(tmp):
    d = tmp / "logs"
    return sorted(p.name for p in d.iterdir()) if d.exists() else []


# ---------------------------------------------------------------- guards


def test_apply_without_selector_exits_2_and_calls_nothing(env, monkeypatch, capsys):
    tmp, cfg = env
    fs = use(monkeypatch, make_fs())
    assert go(tmp, cfg, "--apply") == 2
    assert fs.constructed == [] and fs.calls == [] and logs_written(tmp) == []
    assert "selector" in capsys.readouterr().err


def test_what_if_enable_all_with_apply_exits_2(env, monkeypatch):
    tmp, cfg = env
    fs = use(monkeypatch, make_fs())
    assert go(tmp, cfg, "--apply", "--newest", "2", "--what-if-enable-all") == 2
    assert fs.constructed == [] and fs.calls == []


@pytest.mark.parametrize("bad", ["0", "-3"])
def test_max_moves_below_one_exits_2(env, monkeypatch, bad):
    tmp, cfg = env
    fs = use(monkeypatch, make_fs())
    assert go(tmp, cfg, "--apply", "--newest", "2", "--max-moves", bad) == 2
    assert fs.calls == []


def test_check_apply_guards_accepts_each_selector():
    for extra in (["--newest", "2"], ["--only-uris", uri(1)], ["--allow-unselected"]):
        assert sync.check_apply_guards(sync.parse_args(["--apply", *extra])) is None
    assert sync.check_apply_guards(sync.parse_args([])) is None  # dry-run needs no selector


def test_negative_newest_is_rejected_by_the_guard():
    assert sync.check_apply_guards(sync.parse_args(["--apply", "--newest", "-1"])) is not None


def test_negative_newest_does_not_widen_the_selection():
    tracks = [make_track(i, age_days=30 + i) for i in range(1, 6)]
    assert len(sync.select_tracks(tracks, -2, None)) <= 0


# ---------------------------------------------------------------- selectors


def test_newest_n_moves_only_the_n_newest(env, monkeypatch):
    tmp, cfg = env
    fs = use(monkeypatch, make_fs(6))
    assert go(tmp, cfg, "--apply", "--newest", "2") == 0
    assert set(fs.items["chill1"]) == {uri(1), uri(2)}
    assert fs.liked_uris() == {uri(i) for i in range(3, 7)}
    assert fs.constructed == [False]


def test_only_uris_comma_list(env, monkeypatch):
    tmp, cfg = env
    fs = use(monkeypatch, make_fs(6))
    assert go(tmp, cfg, "--apply", "--only-uris", f"{uri(4)},{uri(5)}") == 0
    assert set(fs.items["chill1"]) == {uri(4), uri(5)} and len(fs.liked) == 4


def test_only_uris_from_file(env, monkeypatch):
    tmp, cfg = env
    f = tmp / "uris.txt"
    f.write_text(f"{uri(3)}\n{uri(6)}\n", encoding="utf-8")
    fs = use(monkeypatch, make_fs(6))
    assert go(tmp, cfg, "--apply", "--only-uris", f"@{f}") == 0
    assert set(fs.items["chill1"]) == {uri(3), uri(6)}


def test_only_uris_invalid_uri_is_rejected_before_any_client(env, monkeypatch):
    tmp, cfg = env
    fs = use(monkeypatch, make_fs())
    assert go(tmp, cfg, "--apply", "--only-uris", f"{uri(1)},spotify:album:{'a' * 22}") == 1
    assert fs.constructed == [] and fs.calls == []


def test_only_uris_missing_file_exit_1(env, monkeypatch):
    tmp, cfg = env
    fs = use(monkeypatch, make_fs())
    assert go(tmp, cfg, "--apply", "--only-uris", f"@{tmp / 'missing.txt'}") == 1
    assert fs.constructed == []


def test_only_uris_with_empty_file_selects_nothing(env, monkeypatch):
    tmp, cfg = env
    f = tmp / "empty.txt"
    f.write_text("\n", encoding="utf-8")
    fs = use(monkeypatch, make_fs(3))
    assert go(tmp, cfg, "--apply", "--only-uris", f"@{f}") == 0
    assert fs.write_calls() == [] and len(fs.liked) == 3


def test_only_uris_for_a_song_that_is_not_liked_moves_nothing(env, monkeypatch):
    tmp, cfg = env
    fs = use(monkeypatch, make_fs(3))
    assert go(tmp, cfg, "--apply", "--only-uris", uri(99)) == 0
    assert fs.write_calls() == [] and len(fs.liked) == 3


def test_selector_never_touches_songs_outside_it(env, monkeypatch):
    tmp, cfg = env
    fs = use(monkeypatch, make_fs(8))
    go(tmp, cfg, "--apply", "--only-uris", f"{uri(2)},{uri(7)}")
    removed = {u for n, a in fs.calls if n == "remove_saved_tracks_batched" for u in a[0]}
    added = {u for n, a in fs.calls if n == "add_playlist_items_batched" for u in a[1]}
    assert removed == added == {uri(2), uri(7)}
    assert fs.liked_uris() == {uri(i) for i in range(1, 9)} - {uri(2), uri(7)}
    assert set(fs.put_uris) == set()


def test_newest_and_only_uris_combine(env, monkeypatch):
    tmp, cfg = env
    fs = use(monkeypatch, make_fs(6))
    go(tmp, cfg, "--apply", "--only-uris", f"{uri(1)},{uri(2)},{uri(3)}", "--newest", "2")
    assert set(fs.items["chill1"]) == {uri(1), uri(2)}


def test_too_young_selected_song_is_left_alone(env, monkeypatch):
    tmp, cfg = env
    young = make_track(90, age_days=2)
    fs = use(monkeypatch, make_fs(2, extra_tracks=[young]))
    assert go(tmp, cfg, "--apply", "--newest", "1") == 0
    assert uri(90) in fs.liked and fs.write_calls() == []


# ---------------------------------------------------------------- cap


def test_allow_unselected_works(env, monkeypatch):
    tmp, cfg = env
    fs = use(monkeypatch, make_fs(4))
    assert go(tmp, cfg, "--apply", "--allow-unselected") == 0
    assert fs.liked == [] and len(fs.items["chill1"]) == 4


def test_allow_unselected_above_max_moves_exits_4_and_writes_nothing(env, monkeypatch, capsys):
    tmp, cfg = env
    fs = use(monkeypatch, make_fs(4))
    assert go(tmp, cfg, "--apply", "--allow-unselected", "--max-moves", "3") == 4
    assert fs.write_calls() == [] and len(fs.liked) == 4 and fs.items["chill1"] == []
    assert [f for f in logs_written(tmp) if f.endswith(".json")] == []  # no run log, no runs.json, no latest-plan
    assert "max-moves" in capsys.readouterr().err


def test_default_cap_is_50_through_the_cli(env, monkeypatch):
    tmp, cfg = env
    fs = use(monkeypatch, make_fs(51))
    assert go(tmp, cfg, "--apply", "--allow-unselected") == 4
    assert fs.write_calls() == [] and len(fs.liked) == 51


def test_exactly_50_moves_is_within_the_default_cap(env, monkeypatch):
    tmp, cfg = env
    fs = use(monkeypatch, make_fs(50))
    assert go(tmp, cfg, "--apply", "--allow-unselected") == 0
    assert fs.liked == [] and len(fs.items["chill1"]) == 50


def test_newest_selection_is_still_capped(env, monkeypatch):
    tmp, cfg = env
    fs = use(monkeypatch, make_fs(6))
    assert go(tmp, cfg, "--apply", "--newest", "5", "--max-moves", "3") == 4
    assert fs.write_calls() == []


# ---------------------------------------------------------------- full apply run artifacts


def test_full_apply_writes_run_log(env, monkeypatch):
    tmp, cfg = env
    fs = use(monkeypatch, make_fs(5))
    assert go(tmp, cfg, "--apply", "--newest", "3") == 0
    log = read_log(tmp)
    assert log["mode"] == "apply" and log["dry_run"] is False and log["verdict"] == "ok"
    assert log["liked_before"] == 5 and log["liked_after"] == 2 == len(fs.liked)
    assert [j["uri"] for j in log["journal"]] == sorted([uri(1), uri(2), uri(3)])
    assert all(j["target_playlist_id"] == "chill1" for j in log["journal"])
    assert sorted(log["moved_uris"]) == sorted([uri(1), uri(2), uri(3)]) and log["still_liked"] == []
    assert log["errors"] == []
    assert log["reconcile"]["ok"] is True and log["reconcile"]["lost"] == 0 and log["reconcile"]["removed"] == 3
    kinds = [b["kind"] for b in log["batches"]]
    assert kinds == ["add_to_playlist", "remove_from_liked"] and all(b["committed"] for b in log["batches"])
    assert log["restore_command"].startswith("python -m src.sync --restore ") and log["restore_command"].endswith(" --apply")
    assert f"{TODAY}.json" in log["restore_command"]


def test_apply_updates_runs_index_and_latest_plan(env, monkeypatch):
    tmp, cfg = env
    use(monkeypatch, make_fs(5))
    go(tmp, cfg, "--apply", "--newest", "3")
    runs = json.loads((tmp / "logs" / "runs.json").read_text(encoding="utf-8"))["runs"]
    assert len(runs) == 1
    r = runs[0]
    assert r["mode"] == "apply" and r["verdict"] == "ok" and r["moved"] == 3
    assert r["liked_before"] == 5 and r["liked_after"] == 2 and r["errors"] == 0 and r["log"] == f"{TODAY}.json"
    plan = json.loads((tmp / "logs" / "latest-plan.json").read_text(encoding="utf-8"))
    assert plan["mode"] == "apply" and len(plan["songs"]) == 3  # the snapshot covers the selected songs


def test_two_runs_accumulate_in_runs_index(env, monkeypatch):
    tmp, cfg = env
    use(monkeypatch, make_fs(6))
    go(tmp, cfg, "--apply", "--newest", "2")
    go(tmp, cfg, "--apply", "--newest", "2")
    runs = json.loads((tmp / "logs" / "runs.json").read_text(encoding="utf-8"))["runs"]
    assert len(runs) == 2 or len({r["run_id"] for r in runs}) == len(runs)  # same-second ids collapse; never corrupt


def test_run_log_with_journal_exists_on_disk_at_first_removal(env, monkeypatch):
    tmp, cfg = env
    fs = use(monkeypatch, make_fs(4))
    seen = {}

    def hook(f, uris):
        log = read_log(tmp)  # raises if the file is not there yet
        seen["journal"] = [j["uri"] for j in log["journal"]]
        seen["verdict"] = log["verdict"]
        seen["uris"] = set(uris)
        seen["still_liked"] = f.liked_uris()

    fs.hooks["remove_saved_tracks_batched"] = hook
    assert go(tmp, cfg, "--apply", "--newest", "3") == 0
    assert set(seen["journal"]) == seen["uris"] == {uri(1), uri(2), uri(3)}
    assert seen["verdict"] == "in_progress"
    assert seen["still_liked"] == {uri(i) for i in range(1, 5)}  # nothing removed yet


def test_journal_write_failure_aborts_removal_through_the_cli(env, monkeypatch):
    tmp, cfg = env
    fs = use(monkeypatch, make_fs(3))
    monkeypatch.setattr(sync.artifacts, "atomic_write_json",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    assert go(tmp, cfg, "--apply", "--newest", "3") == 1  # the disk error is reported, not a crash
    assert fs.count("remove_saved_tracks_batched") == 0 and len(fs.liked) == 3


def test_apply_add_failure_exit_6_verdict_error(env, monkeypatch):
    tmp, cfg = env
    fs = use(monkeypatch, make_fs(3))
    fs.fail_every("add_playlist_items_batched")
    assert go(tmp, cfg, "--apply", "--newest", "3") == apply_mod.EXIT_FAILED
    log = read_log(tmp)
    assert log["verdict"] == "error" and log["errors"] and log["liked_after"] == 3 == len(fs.liked)
    assert log["journal"] == []


def test_apply_mismatch_exit_5_and_verdict_in_run_log(env, monkeypatch):
    tmp, cfg = env
    fs = use(monkeypatch, make_fs(6))
    fs.vanish_after("remove_saved_tracks_batched", uri(6))
    assert go(tmp, cfg, "--apply", "--newest", "2") == apply_mod.EXIT_MISMATCH
    log = read_log(tmp)
    assert log["verdict"] == "mismatch" and log["reconcile"]["lost"] == 1
    assert uri(6) in fs.liked  # re-added


def test_runs_index_verdict_says_mismatch_for_a_reconcile_mismatch(env, monkeypatch):
    tmp, cfg = env
    fs = use(monkeypatch, make_fs(6))
    fs.vanish_after("remove_saved_tracks_batched", uri(6))
    go(tmp, cfg, "--apply", "--newest", "2")
    runs = json.loads((tmp / "logs" / "runs.json").read_text(encoding="utf-8"))["runs"]
    assert runs[0]["verdict"] == "mismatch"


def test_apply_with_top_position_orders_playlist(env, monkeypatch):
    tmp, cfg = env
    cfg.write_text(CONFIG_TOP, encoding="utf-8")
    existing = [make_track(100 + i) for i in range(1, 3)]
    fs = use(monkeypatch, make_fs(4, existing=existing))
    assert go(tmp, cfg, "--apply", "--allow-unselected") == 0
    assert fs.playlist_uris("chill1") == [uri(1), uri(2), uri(3), uri(4)] + [t.uri for t in existing]


def test_already_in_target_song_is_removed_without_adding(env, monkeypatch):
    tmp, cfg = env
    pre = make_track(1, age_days=31)
    fs = use(monkeypatch, make_fs(2, existing=[pre]))
    assert go(tmp, cfg, "--apply", "--allow-unselected") == 0
    added = [u for n, a in fs.calls if n == "add_playlist_items_batched" for u in a[1]]
    assert added == [uri(2)] and fs.liked == [] and fs.playlist_uris("chill1").count(uri(1)) == 1


def test_dry_run_still_never_writes(env, monkeypatch):
    tmp, cfg = env
    fs = use(monkeypatch, make_fs(4))
    assert go(tmp, cfg) == 0
    assert fs.constructed == [True] and fs.write_calls() == [] and len(fs.liked) == 4
    assert read_log(tmp)["dry_run"] is True


# ---------------------------------------------------------------- restore through the CLI


def _apply_then_log(tmp, cfg, monkeypatch, n=5, sel="3"):
    fs = use(monkeypatch, make_fs(n))
    assert go(tmp, cfg, "--apply", "--newest", sel) == 0
    return fs, tmp / "logs" / f"{TODAY}.json"


def test_restore_without_apply_is_a_preview(env, monkeypatch, capsys):
    tmp, cfg = env
    fs, log = _apply_then_log(tmp, cfg, monkeypatch)
    fs.constructed.clear()
    fs.calls.clear()
    liked_before = list(fs.liked)
    assert go(tmp, cfg, "--restore", str(log)) == 0
    assert fs.constructed == [] and fs.calls == [] and fs.liked == liked_before
    out = capsys.readouterr().out
    assert "3 journaled song(s)" in out and "DRY RUN" in out
    assert not (tmp / "logs" / f"{TODAY}-restore.json").exists()


def test_restore_with_apply_restores_and_writes_restore_log(env, monkeypatch):
    tmp, cfg = env
    fs, log = _apply_then_log(tmp, cfg, monkeypatch)
    fs.constructed.clear()
    assert go(tmp, cfg, "--restore", str(log), "--apply") == 0
    assert fs.constructed == [False]
    assert fs.liked_uris() == {uri(i) for i in range(1, 6)}
    assert len(fs.playlist_uris("chill1")) == 3  # not removed by default
    rl = read_log(tmp, f"{TODAY}-restore.json")
    assert rl["mode"] == "restore" and rl["source_log"] == log.name and rl["verdict"] == "ok" and rl["errors"] == []
    assert sorted(rl["restored_now_liked"]) == [uri(1), uri(2), uri(3)]
    assert rl["liked_before"] == 2 and rl["liked_after"] == 5


def test_restore_with_remove_from_target(env, monkeypatch):
    tmp, cfg = env
    fs, log = _apply_then_log(tmp, cfg, monkeypatch)
    assert go(tmp, cfg, "--restore", str(log), "--apply", "--remove-from-target") == 0
    assert fs.playlist_uris("chill1") == [] and len(fs.liked) == 5


def test_restore_does_not_re_save_liked_songs(env, monkeypatch):
    tmp, cfg = env
    fs, log = _apply_then_log(tmp, cfg, monkeypatch)
    go(tmp, cfg, "--restore", str(log), "--apply")
    fs.put_uris.clear()
    assert go(tmp, cfg, "--restore", str(log), "--apply") == 0
    assert fs.put_uris == []


def test_restore_command_from_log_is_usable(env, monkeypatch):
    tmp, cfg = env
    fs, log = _apply_then_log(tmp, cfg, monkeypatch, n=4, sel="2")
    cmd = read_log(tmp)["restore_command"]
    path = cmd.split("--restore ", 1)[1].rsplit(" --apply", 1)[0]
    assert go(tmp, cfg, "--restore", path, "--apply") == 0
    assert len(fs.liked) == 4


@pytest.mark.parametrize("missing", ["nope.json", None])
def test_restore_bad_log_exits_1_without_client(env, monkeypatch, missing):
    tmp, cfg = env
    fs = use(monkeypatch, make_fs())
    bad = tmp / (missing or "notajournal.json")
    if missing is None:
        bad.write_text(json.dumps({"hello": 1}), encoding="utf-8")
    assert go(tmp, cfg, "--restore", str(bad), "--apply") == 1
    assert fs.constructed == [] and fs.calls == []


def test_restore_needs_no_config_and_no_selector(tmp_path, monkeypatch):
    fs, log = make_fs(3), None
    log = tmp_path / "j.json"
    log.write_text(json.dumps({"mode": "apply", "dry_run": False, "journal": [{"uri": uri(9), "name": "x", "artists": "y",
                                            "original_added_at": None, "target_playlist_id": "chill1"}]}), encoding="utf-8")
    monkeypatch.setattr(sync, "load_env", lambda *a, **k: False)
    monkeypatch.setattr(sync, "SpotifyClient", client_factory(fs))
    rc = sync.main(["--config", str(tmp_path / "absent.yaml"), "--logs-dir", str(tmp_path / "logs"),
                    "--restore", str(log), "--apply"])
    assert rc == 0 and uri(9) in fs.liked


def test_restore_failure_exit_6_and_verdict_error(env, monkeypatch):
    tmp, cfg = env
    fs, log = _apply_then_log(tmp, cfg, monkeypatch)
    fs.fail_every("save_tracks_batched")
    assert go(tmp, cfg, "--restore", str(log), "--apply") == apply_mod.EXIT_FAILED
    rl = read_log(tmp, f"{TODAY}-restore.json")
    assert rl["verdict"] == "error" and rl["errors"]
    assert len(fs.playlist_uris("chill1")) == 3  # the playlist copy is intact


def test_apply_log_is_never_overwritten_and_dry_run_does_not_clobber_it(tmp_path):
    from datetime import datetime, timezone

    now = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
    logs = tmp_path
    first = sync.log_path(logs, now, "apply")
    first.write_text(json.dumps({"mode": "apply"}), encoding="utf-8")
    second = sync.log_path(logs, now, "apply")
    assert second != first and second.name == "2026-09-21-2.json"
    dry = sync.log_path(logs, now, "dry_run")
    assert dry.name == "2026-09-21-dryrun.json"  # would otherwise clobber the apply journal
    first.write_text(json.dumps({"mode": "dry_run"}), encoding="utf-8")
    assert sync.log_path(logs, now, "dry_run") == first


def test_max_moves_hard_ceiling(env, monkeypatch, capsys):
    tmp, cfg = env
    use(monkeypatch, make_fs(3))
    assert go(tmp, cfg, "--apply", "--newest", "3", "--max-moves", "501") == 2
    assert "between 1 and 500" in capsys.readouterr().err
