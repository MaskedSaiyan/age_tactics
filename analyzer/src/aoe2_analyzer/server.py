"""A tiny local web server that serves the interactive report with a game picker.

`serve(folder)` lists every .aoe2record in `folder` in a dropdown; picking one
parses it (cached by mtime) and renders the same self-contained report UI as
`aoe report`. Stdlib only — no Flask, no install.
"""

from __future__ import annotations

import glob
import html
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .parser import ReplayParseError, parse_replay
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


def _list_games(folder: str) -> list[dict]:
    """All replays in `folder`, newest first, as {file, label} (file = basename)."""
    files = glob.glob(os.path.join(folder, "*.aoe2record"))
    files.sort(key=os.path.getmtime, reverse=True)
    return [{"file": os.path.basename(f), "label": _label(f)} for f in files]


def _error_page(title: str, body: str) -> bytes:
    return (
        "<!doctype html><meta charset='utf-8'>"
        "<body style='background:#0f1419;color:#e6edf3;font-family:system-ui;padding:40px'>"
        f"<h1>{html.escape(title)}</h1><p>{html.escape(body)}</p></body>"
    ).encode("utf-8")


def make_handler(folder: str):
    cache: dict[str, tuple[float, object]] = {}  # path -> (mtime, summary)

    def load(path: str):
        mtime = os.path.getmtime(path)
        hit = cache.get(path)
        if hit and hit[0] == mtime:
            return hit[1]
        summary = parse_replay(path)
        cache[path] = (mtime, summary)
        return summary

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

            games = _list_games(folder)
            if not games:
                self._send(_error_page("Sin partidas",
                           f"No hay .aoe2record en {folder}."), 404)
                return

            # Pick the requested game (validated against the listing) or the newest.
            want = parse_qs(parsed.query).get("game", [None])[0]
            valid = {g["file"] for g in games}
            selected = want if want in valid else games[0]["file"]

            try:
                summary = load(os.path.join(folder, selected))
            except ReplayParseError as exc:
                self._send(_error_page("No se pudo leer la partida", str(exc)), 500)
                return

            self._send(build_html(summary, games=games, selected=selected).encode("utf-8"))

    return Handler


def serve(folder: str, host: str = "127.0.0.1", port: int = 8000) -> None:
    folder = os.path.abspath(folder)
    httpd = ThreadingHTTPServer((host, port), make_handler(folder))
    url = f"http://{host}:{port}/"
    print(f"Serving replays from {folder}")
    print(f"Open:  {url}   (Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        httpd.server_close()
