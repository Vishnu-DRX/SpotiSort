"""Static checks on the GitHub Actions workflows (safety properties, not GitHub's own parser)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WF = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def load(name: str) -> dict:
    data = yaml.safe_load((WF / name).read_text(encoding="utf-8"))
    # PyYAML reads the bare key `on` as boolean True
    if True in data and "on" not in data:
        data["on"] = data.pop(True)
    return data


@pytest.fixture(scope="module")
def sync() -> dict:
    return load("sync.yml")


def test_all_workflows_parse_and_have_jobs():
    for path in WF.glob("*.yml"):
        data = load(path.name)
        assert data.get("name") and data.get("jobs"), path.name


def test_sync_is_manual_only_until_schedule_is_confirmed(sync):
    assert set(sync["on"]) == {"workflow_dispatch"}


def test_sync_dry_run_input_defaults_to_true(sync):
    inp = sync["on"]["workflow_dispatch"]["inputs"]["dry_run"]
    assert inp["type"] == "boolean" and inp["default"] is True


def test_sync_has_concurrency_group_without_cancelling(sync):
    assert sync["concurrency"]["group"] and sync["concurrency"]["cancel-in-progress"] is False


def test_sync_uses_only_two_spotify_secrets():
    text = (WF / "sync.yml").read_text(encoding="utf-8")
    assert "secrets.SPOTIFY_CLIENT_ID" in text and "secrets.SPOTIFY_REFRESH_TOKEN" in text
    assert "CLIENT_SECRET" not in text
    import re

    assert set(re.findall(r"secrets\.([A-Z_]+)", text)) == {"SPOTIFY_CLIENT_ID", "SPOTIFY_REFRESH_TOKEN"}


def test_sync_never_interpolates_inputs_into_shell(sync):
    """Inputs reach the shell only through env vars (no ${{ inputs.* }} inside `run:` blocks)."""
    for step in sync["jobs"]["sync"]["steps"]:
        assert "${{" not in step.get("run", ""), step.get("name")


def test_sync_live_run_requires_newest_selector_and_cap():
    run = next(s["run"] for s in load("sync.yml")["jobs"]["sync"]["steps"] if s.get("name") == "Sync")
    assert "--apply" in run and "--newest" in run and "--max-moves" in run
    assert "--allow-unselected" not in run  # no unselected live run from the manual dispatch (decision 12)
    assert "exit 2" in run  # a live run without 'newest' is refused before python starts


def test_sync_has_no_unselected_input(sync):
    assert "unselected" not in sync["on"]["workflow_dispatch"]["inputs"]


def test_sync_caches_enrichment_and_does_not_commit_it(sync):
    steps = sync["jobs"]["sync"]["steps"]
    cache = next(s for s in steps if str(s.get("uses", "")).startswith("actions/cache"))
    assert cache["with"]["path"] == ".cache/enrichment.json"
    assert "github.run_id" in cache["with"]["key"] and cache["with"]["restore-keys"].strip().startswith("enrichment-v1-")
    commit = next(s["run"] for s in steps if s.get("name") == "Commit run logs")
    assert ".cache" not in commit and "git add -f" in commit and "[skip ci]" in commit


def test_sync_permissions_and_bot_identity(sync):
    assert sync["permissions"] == {"contents": "write"}
    commit = next(s["run"] for s in sync["jobs"]["sync"]["steps"] if s.get("name") == "Commit run logs")
    assert "spotisort-bot" in commit


def test_tests_workflow_is_read_only():
    assert load("tests.yml")["permissions"] == {"contents": "read"}
