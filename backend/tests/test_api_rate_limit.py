import asyncio
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from api_rate_limit import ApiRateLimitMiddleware, SQLiteRateLimitStore


class ApiRateLimitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "nexus.sqlite3"
        self.store = SQLiteRateLimitStore(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_fixed_window_limit_and_reset(self):
        first = self.store.consume("198.51.100.10", "publish", 2, now=1201)
        second = self.store.consume("198.51.100.10", "publish", 2, now=1202)
        third = self.store.consume("198.51.100.10", "publish", 2, now=1203)
        next_window = self.store.consume("198.51.100.10", "publish", 2, now=1260)
        self.assertTrue(first["allowed"])
        self.assertTrue(second["allowed"])
        self.assertFalse(third["allowed"])
        self.assertEqual(third["remaining"], 0)
        self.assertEqual(third["retry_after"], 57)
        self.assertTrue(next_window["allowed"])

    def test_concurrent_requests_cannot_exceed_atomic_limit(self):
        def consume(_):
            return self.store.consume("203.0.113.25", "review", 5, now=3000)["allowed"]
        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(consume, range(40)))
        self.assertEqual(sum(results), 5)

    def test_subject_identifier_is_hashed_in_persistent_storage(self):
        self.store.consume("203.0.113.77", "auth", 10, now=600)
        import sqlite3
        with sqlite3.connect(self.db) as connection:
            row = connection.execute(
                "SELECT subject_hash FROM api_rate_limit_buckets"
            ).fetchone()
        self.assertEqual(len(row[0]), 64)
        self.assertNotIn("203.0.113.77", row[0])

    def test_middleware_returns_429_and_rate_limit_headers(self):
        calls = []
        async def inner(scope, receive, send):
            calls.append(scope["path"])
            await send({"type": "http.response.start", "status": 204, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        middleware = ApiRateLimitMiddleware(
            inner, self.store, limits={"auth": 1}, window_seconds=60
        )

        async def request():
            messages = []
            scope = {
                "type": "http",
                "method": "POST",
                "path": "/api/tiktok/oauth/start",
                "client": ("192.0.2.10", 4321),
                "headers": [],
            }
            async def receive():
                return {"type": "http.request", "body": b"", "more_body": False}
            async def send(message):
                messages.append(message)
            await middleware(scope, receive, send)
            return messages

        first = asyncio.run(request())
        second = asyncio.run(request())
        first_headers = dict(first[0]["headers"])
        second_headers = dict(second[0]["headers"])
        self.assertEqual(first[0]["status"], 204)
        self.assertEqual(first_headers[b"x-ratelimit-limit"], b"1")
        self.assertEqual(first_headers[b"x-ratelimit-remaining"], b"0")
        self.assertEqual(second[0]["status"], 429)
        self.assertIn(b"retry-after", second_headers)
        self.assertEqual(len(calls), 1)

    def test_health_get_is_not_rate_limited(self):
        async def inner(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})
        middleware = ApiRateLimitMiddleware(inner, self.store)

        async def request():
            messages = []
            scope = {
                "type": "http", "method": "GET", "path": "/api/health",
                "client": ("192.0.2.11", 4321), "headers": [],
            }
            async def receive():
                return {"type": "http.request", "body": b"", "more_body": False}
            async def send(message):
                messages.append(message)
            await middleware(scope, receive, send)
            return messages
        response = asyncio.run(request())
        self.assertEqual(response[0]["status"], 200)
        self.assertEqual(response[0]["headers"], [])


if __name__ == "__main__":
    unittest.main()
