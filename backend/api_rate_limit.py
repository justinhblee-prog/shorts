"""SQLite-backed API rate limiting shared by processes using the same database."""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
from pathlib import Path


class SQLiteRateLimitStore:
    def __init__(self, db_path="data/nexus.sqlite3"):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._db() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS api_rate_limit_buckets (
                    scope TEXT NOT NULL,
                    subject_hash TEXT NOT NULL,
                    window_start INTEGER NOT NULL,
                    request_count INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY(scope, subject_hash)
                )
            """)
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_api_rate_limit_updated "
                "ON api_rate_limit_buckets(updated_at)"
            )

    def _db(self):
        connection = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    @staticmethod
    def _subject_hash(subject):
        return hashlib.sha256(str(subject).encode("utf-8")).hexdigest()

    def consume(self, subject, scope, limit, window_seconds=60, now=None):
        """Atomically consume one request slot in a fixed time window."""
        limit = int(limit)
        window_seconds = int(window_seconds)
        if limit < 1 or window_seconds < 1:
            raise ValueError("limit and window_seconds must be positive")
        current = int(time.time() if now is None else now)
        window_start = current // window_seconds * window_seconds
        subject_hash = self._subject_hash(subject)
        connection = self._db()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT window_start,request_count FROM api_rate_limit_buckets "
                "WHERE scope=? AND subject_hash=?",
                (str(scope), subject_hash),
            ).fetchone()
            if row is None or row["window_start"] != window_start:
                count = 1
                connection.execute("""
                    INSERT INTO api_rate_limit_buckets
                        (scope,subject_hash,window_start,request_count,updated_at)
                    VALUES(?,?,?,?,?)
                    ON CONFLICT(scope,subject_hash) DO UPDATE SET
                        window_start=excluded.window_start,
                        request_count=excluded.request_count,
                        updated_at=excluded.updated_at
                """, (str(scope), subject_hash, window_start, count, current))
            else:
                count = row["request_count"] + 1
                connection.execute(
                    "UPDATE api_rate_limit_buckets SET request_count=?,updated_at=? "
                    "WHERE scope=? AND subject_hash=?",
                    (count, current, str(scope), subject_hash),
                )
            # Bound persistent state without requiring a background cleanup worker.
            if window_start % 3600 == 0:
                connection.execute(
                    "DELETE FROM api_rate_limit_buckets WHERE updated_at < ?",
                    (current - 86400,),
                )
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

        retry_after = max(1, window_start + window_seconds - current)
        return {
            "allowed": count <= limit,
            "limit": limit,
            "remaining": max(0, limit - count),
            "retry_after": retry_after,
            "reset_at": window_start + window_seconds,
        }


class ApiRateLimitMiddleware:
    """Apply persistent per-client limits to API mutations and OAuth callbacks."""

    def __init__(self, app, store, limits=None, window_seconds=60):
        self.app = app
        self.store = store
        self.window_seconds = int(window_seconds)
        self.limits = {
            "default": 120,
            "auth": 20,
            "publish": 10,
            "control": 30,
            "review": 60,
            "production": 30,
        }
        if limits:
            self.limits.update({key: int(value) for key, value in limits.items()})
        if any(value < 1 for value in self.limits.values()):
            raise ValueError("all API rate limits must be positive")

    def _policy(self, method, path):
        callback = path == "/api/tiktok/oauth/callback"
        if method not in {"POST", "PUT", "PATCH", "DELETE"} and not callback:
            return None
        if path.startswith("/api/tiktok/oauth/"):
            return "auth"
        if path.startswith("/api/tiktok/") or path.startswith("/api/youtube/"):
            return "publish"
        if path.startswith("/api/queue/"):
            return "control"
        if path.startswith("/api/review/"):
            return "review"
        if path.startswith("/api/production/"):
            return "production"
        if path.startswith("/api/"):
            return "default"
        return None

    @staticmethod
    def _client_identity(scope):
        client = scope.get("client")
        # Do not trust caller-supplied X-Forwarded-For. Configure the ASGI server
        # and trusted proxy boundary explicitly before placing this behind a proxy.
        return str(client[0]) if client else "unknown"

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET").upper()
        path = scope.get("path", "")
        policy = self._policy(method, path)
        if policy is None:
            await self.app(scope, receive, send)
            return

        result = self.store.consume(
            self._client_identity(scope),
            policy,
            self.limits[policy],
            self.window_seconds,
        )
        headers = [
            (b"x-ratelimit-limit", str(result["limit"]).encode("ascii")),
            (b"x-ratelimit-remaining", str(result["remaining"]).encode("ascii")),
            (b"x-ratelimit-reset", str(result["reset_at"]).encode("ascii")),
        ]
        if not result["allowed"]:
            body = json.dumps({
                "detail": "Too many requests",
                "retry_after": result["retry_after"],
            }).encode("utf-8")
            headers.extend([
                (b"content-type", b"application/json"),
                (b"retry-after", str(result["retry_after"]).encode("ascii")),
                (b"content-length", str(len(body)).encode("ascii")),
            ])
            await send({"type": "http.response.start", "status": 429, "headers": headers})
            await send({"type": "http.response.body", "body": body})
            return

        async def send_with_rate_headers(message):
            if message["type"] == "http.response.start":
                message = dict(message)
                message["headers"] = list(message.get("headers", [])) + headers
            await send(message)

        await self.app(scope, receive, send_with_rate_headers)
