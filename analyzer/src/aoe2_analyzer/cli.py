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
import shlex
import sys
import time
from typing import Optional, Sequence

from . import __version__
from .parser import ReplayParseError, parse_replay, quick_identify
from .report import (
    dated_filename,
    find_player,
    format_assignments,
    format_compare,
    format_identity,
    format_progression,
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
    analyze.add_argument(
        "replay",
        nargs="?",
        default=None,
        help="A .aoe2record file, OR a folder (uses its newest replay). "
        "Omit entirely to use the newest replay in ./samples.",
    )
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

    report = subparsers.add_parser(
        "report",
        help="Generate a self-contained interactive HTML report (charts + timeline).",
    )
    report.add_argument(
        "replay",
        nargs="?",
        default=None,
        help="A .aoe2record file, a folder (newest replay), or omit for ./samples.",
    )
    report.add_argument(
        "-o", "--out", default=None,
        help="HTML output path (default: <replay-name>.html next to the replay).",
    )
    report.add_argument(
        "--open", action="store_true", dest="open_browser",
        help="Open the generated report in the browser (WSL/Linux/macOS).",
    )

    serve = subparsers.add_parser(
        "serve",
        help="Local web app: pick any replay from a dropdown and view its report.",
    )
    serve.add_argument(
        "folder", nargs="?", default=None,
        help="Folder of replays to serve (default: ./samples or $AOE2_SAMPLES_DIR).",
    )
    serve.add_argument("--port", type=int, default=8000, help="Port (default: 8000).")
    serve.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1).")
    serve.add_argument("--open", action="store_true", dest="open_browser",
                       help="Open the app in the browser once it's up.")

    progression = subparsers.add_parser(
        "progression",
        help="Cross-player timeline: who led on vills/military, minute by minute.",
    )
    progression.add_argument(
        "replay",
        nargs="?",
        default=None,
        help="A .aoe2record file, a folder (newest replay), or omit for ./samples.",
    )
    progression.add_argument(
        "--step", type=int, default=180,
        help="Seconds between time marks (default: 180 = every 3 min).",
    )
    progression.add_argument("-o", "--out", default=None, help="Write the table to this file.")

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


def _newest_replay(folder: str) -> Optional[str]:
    """Return the most-recently-modified .aoe2record in `folder`, or None."""
    files = glob.glob(os.path.join(folder, "*.aoe2record"))
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def _resolve_replay(arg: Optional[str], default_dir: Optional[str] = None) -> Optional[str]:
    """Turn a file / folder / omitted arg into a concrete replay path.

    - a file path  -> itself
    - a folder     -> its newest .aoe2record
    - omitted/None -> the newest .aoe2record in the default folder
                      ($AOE2_SAMPLES_DIR if set, else ./samples)

    Prints which file was auto-picked so the choice is never a surprise.
    """
    if default_dir is None:
        default_dir = os.environ.get("AOE2_SAMPLES_DIR", "samples")
    target = arg if arg is not None else default_dir
    if os.path.isdir(target):
        newest = _newest_replay(target)
        if newest is None:
            print(f"error: no .aoe2record files in '{target}'.", file=sys.stderr)
            return None
        print(f"Using newest replay in {target}: {os.path.basename(newest)}\n")
        return newest
    if arg is None:
        print(f"error: no '{default_dir}' folder here; pass a replay path.", file=sys.stderr)
        return None
    return target


def _open_in_browser(path: str) -> None:
    """Best-effort open `path` — tries WSL/Linux/macOS openers, then webbrowser."""
    import shutil
    import subprocess

    # URLs (the server) are opened as-is; file paths get absolutised.
    abspath = path if path.startswith(("http://", "https://")) else os.path.abspath(path)
    # Proper GUI openers. `open` only on macOS — on Linux it's run-mailcap (no GUI).
    openers = ["wslview", "xdg-open"]
    if sys.platform == "darwin":
        openers.append("open")
    for opener in openers:
        if shutil.which(opener):
            try:
                subprocess.Popen([opener, abspath],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print(f"Opening in browser ({opener})…")
                return
            except OSError:
                pass
    # WSL fallback: explorer.exe opens URLs directly, but needs a Windows path
    # for local files.
    if shutil.which("explorer.exe"):
        try:
            if abspath.startswith(("http://", "https://")):
                win = abspath
            else:
                win = subprocess.run(["wslpath", "-w", abspath],
                                     capture_output=True, text=True).stdout.strip()
            subprocess.Popen(["explorer.exe", win or abspath],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("Opening in browser (explorer.exe)…")
            return
        except OSError:
            pass
    try:
        import webbrowser
        webbrowser.open(f"file://{abspath}")
        print("Opening in browser…")
    except Exception:
        print(f"(could not auto-open — open manually: {abspath})")


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
        replay = _resolve_replay(args.replay)
        if replay is None:
            return 1
        args.replay = replay
        summary = _load(replay)
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

    if args.command == "report":
        replay = _resolve_replay(args.replay)
        if replay is None:
            return 1
        summary = _load(replay)
        if summary is None:
            return 1
        from .webreport import build_html
        out = args.out or (os.path.splitext(replay)[0] + ".html")
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(build_html(summary))
        print(f"Wrote HTML report to {out}")
        if args.open_browser:
            _open_in_browser(out)
        else:
            print(f"Open it with:  xdg-open {shlex.quote(out)}")
        return 0

    if args.command == "serve":
        folder = args.folder or os.environ.get("AOE2_SAMPLES_DIR", "samples")
        if not os.path.isdir(folder):
            print(f"error: not a folder: {folder}", file=sys.stderr)
            return 1
        from .server import serve as serve_app
        if args.open_browser:
            url = f"http://{args.host}:{args.port}/"
            import threading
            threading.Timer(0.8, lambda: _open_in_browser(url)).start()
        serve_app(folder, host=args.host, port=args.port)
        return 0

    if args.command == "progression":
        replay = _resolve_replay(args.replay)
        if replay is None:
            return 1
        summary = _load(replay)
        if summary is None:
            return 1
        text = format_progression(summary, args.step)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(text)
            print(f"Wrote progression to {args.out}")
        else:
            print(text, end="")
        return 0

    if args.command == "versus":
        replay = _resolve_replay(args.replay)
        if replay is None:
            return 1
        summary = _load(replay)
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
            mtime = os.path.getmtime(replay) if os.path.exists(replay) else None
            if not args.rename:
                print(f"# {format_identity(replay, summary)}")
                print(rename_command(replay, summary, mtime))
                continue
            target_name = dated_filename(replay, summary, mtime)
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
