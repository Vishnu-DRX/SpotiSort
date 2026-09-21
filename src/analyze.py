"""Onboarding / analyze-mode entrypoint (scaffolding only)."""

from __future__ import annotations

import argparse
import sys


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect existing playlists and draft a starting config.yaml "
            "with inferred rules (never applies changes)."
        )
    )
    parser.add_argument(
        "--output",
        default="config.draft.yaml",
        help="Where to write the draft config (default: config.draft.yaml).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # TODO: auth, fetch playlists + items, genre resolve, emit draft YAML.
    # See IMPLEMENTATION_PLAN.md §5.4 — do not implement until API design is finalized.
    print(
        f"analyze.py scaffolding only — would write draft to {args.output}. "
        "Real analyze logic not implemented yet."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
