#!/usr/bin/env python3
"""Disposable authenticated fixture server for the development-monitor browser smoke test."""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
TOKEN = "development-monitor-smoke-valid-token"
JOBS = [
    {
        "id": "BUILD-SMOKE-001", "title": "Fixture ready task", "status": "ready",
        "priority": 1, "attempts": 0, "max_attempts": 3,
        "scope": ["scripts/example.py"], "dependencies": [],
        "result_summary": "Ready fixture", "lease_token": "SECRET_LEASE_TOKEN",
        "runner_hostname": "SECRET_RUNNER_HOST", "private_event_details": "SECRET_JOB_DETAILS",
    },
    {
        "id": "BUILD-SMOKE-002", "title": "Fixture blocked task", "status": "blocked",
        "priority": 2, "attempts": 1, "max_attempts": 3,
        "scope": ["backend/example.py"], "dependencies": ["BUILD-SMOKE-001"],
        "result_summary": "Blocked fixture", "lease_token": "SECRET_LEASE_TOKEN_2",
        "runner_hostname": "SECRET_RUNNER_HOST_2", "private_event_details": "SECRET_JOB_DETAILS_2",
    },
]


class Handler(BaseHTTPRequestHandler):
    server_version = "DevelopmentMonitorSmoke/1.0"

    def log_message(self, *_args):
        return

    def send_json(self, status: int, payload: object):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        self.server.requests.append({"method": "GET", "path": path})

        if path == "/__test__/health":
            return self.send_json(200, {"ok": True})
        if path == "/__test__/requests":
            return self.send_json(200, {"requests": self.server.requests})

        static = {
            "/": FRONTEND / "index.html",
            "/assets/app.js": FRONTEND / "app.js",
            "/assets/styles.css": FRONTEND / "styles.css",
        }.get(path)
        if static:
            if not static.is_file():
                return self.send_json(404, {"detail": "Fixture asset missing"})
            body = static.read_bytes()
            content_type = "text/html; charset=utf-8" if path == "/" else (
                "text/javascript; charset=utf-8" if path.endswith(".js") else "text/css; charset=utf-8"
            )
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)

        if path.startswith("/api/development/") and self.headers.get("X-Review-Token") != TOKEN:
            return self.send_json(401, {"detail": "Invalid development monitor token"})

        if path == "/api/development/summary":
            return self.send_json(200, {
                "total": 2, "ready": 1, "blocked": 1, "active_leases": 0,
                "expired_leases": 0, "online_workers": 1, "known_workers": 1,
            })
        if path == "/api/development/workers":
            return self.send_json(200, {"workers": [{
                "worker_id": "fixture-worker", "is_online": True, "status": "idle",
                "current_job_id": None, "last_seen_at": "2026-11-21T00:00:00Z",
                "hostname": "SECRET_RUNNER_HOST",
            }]})
        if path == "/api/development/jobs":
            status = parse_qs(parsed.query).get("status", [""])[0]
            items = [job for job in JOBS if not status or job["status"] == status]
            return self.send_json(200, {"items": items, "limit": 100, "next_cursor": None})
        if path.startswith("/api/development/jobs/") and path.endswith("/events"):
            job_id = path.split("/")[4]
            if job_id not in {job["id"] for job in JOBS}:
                return self.send_json(404, {"detail": "Job not found"})
            suffix = "001" if job_id.endswith("001") else "002"
            return self.send_json(200, {"events": [{
                "event_type": "status_changed", "from_status": "queued",
                "to_status": "ready" if suffix == "001" else "blocked",
                "actor": "fixture", "created_at": "2026-11-21T00:00:00Z",
                "details": "SECRET_PRIVATE_EVENT_DETAILS",
            }]})

        if path.startswith("/api/"):
            return self.send_json(200, {})
        return self.send_json(404, {"detail": "Not found"})

    def do_POST(self):
        self.server.requests.append({"method": "POST", "path": urlparse(self.path).path})
        return self.send_json(405, {"detail": "Mutation routes are disabled in this fixture"})

    def do_PUT(self):
        self.server.requests.append({"method": "PUT", "path": urlparse(self.path).path})
        return self.send_json(405, {"detail": "Mutation routes are disabled in this fixture"})

    def do_DELETE(self):
        self.server.requests.append({"method": "DELETE", "path": urlparse(self.path).path})
        return self.send_json(405, {"detail": "Mutation routes are disabled in this fixture"})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.requests = []
    print(f"READY http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
