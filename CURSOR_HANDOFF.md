# Cursor Handoff — Phase 1: Repo & Project Scaffolding

## Scope of this phase (read carefully — do not exceed it)

Set up the GitHub repo and basic project skeleton only. **Do not implement
the real sync logic, rules engine internals, or Spotify API calls yet** —
some of those details are still being confirmed against live API output
and will be finalized in a follow-up pass. Stub things out clearly instead
of guessing.

The full target design is in `IMPLEMENTATION_PLAN.md` (included alongside
this file) — treat it as the reference for *where things go and what they'll
eventually do*, not as something to fully build right now.

## Tasks

### 1. Create the GitHub repo
- Public repo, name suggestion: `spotify-liked-sorter` (or ask the user if
  they want a different name).
- Use `gh repo create` if the GitHub CLI is authenticated locally, otherwise
  create via the GitHub web UI and clone it.
- Default branch `main`.

### 2. Scaffold the directory structure
Create this exact structure (per §4 of `IMPLEMENTATION_PLAN.md`), with
placeholder/stub content only:

```
spotify-liked-sorter/
├── README.md
├── requirements.txt
├── config.example.yaml
├── .gitignore
├── src/
│   ├── __init__.py
│   ├── spotify_client.py      # stub: function signatures + TODO comments only
│   ├── rules_engine.py        # stub: function signatures + TODO comments only
│   ├── genre_cache.py         # stub: function signatures + TODO comments only
│   ├── sync.py                # stub: CLI arg parsing (--dry-run/--apply) only
│   └── analyze.py             # stub: CLI entrypoint only
├── .cache/
│   └── .gitkeep
├── logs/
│   └── .gitkeep
├── .github/
│   └── workflows/
│       └── sync.yml           # skeleton workflow — see note below
└── docs/
    ├── index.html             # minimal placeholder page, "Coming soon"
    ├── app.js
    └── style.css
```

### 3. `requirements.txt`
```
requests>=2.31
PyYAML>=6.0
```
(No `python-dotenv` needed — GitHub Actions Secrets are injected as env
vars directly; local dev can `export` manually for now.)

### 4. `.gitignore`
Standard Python `.gitignore`, plus explicitly:
```
explore_output.json
*.env
.env
```
(These may contain real account data / secrets if generated locally — never
commit them.)

### 5. `config.example.yaml`
Copy the schema from §6 of `IMPLEMENTATION_PLAN.md` verbatim as the example
— it's already final. Do not create a real `config.yaml` yet (that's user
data, not scaffolding).

### 6. `.github/workflows/sync.yml` — skeleton only
Structure it with the right triggers and steps, but the actual "run sync"
step should currently just be a placeholder:

```yaml
name: Daily Sync

on:
  schedule:
    - cron: "0 3 * * *"   # TODO: confirm final time with user
  workflow_dispatch: {}

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      - name: Run sync
        env:
          SPOTIFY_CLIENT_ID: ${{ secrets.SPOTIFY_CLIENT_ID }}
          SPOTIFY_CLIENT_SECRET: ${{ secrets.SPOTIFY_CLIENT_SECRET }}
          SPOTIFY_REFRESH_TOKEN: ${{ secrets.SPOTIFY_REFRESH_TOKEN }}
        run: echo "TODO: python src/sync.py --apply (pending finalized API design)"
      # TODO (later phase): commit logs/ and .cache/ changes back to the repo
```
Do not wire up the real `python src/sync.py --apply` call or the
commit-back step yet — leave the TODOs as-is.

### 7. `README.md`
Include:
- One-paragraph project description (liked-songs auto-sorter, see
  `IMPLEMENTATION_PLAN.md` §1)
- Prerequisites: Spotify **Premium** account required to create a Developer
  app (confirmed current requirement)
- A "Status: early scaffolding, not yet functional" note so it's clear this
  isn't usable yet
- Placeholder setup section: "Full setup instructions coming once the core
  sync logic is implemented"

### 8. `docs/index.html`
Minimal static page — just confirms Pages is wired up correctly. Something
like "Spotify Liked Sorter — config UI coming soon." No need for real UI
yet.

### 9. Enable GitHub Pages
In repo Settings → Pages, set source to the `docs/` folder on `main`.
Confirm the resulting `https://<username>.github.io/<repo>` URL loads the
placeholder page.

### 10. Do NOT add secrets yet
Hold off on adding `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` /
`SPOTIFY_REFRESH_TOKEN` as repo secrets until the core logic is ready to
actually use them — no point exposing them to a workflow that doesn't do
anything yet.

### 11. Commit and push
One initial commit is fine — `Initial project scaffolding`. Push to `main`.

## What happens after this phase

The user will run `explore_api.py` (included alongside this handoff)
against their real Spotify account, bring the output back for a design
review, and then return with a finalized/confirmed version of
`IMPLEMENTATION_PLAN.md` for you to actually implement `spotify_client.py`,
`rules_engine.py`, `sync.py`, and the rest for real. Don't build ahead of
that — the API research so far is docs-based; the explore output is what
confirms it against a live account before real code depends on it.
