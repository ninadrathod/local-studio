"""
Static file server for the frontend (repo root), like `python -m http.server`,
but every response carries `Cache-Control: no-cache`. Browsers still cache
files, yet revalidate them on each load (cheap 304s), so an updated
script.js / styles.css / js/*.js is picked up on the next refresh without
hand-bumped `?v=` query strings.

Usage: python scripts/serve_frontend.py PORT   (serves the current directory)
"""

from __future__ import annotations

import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


class NoCacheHandler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()


def make_server(port: int, directory: str = ".", host: str = "") -> ThreadingHTTPServer:
    """Build the server (host "" = all interfaces, same as `python -m http.server`)."""
    return ThreadingHTTPServer((host, port), partial(NoCacheHandler, directory=directory))


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not argv[1].isdigit():
        print("usage: serve_frontend.py PORT", file=sys.stderr)
        return 2
    port = int(argv[1])
    with make_server(port) as server:
        print(f"Serving frontend on port {port} (Cache-Control: no-cache)", flush=True)
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
