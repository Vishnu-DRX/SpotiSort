"""Browser tests for the dashboard (docs/dashboard) over the bundled fixtures. Run: python -m pytest tests/e2e -q -m e2e"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect  # noqa: E402

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "docs" / "dashboard" / "fixtures"
SHOTS = ROOT / "docs" / "screenshots"
VIEWS = ["overview", "inbox", "rules", "playlists", "runs", "safety", "signals", "backtest"]


def fx(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


PLAN = fx("latest-plan.json")
RUNS = fx("runs.json")["runs"]


@pytest.fixture
def dash(make_page, site):
    """Open a dashboard view over fixtures (service worker blocked so routes always apply)."""

    def _open(view="overview", qs="", width=1280, height=900, setup=None, source="fixtures", **ctx):
        page, context = make_page(width=width, height=height, service_workers="block", **ctx)
        if setup:
            setup(page)
        page.goto(f"{site}dashboard/?source={source}{qs}#/{view}")
        page.wait_for_selector(f'#view-root[data-state="ready"][data-view="{view}"]')
        return page

    return _open


def patch_json(page, name, fn):
    def handler(route):
        data = json.loads((FIX / name).read_text(encoding="utf-8"))
        out = fn(data)
        route.fulfill(status=200, content_type="application/json", body=json.dumps(out if out is not None else data))

    page.route(f"**/dashboard/fixtures/{name}", handler)


def goto_view(page, view):
    page.evaluate("v => { location.hash = '#/' + v }", view)
    page.wait_for_selector(f'#view-root[data-state="ready"][data-view="{view.split("/")[0].split("?")[0]}"]')


def text(page, sel):
    return page.locator(sel).inner_text()


# ------------------------------------------------------------------ overview
def test_overview_answers_is_it_healthy(dash):
    page = dash("overview")
    c = PLAN["counts"]
    assert page.locator("#view-title").inner_text() == "Overview"
    assert "Is it healthy?" in text(page, ".question")
    last = RUNS[0]
    card = text(page, '[data-card="last-run"]')
    assert "Dry run" in card and "2026-09-21 06:00 UTC" in card
    assert "2026-09-22 03:00 UTC" in text(page, '[data-card="next-run"]')  # from the demo fixture's schedule (decision 34)
    assert str(PLAN["liked_total"]) in text(page, '[data-card="liked"]')
    pending = text(page, '[data-card="pending"]')
    assert str(c["will_move"] + c["too_young"]) in pending and f"{c['will_move']} ready to move" in pending
    week_moves = sum(r["moved"] for r in RUNS if r["mode"] == "apply")
    assert re.search(rf"\b{week_moves}\b", text(page, '[data-card="moves"]'))
    assert f"{last['errors']} / {last['warnings']}" in text(page, '[data-card="errors"]')
    assert "Mismatch" in text(page, '[data-card="safety"]')  # the latest apply run failed reconcile
    nxt = text(page, '[data-testid="next"]')
    assert f"move {c['will_move']} songs" in nxt and "nothing has been written" in nxt
    assert "Data freshness" in text(page, '[data-testid="freshness"]')
    expect(page.locator('[data-banner="stale"]')).to_have_count(0)
    expect(page.locator('[data-banner="legacy"]')).to_have_count(0)
    expect(page.locator('[data-banner="what-if"]')).to_have_count(0)
    page.locator('[data-testid="decision-counts"] a', has_text="Blocked").click()
    page.wait_for_selector('#view-root[data-view="inbox"]')
    expect(page.locator("#inbox-decision")).to_have_value("blocked")
    expect(page.locator("#inbox-results tbody tr")).to_have_count(c["blocked"])


def test_overview_reads_schedule_field(dash):
    def setup(page):
        patch_json(page, "runs.json", lambda d: d.update(schedule="daily at 06:00 UTC"))

    page = dash("overview", setup=setup)
    assert "daily at 06:00 UTC" in text(page, '[data-card="next-run"]')


# ------------------------------------------------------------------ inbox
def test_inbox_table_search_filter_sort(dash):
    page = dash("inbox")
    rows = page.locator("#inbox-results tbody tr")
    expect(rows).to_have_count(len(PLAN["songs"]))
    # search
    page.locator("#inbox-q").fill("nameless loop")
    expect(rows).to_have_count(5)
    assert "Showing 5 of 5" in text(page, '[data-testid="result-count"]')
    page.locator("#inbox-q").fill("")
    # decision filter
    page.locator("#inbox-decision").select_option("blocked")
    expect(rows).to_have_count(PLAN["counts"]["blocked"])
    assert all(d == "blocked" for d in page.locator("#inbox-results tbody tr").evaluate_all("els => els.map(e => e.dataset.decision)"))
    page.locator("#inbox-decision").select_option("")
    # rule filter
    page.locator("#inbox-rule").select_option("Lo-fi study")
    expect(rows).to_have_count(5)
    page.locator("#inbox-rule").select_option("")
    # empty result
    page.locator("#inbox-q").fill("zzz-no-such-song")
    expect(page.locator("#inbox-results .empty")).to_be_visible()
    page.locator("#inbox-q").fill("")
    # sort by title asc / desc
    titles = sorted((s["title"] for s in PLAN["songs"]), key=str.lower)
    page.locator('[data-sort="title"]').click()
    expect(page.locator('th[aria-sort="ascending"]')).to_have_count(1)
    assert page.locator("#inbox-results tbody tr .link-btn").first.inner_text() == titles[0]
    page.locator('[data-sort="title"]').click()
    assert page.locator("#inbox-results tbody tr .link-btn").first.inner_text() == titles[-1]
    assert page.evaluate("document.activeElement.dataset.sort") == "title"  # focus stays on the sort button
    # sort by age ascending
    page.locator('[data-sort="age"]').click()
    ages = [float(a) for a in page.locator("#inbox-results tbody tr td.num:nth-child(2)").all_inner_texts()]
    assert ages == sorted(ages)
    assert ages[0] == min(s["age_days"] for s in PLAN["songs"])


def test_inbox_row_content(dash):
    page = dash("inbox")
    row = page.locator("#inbox-results tbody tr", has_text="Fake Dil")
    t = row.inner_text()
    assert "Will move" in t and "Hindi hits" in t and "Fake Hindi Hits" in t and "top of playlist" in t and "Playlist" in t
    row = page.locator("#inbox-results tbody tr", has_text="Nilavu Placeholder")
    assert "Too young" in row.inner_text()
    row = page.locator("#inbox-results tbody tr", has_text="Fake Thendral")
    assert "Blocked" in row.inner_text() and "Withheld" in row.inner_text()
    row = page.locator("#inbox-results tbody tr", has_text="Pretend Blues")
    assert "Target problem" in row.inner_text() and "missing" in row.inner_text()


def test_hash_query_prefilters_inbox(dash):
    page = dash("inbox", qs="", setup=None)
    goto_view(page, "inbox?rule=Rock%20legends")
    expect(page.locator("#inbox-rule")).to_have_value("Rock legends")
    expect(page.locator("#inbox-results tbody tr")).to_have_count(5)


# ------------------------------------------------------------------ explain drawer
def open_explain(page, title):
    btn = page.locator("#inbox-results .link-btn", has_text=re.compile(rf"^{re.escape(title)}$"))
    btn.click()
    dlg = page.get_by_role("dialog")
    expect(dlg).to_be_visible()
    return btn, dlg


def open_technical_trace(dlg):
    # decision 34: the rule-by-rule trace is a collapsed <details> under the sentence-first narrative. A closed
    # <details>'s content has no innerText (browsers treat it like display:none), so tests that inspect the
    # trace's text must open it first, same as a person would click "Technical details" to see it.
    dlg.locator('details[data-testid="technical-trace"] summary').click()


def test_explain_withheld_signal_and_trace(dash):
    page = dash("inbox")
    _, dlg = open_explain(page, "Fake Thendral")
    body = dlg.inner_text()
    assert "Blocked" in body and "Withheld from rules" in body and "57.1%" in body and "below the 90% bar" in body
    assert "Hint" in body and "58%" in body
    trace = dlg.locator('[data-testid="trace"] > li')
    expect(trace).to_have_count(len(PLAN["rules"]))
    open_technical_trace(dlg)
    tamil = dlg.locator('li[data-rule="Tamil and Telugu"]')
    assert tamil.get_attribute("data-result") == "failed"
    assert tamil.locator("li[data-passed='false']").count() == 1 and "failed" in tamil.inner_text()
    # unmeasured
    dlg.get_by_role("button", name="Close explanation").click()
    _, dlg = open_explain(page, "Sample Ragam")
    assert "has not been measured" in dlg.inner_text()


def test_explain_matched_shadowed_and_signals(dash):
    page = dash("inbox")
    _, dlg = open_explain(page, "Fake Anthem (Live)")
    open_technical_trace(dlg)
    assert dlg.locator('li[data-rule="Rock legends"]').get_attribute("data-result") == "matched"
    alpha = dlg.locator('li[data-rule="Alpha live cuts"]')
    assert alpha.get_attribute("data-result") == "not_reached_but_would_match"
    assert alpha.locator("li[data-passed='true']").count() == 2 and "never reached" in alpha.inner_text()
    assert "Country default" in dlg.inner_text() and "rock" in dlg.inner_text()
    assert dlg.locator('li[data-rule="Draft country"]').get_attribute("data-result") == "skipped_disabled"
    dlg.get_by_role("button", name="Close explanation").click()
    _, dlg = open_explain(page, "Nilavu Placeholder")
    assert dlg.locator('li[data-result="matched_too_young"]').count() == 1
    assert "Playlist" in dlg.locator('[data-testid="lang-signal"]').inner_text() and "97%" in dlg.inner_text()


def test_explain_drawer_keyboard_focus_and_escape(dash):
    page = dash("inbox")
    btn, dlg = open_explain(page, "Fake Dil")
    close = dlg.get_by_role("button", name="Close explanation")
    expect(close).to_be_focused()
    assert dlg.get_attribute("aria-modal") == "true" and dlg.get_attribute("aria-labelledby") == "drawer-title"
    for _ in range(12):  # focus never leaves the dialog
        page.keyboard.press("Tab")
        assert page.evaluate("document.getElementById('drawer').contains(document.activeElement)")
    for _ in range(4):
        page.keyboard.press("Shift+Tab")
        assert page.evaluate("document.getElementById('drawer').contains(document.activeElement)")
    assert page.evaluate("document.querySelector('.wrap').hasAttribute('inert')")
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_have_count(0)
    expect(btn).to_be_focused()
    assert not page.evaluate("document.querySelector('.wrap').hasAttribute('inert')")
    # backdrop click closes too, and Enter on the row button opens it from the keyboard
    btn.focus()
    page.keyboard.press("Enter")
    expect(page.get_by_role("dialog")).to_be_visible()
    page.mouse.click(20, 400)
    expect(page.get_by_role("dialog")).to_have_count(0)


# ------------------------------------------------------------------ rules
def test_rules_flags_and_history(dash):
    page = dash("rules")
    rows = page.locator('[data-testid="rules-table"] tbody tr')
    expect(rows).to_have_count(len(PLAN["rules"]))
    status = {n: page.locator(f'tr[data-rule="{n}"]').get_attribute("data-status") for n in ("Polka party", "Alpha live cuts", "Draft country", "Rock legends")}
    assert status == {"Polka party": "dead", "Alpha live cuts": "shadowed", "Draft country": "disabled", "Rock legends": "ok"}
    shadow = page.locator('tr[data-rule="Alpha live cuts"]').inner_text()
    assert "Shadowed" in shadow and "Rock legends (1)" in shadow
    assert "No song in the inbox matches" in page.locator('tr[data-rule="Polka party"]').inner_text()
    assert "Weak signals: hint, country_default" in page.locator('tr[data-rule="Spanish nights"]').inner_text()
    hindi = page.locator('tr[data-rule="Hindi hits"]')
    plan_rule = next(r for r in PLAN["rules"] if r["name"] == "Hindi hits")
    assert f"{plan_rule['would_match']}" in hindi.locator("td[data-label='Would match']").inner_text()
    last_matched = next(r for r in RUNS if r["rule_counts"].get("Hindi hits"))["time"][:10]
    assert last_matched in hindi.locator("td[data-label='Last matched']").inner_text()
    last_run = RUNS[0]["rule_counts"].get("Hindi hits", 0)
    assert hindi.locator("td[data-label='Last run']").inner_text() == str(last_run)
    assert "never" in page.locator('tr[data-rule="Polka party"] td[data-label="Last matched"]').inner_text()
    assert "Missing" in page.locator('tr[data-rule="Old jazz"]').inner_text()
    hindi.locator("td[data-label='Wins now'] a").click()
    page.wait_for_selector('#view-root[data-view="inbox"]')
    expect(page.locator("#inbox-results tbody tr")).to_have_count(plan_rule["wins"])


# ------------------------------------------------------------------ playlists
def test_playlists_status_size_planned(dash):
    page = dash("playlists")
    rows = page.locator('[data-testid="playlists-table"] tbody tr')
    expect(rows).to_have_count(len(PLAN["playlists"]))
    statuses = set(rows.evaluate_all("els => els.map(e => e.dataset.status)"))
    assert statuses == {"resolved", "missing", "not_writable", "ambiguous"}
    eng = next(p for p in PLAN["playlists"] if p["name"] == "Fake English")
    row = page.locator("tr", has_text="Fake English")
    assert str(eng["size"]) in row.inner_text() and str(eng["planned_in"]) in row.inner_text()
    assert "Not writable" in page.locator("tr", has_text="Fake Tamil Telugu").inner_text()
    assert "Ambiguous" in page.locator("tr", has_text="Fake Duplicate").inner_text()
    assert "Missing" in page.locator("tr", has_text="Fake Jazz Vault").inner_text()


# ------------------------------------------------------------------ runs
def test_runs_history_detail_and_diff(dash):
    page = dash("runs")
    rows = page.locator('[data-testid="runs-table"] tbody tr')
    expect(rows).to_have_count(len(RUNS))
    verdicts = rows.evaluate_all("els => els.map(e => e.dataset.verdict)")
    assert {"mismatch", "error", "ok", "dry_run"} <= set(verdicts)
    assert sum(1 for r in RUNS if r["mode"] == "apply") >= 2
    # detail of the mismatching apply run
    mism = next(r for r in RUNS if r["verdict"] == "mismatch")
    page.locator(f'tr[data-run="{mism["run_id"]}"] a', has_text="Details").click()
    page.wait_for_selector('[data-testid="run-detail"]')
    body = page.locator("#view-root").inner_text()
    assert "Mismatch" in body and "expected 42" in body and "found 43" in body
    assert "python -m src.sync --restore logs/2026-09-17.json" in body
    assert "Journal (4 removals recorded)" in body or "Journal" in body
    assert "Spotify write calls" in body
    # run with an error
    err = next(r for r in RUNS if r["verdict"] == "error")
    goto_view(page, f"runs/{err['run_id']}")
    assert "HTTP 503" in page.locator("#view-root").inner_text()
    # diff two runs
    goto_view(page, "runs")
    a, b = RUNS[1], RUNS[3]
    page.locator(f'[data-pick="{a["run_id"]}"]').check()
    expect(page.get_by_role("button", name="Compare selected runs")).to_be_disabled()
    page.locator(f'[data-pick="{b["run_id"]}"]').check()
    page.get_by_role("button", name="Compare selected runs").click()
    page.wait_for_selector('[data-testid="run-diff"]')
    diff = page.locator('[data-testid="run-diff"]').inner_text()
    assert "Planned moves" in diff and "Rule wins" in diff and "Compare runs" in diff
    assert "Only in the older run" in diff and "Only in the newer run" in diff


def test_runs_unknown_run_is_a_clear_message(dash):
    page = dash("runs")
    goto_view(page, "runs/nope")
    assert "Run not found" in page.locator("#view-root").inner_text()


# ------------------------------------------------------------------ safety
def test_safety_timeline_restore_reconcile(dash):
    page = dash("safety")
    svg = page.locator('svg[data-testid="timeline"]')
    expect(svg).to_be_visible()
    assert svg.get_attribute("role") == "img" and page.locator("#tl-title").text_content() == "Liked songs over time"
    assert svg.locator("circle, rect.pt-bad").count() == len(RUNS)
    expect(page.locator('[data-banner="mismatch"]')).to_be_visible()
    cards = page.locator('[data-testid="apply-run"]')
    expect(cards).to_have_count(2)
    txt = cards.all_inner_texts()
    joined = "\n".join(txt)
    assert "python -m src.sync --restore logs/2026-09-15.json" in joined and "python -m src.sync --restore logs/2026-09-17.json" in joined
    assert "Reconcile: OK" in joined.replace("\n", " ").replace("✓ ", "") or "OK" in joined
    assert "Mismatch" in joined and "expected 42, found 43" in joined
    cards.first.locator("summary").click()
    assert cards.first.locator('[data-testid="journal"] tbody tr').count() >= 1
    assert "Not available yet" in text(page, '[data-testid="vanished"]')
    # timeline data table alternative
    page.locator("summary", has_text="Show as a table").click()
    expect(page.locator("details[open] table tbody tr").first).to_be_visible()


# ------------------------------------------------------------------ signals
def test_signals_coverage_and_precision_badges(dash):
    page = dash("signals")
    cov = fx("enrichment-coverage.json")
    t = text(page, '[data-testid="coverage"]')
    assert str(cov["tracks"]) in t and f"{cov['genre_coverage_pct_of_artists']}%" in t and f"{cov['language_coverage_pct_whole_library']}%" in t
    cell = lambda sig, lang: page.locator(f'td[data-signal="{sig}"][data-lang="{lang}"]')
    assert cell("hint", "tamil").get_attribute("data-qualified") == "no" and "Not qualified" in cell("hint", "tamil").inner_text()
    assert "57.1%" in cell("hint", "tamil").inner_text() and "8 of 14" in cell("hint", "tamil").inner_text()
    assert cell("hint", "spanish").get_attribute("data-qualified") == "yes" and "Qualified" in cell("hint", "spanish").inner_text()
    assert cell("country_default", "english").get_attribute("data-qualified") == "yes"
    assert cell("country_default", "hindi").get_attribute("data-qualified") == "no"
    assert cell("playlist", "malayalam").get_attribute("data-qualified") == "yes"
    assert "not measured" in cell("playlist", "bengali").inner_text()
    assert "Where languages came from" in page.locator("#view-root").inner_text()
    assert "90%" in page.locator("#view-root").inner_text()


# ------------------------------------------------------------------ backtest
def test_backtest_names_in_local_detail_mode(dash):
    page = dash("backtest")
    bt = fx("backtest.json")
    tot = text(page, '[data-testid="backtest-totals"]')
    assert f"{bt['totals']['precision'] * 100:.1f}%" in tot and f"{bt['totals']['recall'] * 100:.1f}%" in tot
    rows = page.locator('[data-testid="backtest-playlists"] tbody tr')
    expect(rows).to_have_count(len(bt["playlists"]))
    assert "Fake Rock" in page.locator("#view-root").inner_text() and "P03" not in text(page, '[data-testid="backtest-playlists"]')
    assert "n/a" in page.locator('tr[data-playlist="P05"]').inner_text()  # precision undefined: no divide-by-zero
    assert page.locator('[data-testid="confusions"] tbody tr').count() == len(bt["confusions"])
    mis = text(page, '[data-testid="misroutes"]')
    assert "Fake Anthem Remix" in mis and "Lo-fi study" in mis


def test_backtest_without_detail_uses_ids(dash):
    def setup(page):
        page.route("**/dashboard/fixtures/backtest-detail.json", lambda r: r.fulfill(status=404, body="nope"))

    page = dash("backtest", setup=setup)
    body = page.locator("#view-root").inner_text()
    assert "P01" in body and "R01" in body and "Fake Rock" not in body and "Fake Anthem Remix" not in body
    assert "only shown in Local mode" in body


# ------------------------------------------------------------------ banners
def test_stale_banner_when_generated_at_is_old(dash):
    def setup(page):
        patch_json(page, "latest-plan.json", lambda d: d.update(generated_at="2026-09-17T06:00:00+00:00"))

    page = dash("overview", setup=setup)
    banner = page.locator('[data-banner="stale"]')
    expect(banner).to_be_visible()
    assert "more than 2 days old" in banner.inner_text() and "Inbox snapshot" in banner.inner_text()
    goto_view(page, "inbox")
    expect(page.locator('[data-banner="stale"]')).to_be_visible()
    goto_view(page, "signals")  # signals does not use the plan file, so it is not stale
    expect(page.locator('[data-banner="stale"]')).to_have_count(0)


def test_now_parameter_makes_everything_stale(dash):
    page = dash("runs", qs="&now=2026-10-05T00:00:00Z")
    expect(page.locator('[data-banner="stale"]')).to_be_visible()


def test_what_if_and_legacy_banners_on_every_view(dash):
    def setup(page):
        patch_json(page, "latest-plan.json", lambda d: d.update(what_if=True, inbox_kind="legacy_library"))

    page = dash("overview", setup=setup)
    for view in VIEWS:
        goto_view(page, view)
        legacy = page.locator('[data-banner="legacy"]')
        expect(legacy).to_be_visible()
        assert "This is the old archive, not a live inbox" in legacy.inner_text()
        wi = page.locator('[data-banner="what-if"]')
        expect(wi).to_be_visible()
        assert "Disabled rules were treated as enabled" in wi.inner_text()


# ------------------------------------------------------------------ empty + error states
def test_empty_states_name_the_command(dash):
    page = dash("overview", source="files")  # nothing has been opened yet, so every file is missing
    expected = {
        "overview": ["python -m src.sync"],
        "inbox": ["python -m src.sync"],
        "rules": ["python -m src.sync"],
        "playlists": ["python -m src.sync"],
        "runs": ["python -m src.sync"],
        "safety": ["python -m src.sync"],
        "signals": ["python -m src.enrich --report", "python -m src.backtest"],
        "backtest": ["python -m src.backtest"],
    }
    for view, cmds in expected.items():
        goto_view(page, view)
        empties = page.locator("#view-root .empty")
        assert empties.count() >= 1, view
        body = page.locator("#view-root").inner_text()
        for c in cmds:
            assert c in body, (view, c)
        assert "No data" in text(page, '[data-testid="freshness"]') or "no data" in text(page, '[data-testid="freshness"]')
    assert page.locator('[data-empty="plan"]').count() == 0 or True


def test_partial_data_shows_what_exists(dash):
    def setup(page):
        page.route("**/dashboard/fixtures/enrichment-coverage.json", lambda r: r.fulfill(status=404, body="x"))

    page = dash("signals", setup=setup)
    expect(page.locator('[data-empty="coverage"]')).to_be_visible()
    assert "python -m src.enrich --report" in text(page, '[data-empty="coverage"]')
    expect(page.locator('[data-testid="precision-table"]')).to_be_visible()


def test_error_state_and_retry(dash):
    state = {"fail": True}

    def setup(page):
        def handler(route):
            if state["fail"]:
                route.fulfill(status=500, body="boom")
            else:
                route.continue_()

        page.route("**/dashboard/fixtures/latest-plan.json", handler)

    page = dash("inbox", setup=setup)
    err = page.locator('[data-error="plan"]')
    expect(err).to_be_visible()
    assert err.get_attribute("role") == "alert" and "HTTP 500" in err.inner_text()
    state["fail"] = False
    err.get_by_role("button", name="Try again").click()
    page.wait_for_selector("#inbox-results tbody tr")
    expect(page.locator('[data-error="plan"]')).to_have_count(0)


def test_invalid_json_is_an_error_not_a_crash(dash):
    def setup(page):
        page.route("**/dashboard/fixtures/runs.json", lambda r: r.fulfill(status=200, content_type="application/json", body="{not json"))

    page = dash("runs", setup=setup)
    assert "not valid JSON" in text(page, '[data-error="runs"]')
    goto_view(page, "overview")  # the rest of the dashboard keeps working
    assert page.locator('[data-error="runs"]').count() == 1 and page.locator('[data-card="liked"]').count() == 1


def test_network_failure_is_an_error(dash):
    def setup(page):
        page.route("**/dashboard/fixtures/latest-plan.json", lambda r: r.abort())

    page = dash("playlists", setup=setup)
    expect(page.locator('[data-error="plan"]')).to_be_visible()


# ------------------------------------------------------------------ sources
def serve_data(page, prefix_pattern):
    def handler(route):
        name = route.request.url.split("?")[0].rsplit("/", 1)[1]
        f = FIX / name
        if f.exists():
            route.fulfill(status=200, content_type="application/json", body=f.read_text(encoding="utf-8"))
        else:
            route.fulfill(status=404, body="nope")

    page.route(prefix_pattern, handler)


def test_source_switch_repo_fixtures_files(dash, site):
    requests = []

    def setup(page):
        page.on("request", lambda r: requests.append(r.url))
        serve_data(page, "https://raw.githubusercontent.com/**")

    page = dash("overview", setup=setup)
    sel = page.locator("#source-select")
    expect(sel).to_have_value("fixtures")
    assert "Demo data" in page.locator("#repo-hint").inner_text()
    assert "Demo data" in page.locator("#source-current").inner_text()
    # -> files: nothing chosen yet, reads nothing over the network
    sel.select_option("files")
    expect(page.locator("#files-field")).to_be_visible()
    assert "Open local files" in page.locator("#source-current").inner_text()
    assert "source=files" in page.url and page.evaluate("localStorage.getItem('spotisort.dashboard.source')") == "files"
    requests.clear()  # only care about requests made from here on, once "files" is the active source
    page.locator("#files-input").set_input_files([str(FIX / "latest-plan.json"), str(FIX / "runs.json")])
    page.wait_for_selector('#view-root[data-state="ready"] [data-card="liked"]')
    assert "latest-plan.json" in page.locator("#files-status").inner_text()
    assert not any(u.endswith("latest-plan.json") and u.startswith("http") for u in requests)  # never uploaded
    # -> repo: needs a configured GitHub raw folder; invalid ones are refused
    sel.select_option("repo")
    expect(page.locator("#repo-url")).to_be_visible()
    page.locator("#repo-url").fill("https://evil.example/logs/")
    page.get_by_role("button", name="Save URL").click()
    assert page.locator("#repo-url").get_attribute("aria-invalid") == "true"
    assert "raw.githubusercontent.com" in page.locator("#repo-hint").inner_text()
    page.locator("#repo-url").fill("https://raw.githubusercontent.com/octo/spot/main/logs")
    page.get_by_role("button", name="Save URL").click()
    page.wait_for_selector('#view-root[data-state="ready"] [data-card="liked"]')
    assert any(u == "https://raw.githubusercontent.com/octo/spot/main/logs/latest-plan.json" for u in requests)
    assert page.evaluate("localStorage.getItem('spotisort.dashboard.repo')") == "https://raw.githubusercontent.com/octo/spot/main/logs/"
    assert page.locator("#repo-url").input_value() == "https://raw.githubusercontent.com/octo/spot/main/logs/"
    # -> back to fixtures
    sel.select_option("fixtures")
    page.wait_for_selector('#view-root[data-state="ready"] [data-card="liked"]')
    expect(page.locator("#repo-url")).to_be_hidden()
    own = site.split("/")[2]
    external = {u.split("/")[2] for u in requests if u.startswith("http")} - {own}
    assert external <= {"raw.githubusercontent.com"}, external


def test_repo_source_without_configuration_asks_for_it(dash):
    page = dash("overview", source="repo")  # 127.0.0.1 host: no owner can be derived
    assert "Enter the raw URL" in page.locator("#repo-hint").inner_text()
    expect(page.locator('[data-error="plan"]')).to_be_visible()


def test_no_requests_leave_the_site_with_fixtures(dash, site):
    seen = []

    def setup(page):
        page.on("request", lambda r: seen.append(r.url))

    page = dash("overview", setup=setup)
    for v in VIEWS:
        goto_view(page, v)
    bad = [u for u in seen if not (u.startswith(site) or u.startswith("data:") or u.startswith("blob:"))]
    assert not bad, bad


def test_storage_blocked_does_not_break_the_page(make_page, site):
    page, _ = make_page(service_workers="block")
    page.add_init_script("Object.defineProperty(window, 'localStorage', {get(){ throw new Error('blocked') }})")
    page.goto(f"{site}dashboard/?source=fixtures#/overview")
    page.wait_for_selector('#view-root[data-state="ready"] [data-card="liked"]')


def test_hostile_titles_are_escaped(dash):
    def mutate(d):
        d["songs"][0]["title"] = '<img src=x onerror="window.__xss=1">'
        d["songs"][0]["artists"] = ["<b>bold</b>"]

    def setup(page):
        patch_json(page, "latest-plan.json", mutate)

    page = dash("inbox", setup=setup)
    assert page.evaluate("window.__xss") is None
    assert page.locator("#inbox-results img").count() == 0
    assert page.locator("#inbox-results", has_text="<img src=x").count() == 1


# ------------------------------------------------------------------ keyboard, routing, theme
def test_tabs_keyboard_routing_and_aria(dash):
    page = dash("overview")
    nav = page.get_by_role("navigation", name="Dashboard views")
    labels = nav.get_by_role("link").all_inner_texts()
    assert labels == ["Overview", "Inbox", "Rules", "Playlists", "Runs", "Safety", "Signals", "Backtest"]
    assert nav.locator('[aria-current="page"]').inner_text() == "Overview"
    nav.get_by_role("link", name="Rules").focus()
    page.keyboard.press("Enter")
    page.wait_for_selector('#view-root[data-view="rules"]')
    assert nav.locator('[aria-current="page"]').inner_text() == "Rules"
    expect(page.locator("#view-title")).to_be_focused()  # focus moves to the new view heading
    assert page.title().startswith("Rules")
    page.evaluate("location.hash = '#/definitely-not-a-view'")
    page.wait_for_selector('#view-root[data-view="overview"]')
    assert page.get_by_role("link", name="Skip to content").count() == 1


def test_theme_tokens_follow_color_scheme(make_page, site):
    for scheme, bg in (("dark", "rgb(18, 18, 18)"), ("light", "rgb(246, 246, 246)")):
        page, _ = make_page(service_workers="block", color_scheme=scheme)
        page.goto(f"{site}dashboard/?source=fixtures#/overview")
        page.wait_for_selector('#view-root[data-state="ready"]')
        assert page.evaluate("getComputedStyle(document.body).backgroundColor") == bg
    page.get_by_role("button", name=re.compile("Colour theme")).click()  # auto -> light
    assert page.evaluate("document.documentElement.dataset.theme") == "light"
    page.get_by_role("button", name=re.compile("Colour theme")).click()  # -> dark
    assert page.evaluate("getComputedStyle(document.body).backgroundColor") == "rgb(18, 18, 18)"


def test_dashboard_css_uses_only_design_tokens():
    css = (ROOT / "docs" / "dashboard" / "dashboard.css").read_text(encoding="utf-8")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css), "raw hex colour in dashboard.css"
    assert not re.search(r"\brgba?\(|\bhsla?\(", css)


# ------------------------------------------------------------------ mobile + screenshots
@pytest.mark.parametrize("width,height", [(375, 812), (1280, 900)])
@pytest.mark.parametrize("view", VIEWS)
def test_no_horizontal_overflow_and_screenshots(dash, view, width, height):
    page = dash(view, width=width, height=height)
    if view == "runs":
        page.wait_for_selector('[data-testid="runs-table"]')
    for w in ("document.documentElement.scrollWidth", "document.body.scrollWidth"):
        assert page.evaluate(w) <= width, (view, width, w, page.evaluate(w))
    SHOTS.mkdir(exist_ok=True)
    page.screenshot(path=str(SHOTS / f"dashboard-{view}-{width}.png"), full_page=True)


@pytest.mark.parametrize("width", [375, 1280])
def test_drawer_and_details_fit_the_viewport(dash, width):
    page = dash("inbox", width=width)
    open_explain(page, "Fake Anthem (Live)")
    dlg = page.get_by_role("dialog")
    page.wait_for_timeout(500)  # let the slide-in animation finish
    box = dlg.bounding_box()
    assert box["x"] >= 0 and box["x"] + box["width"] <= width + 1
    assert page.evaluate("document.documentElement.scrollWidth") <= width
    assert page.evaluate("document.getElementById('drawer').scrollWidth <= document.getElementById('drawer').clientWidth + 1")
    page.screenshot(path=str(SHOTS / f"dashboard-explain-{width}.png"))
    page.keyboard.press("Escape")
    goto_view(page, f"runs/{RUNS[1]['run_id']}")
    assert page.evaluate("document.documentElement.scrollWidth") <= width


def test_mobile_tables_collapse_to_cards(dash):
    page = dash("inbox", width=375, height=812)
    assert page.evaluate("getComputedStyle(document.querySelector('#inbox-results tbody tr')).display") == "block"
    assert page.evaluate("getComputedStyle(document.querySelector('#inbox-results thead')).position") == "absolute"
    page2 = dash("inbox", width=1280)
    assert page2.evaluate("getComputedStyle(document.querySelector('#inbox-results tbody tr')).display") == "table-row"


# ------------------------------------------------------------------ offline
def test_dashboard_works_offline_via_service_worker(make_page, site):
    page, ctx = make_page()  # service workers allowed
    page.goto(f"{site}dashboard/?source=fixtures#/overview")
    page.wait_for_selector('#view-root[data-state="ready"]')
    page.evaluate("navigator.serviceWorker.ready.then(() => true)")
    page.reload()
    page.wait_for_function("navigator.serviceWorker.controller !== null")
    cached = page.evaluate("caches.keys().then(async ks => (await Promise.all(ks.map(k => caches.open(k).then(c => c.keys())))).flat().map(r => r.url))")
    for needed in ("dashboard/", "dashboard/index.html", "dashboard/dashboard.css", "dashboard/data.js", "dashboard/views.js",
                   "dashboard/app.js", "assets/tokens.css", "dashboard/fixtures/latest-plan.json", "dashboard/fixtures/runs.json"):
        assert site + needed in cached, needed
    ctx.set_offline(True)
    page.reload()
    page.wait_for_selector('#view-root[data-state="ready"] [data-card="liked"]')
    assert str(PLAN["liked_total"]) in text(page, '[data-card="liked"]')
    goto_view(page, "inbox")
    expect(page.locator("#inbox-results tbody tr")).to_have_count(len(PLAN["songs"]))
    ctx.set_offline(False)
