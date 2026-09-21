"""Daily sync entrypoint (scaffolding only — no API / rules logic yet)."""

from __future__ import annotations

import argparse
import sys


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Sort aged Liked Songs into existing playlists by rules. "
            "Dry-run is the default; pass --apply to perform writes."
        )
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Preview intended moves without calling write endpoints (default).",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Perform adds/removes for real. Overrides --dry-run.",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to rules config (default: config.yaml).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    dry_run = not args.apply

    # TODO: load config, auth, fetch liked tracks, evaluate rules, move/remove.
    # See IMPLEMENTATION_PLAN.md §5.2 — do not implement until API design is finalized.
    mode = "dry-run" if dry_run else "apply"
    print(
        f"sync.py scaffolding only — mode={mode}, config={args.config}. "
        "Real sync logic not implemented yet."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
