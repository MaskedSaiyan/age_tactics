"""Command-line interface for aoe2_analyzer.

Usage:
    python -m aoe2_analyzer analyze path/to/replay.aoe2record
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from . import __version__
from .parser import ReplayParseError, parse_replay
from .report import print_build_orders, print_summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aoe2_analyzer",
        description="Analyzer for AoE2 DE replay files (.aoe2record).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser(
        "analyze",
        help="Parse a replay and print an age-progression summary.",
    )
    analyze.add_argument("replay", help="Path to a .aoe2record file.")
    analyze.add_argument(
        "-b",
        "--build-order",
        action="store_true",
        help="Also print the full numbered build-order timeline.",
    )

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "analyze":
        try:
            summary = parse_replay(args.replay)
        except ReplayParseError as exc:
            print(f"error: could not parse replay: {exc}", file=sys.stderr)
            return 1
        print_summary(summary)
        if args.build_order:
            print_build_orders(summary)
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
