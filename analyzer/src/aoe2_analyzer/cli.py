"""Command-line interface for aoe2_analyzer.

Usage:
    python -m aoe2_analyzer analyze   path/to/replay.aoe2record [--build-order]
    python -m aoe2_analyzer villagers path/to/replay.aoe2record [--player N]
    python -m aoe2_analyzer unit      path/to/replay.aoe2record <object_id>
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional, Sequence

from . import __version__
from .parser import ReplayParseError, parse_replay
from .report import (
    format_assignments,
    format_identity,
    format_unit_log,
    format_villager_list,
    print_report,
    print_summary,
    suggested_name,
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
    analyze.add_argument(
        "-r",
        "--rename",
        action="store_true",
        help="After analysing, suggest a filename and offer to rename the file.",
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

    identify = subparsers.add_parser(
        "id",
        help="Quickly print who-vs-who for one or more replays (to rename them).",
    )
    identify.add_argument(
        "replays", nargs="+", help="One or more .aoe2record files (globs work).",
    )

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


def _unique_path(path: str) -> str:
    """Return `path`, or path with -2/-3/... before the extension if it exists."""
    if not os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{root}-{n}{ext}"):
        n += 1
    return f"{root}-{n}{ext}"


def _suggest_and_maybe_rename(replay: str, summary, do_rename: bool) -> None:
    names = [p.name for p in summary.players]
    suggested = suggested_name(names, summary.game_duration_seconds) + ".aoe2record"
    print(f"\nSuggested filename: {suggested}")

    if not do_rename:
        print("(run with --rename to rename this file)")
        return
    if not sys.stdin.isatty():
        print("(no interactive terminal; skipping rename)")
        return

    prompt = "Rename it? [Enter = use suggestion / n = keep / or type a new name]: "
    try:
        answer = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print("\nKept original name.")
        return

    if answer.lower() in ("n", "no"):
        print("Kept original name.")
        return

    chosen = suggested if answer == "" else answer
    if not chosen.endswith(".aoe2record"):
        chosen += ".aoe2record"
    # Stay in the same directory; ignore any path the user typed.
    target = os.path.join(os.path.dirname(replay), os.path.basename(chosen))
    target = _unique_path(target)
    try:
        os.rename(replay, target)
    except OSError as exc:
        print(f"error: could not rename: {exc}", file=sys.stderr)
        return
    print(f"Renamed -> {os.path.basename(target)}")


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
        _suggest_and_maybe_rename(args.replay, summary, args.rename)
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

    if args.command == "id":
        exit_code = 0
        for replay in args.replays:
            try:
                summary = parse_replay(replay)
            except ReplayParseError as exc:
                print(f"{replay}: error: {exc}", file=sys.stderr)
                exit_code = 1
                continue
            print(format_identity(replay, summary))
        return exit_code

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
