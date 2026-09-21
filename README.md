# SpotiSort

A rules-based, fork-and-run tool that treats Spotify **Liked Songs as an inbox**: after a configurable number of days, liked tracks are matched against your rules (artist, genre, release year, explicit flag, etc.) and **moved into playlists you already have** — never creating playlists unless a rule explicitly allows it. Sync runs on a schedule via GitHub Actions; an analyze mode can draft a starting `config.yaml` from your existing playlists for you to review.

**Status: early scaffolding, not yet functional.** Module stubs and workflow skeleton are in place; sync/API logic will land after live API design is finalized.

## Prerequisites

- A **Spotify Premium** account (required to create a Developer app as of Feb 2026)
- A GitHub account (fork this repo and run Actions on your own copy)
- Python 3.12+ (for local dry-runs later)

## Setup

Full setup instructions coming once the core sync logic is implemented.

## License

Open source — fork and run against your own Spotify Developer app and GitHub Actions secrets. No shared backend.
