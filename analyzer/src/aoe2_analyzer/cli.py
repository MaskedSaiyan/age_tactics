"""Command-line interface for aoe2_analyzer.

Usage:
    python -m aoe2_analyzer analyze   path/to/replay.aoe2record [--build-order]
    python -m aoe2_analyzer villagers path/to/replay.aoe2record [--player N]
    python -m aoe2_analyzer unit      path/to/replay.aoe2record <object_id>
"""

from __future__ import annotations

import argparse
import glob
import os
import sys
import time
from typing import Optional, Sequence

from . import __version__
from .parser import ReplayParseError, parse_replay, quick_identify
from .report import (
    find_player,
    format_assignments,
    format_compare,
    format_identity,
    format_report,
    format_summary,
    format_unit_log,
    format_villager_list,
    rename_command,
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
        "-p",
        "--player",
        default=None,
        help="Only analyse this player (name substring or numeric id).",
    )
    analyze.add_argument(
        "-s",
        "--summary-only",
        action="store_true",
        help="Print only the overview section (no build order / assignments).",
    )
    analyze.add_argument(
        "-o",
        "--out",
        default=None,
        help="Write the report to this file instead of the screen.",
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

    scan = subparsers.add_parser(
        "scan",
        help="Fast header-only scan of a folder: who's in each game, newest first.",
    )
    scan.add_argument(
        "paths", nargs="+",
        help="Folders and/or .aoe2record files (globs work).",
    )

    identify = subparsers.add_parser(
        "id",
        help="Print who-vs-who + an mv line for replays; --rename applies it.",
    )
    identify.add_argument(
        "paths", nargs="+", help="Folders and/or .aoe2record files (globs work).",
    )
    identify.add_argument(
        "-r", "--rename", action="store_true",
        help="Actually rename each file to its suggested name (collision-safe).",
    )

    versus = subparsers.add_parser(
        "versus",
        help="Head-to-head: compare two players within ONE replay.",
    )
    versus.add_argument("replay", help="Path to a .aoe2record file.")
    versus.add_argument(
        "players", nargs=2, metavar="PLAYER",
        help="Two players (name substring or id), e.g. soad shura.",
    )
    versus.add_argument("-o", "--out", default=None, help="Write the table to this file.")

    compare = subparsers.add_parser(
        "compare",
        help="Compare key metrics for one player across several replays.",
    )
    compare.add_argument(
        "replays", nargs="+", help="Two or more .aoe2record files (globs work).",
    )
    compare.add_argument(
        "-p", "--player", required=True,
        help="Player to compare (name substring or numeric id).",
    )
    compare.add_argument(
        "-o", "--out", default=None, help="Write the table to this file.",
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


def _expand_replays(paths: Sequence[str]) -> list[str]:
    """Expand folders and globs into a de-duplicated list of .aoe2record files."""
    files: list[str] = []
    for p in paths:
        if os.path.isdir(p):
            files += sorted(glob.glob(os.path.join(p, "*.aoe2record")))
        elif any(c in p for c in "*?["):
            files += sorted(glob.glob(p))
        else:
            files.append(p)
    seen: set[str] = set()
    out: list[str] = []
    for f in files:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


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

    if not do_rename:
        # Just print a copy-paste-ready mv command.
        print("\nTo rename (copy-paste):")
        print(f"  {rename_command(replay, summary)}")
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

        players = None
        if args.player is not None:
            p = find_player(summary, args.player)
            if p is None:
                names = ", ".join(pl.name for pl in summary.players)
                print(f"error: no player matching '{args.player}'. "
                      f"Players: {names}", file=sys.stderr)
                return 1
            players = [p]

        if args.summary_only:
            text = format_summary(summary, players)
        else:
            text = format_report(summary, players)

        if args.out:
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(text)
            print(f"Wrote report to {args.out}")
        else:
            print(text, end="")
            _suggest_and_maybe_rename(args.replay, summary, args.rename)
        return 0

    if args.command == "versus":
        summary = _load(args.replay)
        if summary is None:
            return 1
        matchup_players: list = []
        for q in args.players:
            p = find_player(summary, q)
            if p is None:
                names = ", ".join(pl.name for pl in summary.players)
                print(f"error: no player matching '{q}'. Players: {names}",
                      file=sys.stderr)
                return 1
            matchup_players.append((p.name, p))
        text = format_compare(matchup_players)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(text)
            print(f"Wrote head-to-head to {args.out}")
        else:
            print(text, end="")
        return 0

    if args.command == "compare":
        games: list = []
        for replay in args.replays:
            summary = _load(replay)
            if summary is None:
                continue
            p = find_player(summary, args.player)
            if p is None:
                print(f"{replay}: no player matching '{args.player}' — skipped",
                      file=sys.stderr)
                continue
            games.append((os.path.basename(replay), p))
        if not games:
            print("error: no games matched the player.", file=sys.stderr)
            return 1
        text = format_compare(games)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(text)
            print(f"Wrote comparison to {args.out}")
        else:
            print(text, end="")
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

    if args.command == "scan":
        files = _expand_replays(args.paths)
        rows = []
        for f in files:
            try:
                info = quick_identify(f)
            except ReplayParseError as exc:
                print(f"{f}: {exc}", file=sys.stderr)
                continue
            mtime = os.path.getmtime(f) if os.path.exists(f) else 0
            rows.append((mtime, f, info))
        if not rows:
            print("No replays found.", file=sys.stderr)
            return 1
        rows.sort(key=lambda r: -r[0])  # newest first
        print(f"{len(rows)} replay(s), newest first:\n")
        for mtime, f, info in rows:
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime)) if mtime else "----"
            names = ", ".join(n for n in info["names"] if n) or "unknown"
            print(f"{ts}  {os.path.basename(f)}")
            print(f"                  {names}")
        return 0

    if args.command == "id":
        files = _expand_replays(args.paths)
        exit_code = 0
        renamed = 0
        for replay in files:
            try:
                summary = parse_replay(replay)
            except ReplayParseError as exc:
                print(f"{replay}: error: {exc}", file=sys.stderr)
                exit_code = 1
                continue
            if not args.rename:
                print(f"# {format_identity(replay, summary)}")
                print(rename_command(replay, summary))
                continue
            target_name = suggested_name(
                [p.name for p in summary.players], summary.game_duration_seconds
            ) + ".aoe2record"
            target = os.path.join(os.path.dirname(replay), target_name)
            if os.path.abspath(target) == os.path.abspath(replay):
                print(f"{os.path.basename(replay)}: already named — skipped")
                continue
            target = _unique_path(target)
            try:
                os.rename(replay, target)
            except OSError as exc:
                print(f"{replay}: could not rename: {exc}", file=sys.stderr)
                exit_code = 1
                continue
            print(f"{os.path.basename(replay)}  ->  {os.path.basename(target)}")
            renamed += 1
        if args.rename:
            print(f"\nRenamed {renamed} file(s).")
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
