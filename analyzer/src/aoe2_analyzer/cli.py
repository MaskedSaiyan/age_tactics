"""Command-line interface for aoe2_analyzer.

Usage:
    python -m aoe2_analyzer analyze   path/to/replay.aoe2record [--build-order]
    python -m aoe2_analyzer villagers path/to/replay.aoe2record [--player N]
    python -m aoe2_analyzer unit      path/to/replay.aoe2record <object_id>
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from . import __version__
from .parser import ReplayParseError, parse_replay
from .report import (
    format_assignments,
    format_unit_log,
    format_villager_list,
    print_report,
    print_summary,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aoe2_analyzer",
        description="Analyzer for AoE2 DE replay files (.aoe2record).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser(
        "analyze",
        help="Full sectioned report: overview + build order + assignments.",
    )
    analyze.add_argument("replay", help="Path to a .aoe2record file.")
    analyze.add_argument(
        "-s",
        "--summary-only",
        action="store_true",
        help="Print only the overview section (no build order / assignments).",
    )

    villagers = subparsers.add_parser(
        "villagers",
        help="List villager-like units (builders) and their object ids.",
    )
    villagers.add_argument("replay", help="Path to a .aoe2record file.")
    villagers.add_argument(
        "-p", "--player", type=int, default=None,
        help="Only list units owned by this player id.",
    )

    unit = subparsers.add_parser(
        "unit",
        help="Print the full command log for one unit (follow a villager).",
    )
    unit.add_argument("replay", help="Path to a .aoe2record file.")
    unit.add_argument("object_id", type=int, help="Object id of the unit to follow.")

    assignments = subparsers.add_parser(
        "assignments",
        help="Number villagers by appearance and infer each one's first resource.",
    )
    assignments.add_argument("replay", help="Path to a .aoe2record file.")
    assignments.add_argument(
        "-p", "--player", type=int, default=1,
        help="Player id to analyse (default: 1).",
    )

    return parser


def _load(replay: str):
    try:
        return parse_replay(replay)
    except ReplayParseError as exc:
        print(f"error: could not parse replay: {exc}", file=sys.stderr)
        return None


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "analyze":
        summary = _load(args.replay)
        if summary is None:
            return 1
        if args.summary_only:
            print_summary(summary)
        else:
            print_report(summary)
        return 0

    if args.command == "villagers":
        summary = _load(args.replay)
        if summary is None:
            return 1
        print(format_villager_list(summary, args.player), end="")
        return 0

    if args.command == "unit":
        summary = _load(args.replay)
        if summary is None:
            return 1
        print(format_unit_log(summary, args.object_id), end="")
        return 0

    if args.command == "assignments":
        summary = _load(args.replay)
        if summary is None:
            return 1
        print(format_assignments(summary, args.player), end="")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
