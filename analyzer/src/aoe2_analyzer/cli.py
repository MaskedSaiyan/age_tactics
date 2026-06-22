"""Command-line interface for aoe2_analyzer.

Usage:
    python -m aoe2_analyzer analyze path/to/replay.aoe2record
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from . import __version__
from .parser import parse_replay
from .report import print_summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aoe2_analyzer",
        description="Exploratory analyzer for AoE2 DE replay files (.aoe2record).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser(
        "analyze",
        help="Parse a replay and print a summary (currently MOCK output).",
    )
    analyze.add_argument("replay", help="Path to a .aoe2record file.")

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "analyze":
        summary = parse_replay(args.replay)
        print_summary(summary)
        if summary.is_mock:
            print(
                "\nReminder: this is MOCK data. Real .aoe2record parsing is not "
                "implemented yet — see analyzer/src/aoe2_analyzer/parser.py.",
                file=sys.stderr,
            )
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
