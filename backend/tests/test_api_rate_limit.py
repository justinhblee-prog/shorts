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

    def test_forwarded_for_is_ignored_without_trusted_proxy_configuration(self):
        middleware = ApiRateLimitMiddleware(lambda *args: None, self.store)
        scope = {
            "client": ("192.0.2.10", 4321),
            "headers": [(b"x-forwarded-for", b"198.51.100.44")],
        }
        self.assertEqual(middleware._client_identity(scope), "192.0.2.10")

    def test_untrusted_peer_cannot_spoof_forwarded_identity(self):
        middleware = ApiRateLimitMiddleware(
            lambda *args: None, self.store,
            trusted_proxy_cidrs="10.0.0.0/8",
        )
        scope = {
            "client": ("192.0.2.10", 4321),
            "headers": [(b"x-forwarded-for", b"198.51.100.44")],
        }
        self.assertEqual(middleware._client_identity(scope), "192.0.2.10")

    def test_trusted_proxy_uses_forwarded_client_address(self):
        middleware = ApiRateLimitMiddleware(
            lambda *args: None, self.store,
            trusted_proxy_cidrs="10.0.0.0/8",
        )
        scope = {
            "client": ("10.0.0.8", 4321),
            "headers": [(b"x-forwarded-for", b"198.51.100.44")],
        }
        self.assertEqual(middleware._client_identity(scope), "198.51.100.44")

    def test_forwarded_chain_walks_right_to_left_and_ignores_untrusted_prefix(self):
        middleware = ApiRateLimitMiddleware(
            lambda *args: None, self.store,
            trusted_proxy_cidrs="10.0.0.0/8,192.168.0.0/16",
        )
        scope = {
            "client": ("10.0.0.8", 4321),
            "headers": [(b"x-forwarded-for",
                         b"203.0.113.200, 198.51.100.44, 192.168.1.2")],
        }
        self.assertEqual(middleware._client_identity(scope), "198.51.100.44")

    def test_malformed_or_ambiguous_forwarded_headers_fall_back_to_proxy_peer(self):
        middleware = ApiRateLimitMiddleware(
            lambda *args: None, self.store,
            trusted_proxy_cidrs="10.0.0.0/8",
        )
        for headers in (
            [(b"x-forwarded-for", b"not-an-ip")],
            [(b"x-forwarded-for", b"198.51.100.1"),
             (b"x-forwarded-for", b"198.51.100.2")],
            [(b"x-forwarded-for", b"198.51.100.1,,198.51.100.2")],
            [(b"x-forwarded-for", b"198.51.100.1, " + b"198.51.100.2," * 25)],
        ):
            with self.subTest(headers=headers):
                self.assertEqual(
                    middleware._client_identity({"client": ("10.0.0.8", 4321), "headers": headers}),
                    "10.0.0.8",
                )

    def test_trusted_proxy_supports_ipv6_and_validates_network_configuration(self):
        middleware = ApiRateLimitMiddleware(
            lambda *args: None, self.store,
            trusted_proxy_cidrs="2001:db8:abcd::/48",
        )
        scope = {
            "client": ("2001:db8:abcd::8", 4321),
            "headers": [(b"x-forwarded-for", b"2001:db8:ffff::44")],
        }
        self.assertEqual(middleware._client_identity(scope), "2001:db8:ffff::44")
        with self.assertRaises(ValueError):
            ApiRateLimitMiddleware(lambda *args: None, self.store,
                                   trusted_proxy_cidrs="not-a-network")


if __name__ == "__main__":
    unittest.main()
