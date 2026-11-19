#!/usr/bin/env python3
"""Minimal static server for real-browser dashboard smoke tests."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
import argparse

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        request_path = urlsplit(path).path
        if request_path in ("/", "/index.html"):
            return str(FRONTEND / "index.html")
        if request_path.startswith("/assets/"):
            relative = request_path[len("/assets/"):]
            candidate = (FRONTEND / relative).resolve()
            if FRONTEND.resolve() in candidate.parents and candidate.is_file():
                return str(candidate)
        return str(FRONTEND / "__not_found__")

    def log_message(self, _format, *_args):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
