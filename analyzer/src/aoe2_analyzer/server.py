"""A tiny local web server that serves the interactive report with a game picker.

`serve(folder)` lists every .aoe2record in `folder` in a dropdown; picking one
parses it (cached by mtime) and renders the same self-contained report UI as
`aoe report`. A player filter narrows the list to one regular player.

"Regular players" (your real opponents) are detected by frequency: a name that
appears in many games. AI personalities are drawn randomly from a huge pool, so
each shows up only once or twice — they fall below the threshold and never
clutter the filter. Stdlib only — no Flask, no install.
"""

from __future__ import annotations

import glob
import html
import math
import os
import re
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .parser import ReplayParseError, parse_replay, quick_identify
from .webreport import build_html


def _label(path: str) -> str:
    """A clean dropdown label from a dated replay filename.

    'YYYY-MM-DD-HHMM_a-vs-b_47m'  ->  'YYYY-MM-DD HH:MM  ·  a vs b  ·  47m'.
    Falls back to the raw stem for non-standard names.
    """
    base = os.path.splitext(os.path.basename(path))[0]
    m = re.match(r"(\d{4}-\d{2}-\d{2})-(\d{2})(\d{2})_(.*?)(?:_(\d+m))?$", base)
    if not m:
        return base
    date, hh, mm, mid, dur = m.groups()
    parts = [f"{date} {hh}:{mm}", mid.replace("-vs-", " vs ")]
    if dur:
        parts.append(dur)
    return "  ·  ".join(parts)


def make_handler(folder: str, min_games: int | None):
    summary_cache: dict[str, tuple[float, object]] = {}  # path -> (mtime, summary)
    name_cache: dict[str, tuple[float, list]] = {}  # path -> (mtime, [names]) header scan

    def load(path: str):
        mtime = os.path.getmtime(path)
        hit = summary_cache.get(path)
        if hit and hit[0] == mtime:
            return hit[1]
        summary = parse_replay(path)
        summary_cache[path] = (mtime, summary)
        return summary

    def names_of(path: str) -> list:
        mtime = os.path.getmtime(path)
        hit = name_cache.get(path)
        if hit and hit[0] == mtime:
            return hit[1]
        try:
            names = sorted({n for n in quick_identify(path).get("names", []) if n})
        except ReplayParseError:
            names = []
        name_cache[path] = (mtime, names)
        return names

    def index():
        """(games newest-first with their regular players, sorted player filter)."""
        files = sorted(glob.glob(os.path.join(folder, "*.aoe2record")),
                       key=os.path.getmtime, reverse=True)
        per_game = {f: names_of(f) for f in files}
        freq: Counter = Counter()
        for names in per_game.values():
            freq.update(names)
        threshold = min_games if min_games is not None else max(3, round(0.02 * len(files)))
        # A regular player is a recurring *handle*: frequent AND no spaces/brackets/
        # apostrophes (which mark lobby titles like "soad's Game" / "[Rematch] soad"
        # and multi-word AI personality names like "King Alfonso").
        regulars = {
            n for n, c in freq.items()
            if c >= threshold and not re.search(r"[\s\[\]'()·]", n)
        }
        games = [{
            "file": os.path.basename(f),
            "label": _label(f),
            "players": [n for n in per_game[f] if n in regulars],
        } for f in files]
        player_filter = sorted(regulars, key=lambda n: (-freq[n], n.lower()))
        return games, player_filter

    def error_page(title: str, body: str) -> bytes:
        return (
            "<!doctype html><meta charset='utf-8'>"
            "<body style='background:#0f1419;color:#e6edf3;font-family:system-ui;padding:40px'>"
            f"<h1>{html.escape(title)}</h1><p>{html.escape(body)}</p></body>"
        ).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # quieter console
            pass

        def _send(self, body: bytes, code: int = 200, ctype: str = "text/html; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path in ("/favicon.ico", "/robots.txt"):
                self._send(b"", 204)
                return

            games, player_filter = index()
            if not games:
                self._send(error_page("Sin partidas", f"No hay .aoe2record en {folder}."), 404)
                return

            want = parse_qs(parsed.query).get("game", [None])[0]
            valid = {g["file"] for g in games}
            selected = want if want in valid else games[0]["file"]

            try:
                summary = load(os.path.join(folder, selected))
            except ReplayParseError as exc:
                self._send(error_page("No se pudo leer la partida", str(exc)), 500)
                return

            body = build_html(summary, games=games, selected=selected,
                              player_filter=player_filter).encode("utf-8")
            self._send(body)

    return Handler


def serve(folder: str, host: str = "127.0.0.1", port: int = 8000,
          min_games: int | None = None) -> None:
    folder = os.path.abspath(folder)
    httpd = ThreadingHTTPServer((host, port), make_handler(folder, min_games))
    url = f"http://{host}:{port}/"
    print(f"Serving replays from {folder}")
    print(f"Open:  {url}   (Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        httpd.server_close()
