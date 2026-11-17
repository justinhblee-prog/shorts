import json
import os
import sqlite3
import tempfile
import unittest
import threading
from datetime import date, datetime, timezone, timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet
from youtube_oauth import (
    YouTubeOAuthStore, YouTubeOAuthManager, YouTubeOAuthError,
    REQUIRED_SCOPES, ANALYTICS_READ_SCOPE, YouTubeConnectionVerifier,
)


class GoogleOAuthTransport:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append((url, headers, body, timeout))
        status, payload = self.responses.pop(0)
        return status, json.dumps(payload).encode("utf-8")



class FakeCredentials:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.refreshed = False

    def refresh(self, request):
        self.refreshed = True


class FakeRequest:
    def execute(self):
        return True


class FakeYouTubeService:
    def channels(self):
        return self

    def list(self, **kwargs):
        self.kwargs = kwargs
        return self

    def execute(self):
        return {"items": [{"id": "UC123", "snippet": {"title": "Test Channel"}}]}


class FakeAnalyticsService:
    def __init__(self, error=None):
        self.error = error
        self.query_args = None

    def reports(self):
        return self

    def query(self, **kwargs):
        self.query_args = kwargs
        return self

    def execute(self):
        if self.error:
            raise self.error
        return {"columnHeaders": [{"name": "views"}], "rows": [[12]]}


class YouTubeOAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "oauth.sqlite3")
        self.store = YouTubeOAuthStore(self.db)
        self.key = Fernet.generate_key()
        self.transport = GoogleOAuthTransport([(
            200, {
                "access_token": "access-secret",
                "refresh_token": "refresh-secret",
                "scope": " ".join((*REQUIRED_SCOPES, ANALYTICS_READ_SCOPE)),
                "token_type": "Bearer",
                "expires_in": 3600,
            }
        )])
        self.manager = YouTubeOAuthManager(
            self.store, "google-client-id", "google-client-secret",
            "https://studio.example.test/api/youtube/oauth/callback",
            self.key, self.transport,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_oauth_state_create_and_consume_clocks_wait_for_write_lock(self):
        decision = datetime(2036, 7, 8, 9, 10, 17, tzinfo=timezone.utc)

        def assert_clock_waits(operation, expected_message):
            clock_called = threading.Event()
            started = threading.Event()
            outcome = {}

            def controlled_now():
                clock_called.set()
                return decision

            def run():
                started.set()
                try:
                    outcome["result"] = operation()
                except Exception as exc:
                    outcome["error"] = exc

            with self.store.db() as holder:
                holder.execute("BEGIN IMMEDIATE")
                with patch("youtube_oauth._now", side_effect=controlled_now):
                    thread = threading.Thread(target=run)
                    thread.start()
                    self.assertTrue(started.wait(1))
                    self.assertFalse(clock_called.wait(0.1), expected_message)
                    holder.commit()
                    thread.join(2)
                self.assertFalse(thread.is_alive(), "OAuth state transition did not finish")
            self.assertNotIn("error", outcome)
            return outcome.get("result")

        state_hash = "state-hash-lock-clock"
        assert_clock_waits(
            lambda: self.store.create_state(state_hash, 600),
            "YouTube OAuth state creation clock sampled before write lock",
        )
        with self.store.db() as connection:
            created = connection.execute(
                "SELECT created_at,expires_at FROM youtube_oauth_states WHERE state_hash=?",
                (state_hash,),
            ).fetchone()
        self.assertEqual(created["created_at"], decision.isoformat())
        self.assertEqual(
            created["expires_at"],
            (decision + timedelta(seconds=600)).isoformat(),
        )

        assert_clock_waits(
            lambda: self.store.consume_state(state_hash),
            "YouTube OAuth state consumption clock sampled before write lock",
        )
        with self.store.db() as connection:
            consumed = connection.execute(
                "SELECT used_at FROM youtube_oauth_states WHERE state_hash=?",
                (state_hash,),
            ).fetchone()
        self.assertEqual(consumed["used_at"], decision.isoformat())


    def test_authorization_url_requests_offline_access_and_required_scopes(self):
        result = self.manager.start_authorization()
        query = parse_qs(urlparse(result["authorization_url"]).query)
        state = query["state"][0]
        self.assertEqual(query["client_id"], ["google-client-id"])
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["access_type"], ["offline"])
        self.assertEqual(query["prompt"], ["consent"])
        self.assertIn(REQUIRED_SCOPES[0], query["scope"][0].split())
        self.assertIn(REQUIRED_SCOPES[1], query["scope"][0].split())
        self.assertEqual(result["expires_in"], 600)
        with self.store.db() as connection:
            row = connection.execute("SELECT * FROM youtube_oauth_states").fetchone()
        self.assertNotEqual(row["state_hash"], state)

    def test_code_exchange_encrypts_refresh_token_and_status_hides_secret(self):
        auth = self.manager.start_authorization()
        state = parse_qs(urlparse(auth["authorization_url"]).query)["state"][0]
        result = self.manager.exchange_code("one-time-code", state)
        self.assertTrue(result["connected"])
        row = self.store.token_record()
        self.assertNotIn("refresh-secret", row["refresh_token_encrypted"])
        self.assertEqual(self.manager.get_refresh_token(), "refresh-secret")
        status = self.manager.status()
        self.assertTrue(status["connected"])
        self.assertFalse(status["live_connectivity_verified"])
        self.assertEqual(status["mode"], "encrypted_oauth")
        self.assertNotIn("refresh_token", status)
        self.assertNotIn("access-secret", str(status))
        with self.assertRaisesRegex(YouTubeOAuthError, "invalid, expired or already used"):
            self.manager.exchange_code("one-time-code", state)

    def test_missing_required_scope_is_rejected_without_storing_token(self):
        transport = GoogleOAuthTransport([(
            200, {
                "access_token": "access",
                "refresh_token": "refresh",
                "scope": REQUIRED_SCOPES[0],
                "expires_in": 3600,
            }
        )])
        manager = YouTubeOAuthManager(
            self.store, "id", "secret",
            "https://studio.example.test/api/youtube/oauth/callback",
            self.key, transport,
        )
        auth = manager.start_authorization()
        state = parse_qs(urlparse(auth["authorization_url"]).query)["state"][0]
        with self.assertRaisesRegex(YouTubeOAuthError, "missing required YouTube scopes"):
            manager.exchange_code("code", state)
        self.assertIsNone(self.store.token_record())

    def test_missing_refresh_token_does_not_claim_connection(self):
        transport = GoogleOAuthTransport([(
            200, {"access_token": "access", "scope": " ".join(REQUIRED_SCOPES)}
        )])
        manager = YouTubeOAuthManager(
            self.store, "id", "secret",
            "https://studio.example.test/api/youtube/oauth/callback",
            self.key, transport,
        )
        auth = manager.start_authorization()
        state = parse_qs(urlparse(auth["authorization_url"]).query)["state"][0]
        with self.assertRaisesRegex(YouTubeOAuthError, "did not return a refresh token"):
            manager.exchange_code("code", state)

    def test_redirect_uri_must_be_https_and_encryption_key_is_required(self):
        insecure = YouTubeOAuthManager(
            self.store, "id", "secret", "http://localhost/callback", self.key
        )
        with self.assertRaisesRegex(YouTubeOAuthError, "absolute HTTPS"):
            insecure.start_authorization()
        no_key = YouTubeOAuthManager(
            self.store, "id", "secret",
            "https://studio.example.test/callback", None
        )
        with self.assertRaisesRegex(YouTubeOAuthError, "Fernet key"):
            no_key.start_authorization()

    def test_disconnect_clears_encrypted_token(self):
        auth = self.manager.start_authorization()
        state = parse_qs(urlparse(auth["authorization_url"]).query)["state"][0]
        self.manager.exchange_code("one-time-code", state)
        self.assertTrue(self.manager.status()["connected"])
        result = self.manager.disconnect()
        self.assertFalse(result["connected"])
        self.assertIsNone(self.store.token_record())


    def test_stored_token_missing_upload_scope_cannot_be_used(self):
        encrypted = self.manager.cipher.encrypt(b"restricted-refresh").decode("ascii")
        self.store.save_token(encrypted, REQUIRED_SCOPES[1], "Bearer")
        with self.assertRaisesRegex(YouTubeOAuthError, "missing required scopes"):
            self.manager.get_refresh_token()
        self.assertFalse(self.manager.status()["connected"])


    def _store_connected_token(self):
        encrypted = self.manager.cipher.encrypt(b"refresh-secret").decode("ascii")
        self.store.save_token(
            encrypted, " ".join((*REQUIRED_SCOPES, ANALYTICS_READ_SCOPE)), "Bearer"
        )



    def test_existing_oauth_token_table_migrates_verification_fields(self):
        legacy_db = os.path.join(self.tmp.name, "legacy-oauth.sqlite3")
        with sqlite3.connect(legacy_db) as connection:
            connection.execute("""
                CREATE TABLE youtube_oauth_tokens(
                  id INTEGER PRIMARY KEY CHECK(id=1),
                  refresh_token_encrypted TEXT NOT NULL,
                  scope TEXT NOT NULL,token_type TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                )
            """)
        migrated = YouTubeOAuthStore(legacy_db)
        encrypted = self.manager.cipher.encrypt(b"legacy-refresh").decode("ascii")
        migrated.save_token(encrypted, " ".join(REQUIRED_SCOPES), "Bearer")
        migrated.record_verification(
            "UC-MIGRATED", "Migrated Channel", True, False, "PermissionError"
        )
        record = migrated.token_record()
        self.assertEqual(record["channel_id"], "UC-MIGRATED")
        self.assertEqual(record["channel_title"], "Migrated Channel")
        self.assertTrue(record["data_api_verified"])
        self.assertFalse(record["analytics_api_verified"])
        self.assertEqual(record["last_error"], "PermissionError")

    def test_live_verifier_requires_encrypted_oauth_connection(self):
        verifier = YouTubeConnectionVerifier(
            self.manager,
            credentials_factory=FakeCredentials,
            service_factory=lambda *args, **kwargs: FakeYouTubeService(),
            request_factory=FakeRequest,
        )
        with self.assertRaisesRegex(YouTubeOAuthError, "encrypted OAuth"):
            verifier.verify()

    def test_live_verifier_checks_data_api_and_analytics_and_persists_channel(self):
        self._store_connected_token()
        youtube = FakeYouTubeService()
        analytics = FakeAnalyticsService()
        services = []
        def service_factory(name, version, **kwargs):
            services.append((name, version, kwargs))
            return youtube if name == "youtube" else analytics
        verifier = YouTubeConnectionVerifier(
            self.manager,
            credentials_factory=FakeCredentials,
            service_factory=service_factory,
            request_factory=FakeRequest,
            today=lambda: date(2026, 11, 16),
        )
        result = verifier.verify()
        self.assertTrue(result["data_api_verified"])
        self.assertTrue(result["analytics_api_verified"])
        self.assertTrue(result["live_connectivity_verified"])
        self.assertEqual(result["channel_id"], "UC123")
        self.assertEqual(result["channel_title"], "Test Channel")
        self.assertEqual(analytics.query_args["ids"], "channel==MINE")
        self.assertEqual(analytics.query_args["metrics"], "views")
        status = self.manager.status()
        self.assertTrue(status["data_api_verified"])
        self.assertTrue(status["analytics_api_verified"])
        self.assertEqual(status["channel_title"], "Test Channel")
        self.assertEqual(len(services), 2)

    def test_analytics_permission_failure_does_not_hide_data_api_success(self):
        self._store_connected_token()
        analytics = FakeAnalyticsService(PermissionError("scope denied"))
        verifier = YouTubeConnectionVerifier(
            self.manager,
            credentials_factory=FakeCredentials,
            service_factory=lambda name, version, **kwargs: (
                FakeYouTubeService() if name == "youtube" else analytics
            ),
            request_factory=FakeRequest,
            today=lambda: date(2026, 11, 16),
        )
        result = verifier.verify()
        self.assertTrue(result["data_api_verified"])
        self.assertFalse(result["analytics_api_verified"])
        self.assertFalse(result["live_connectivity_verified"])
        self.assertEqual(result["analytics_error"], "PermissionError")
        status = self.manager.status()
        self.assertTrue(status["data_api_verified"])
        self.assertFalse(status["analytics_api_verified"])
        self.assertEqual(status["last_error"], "PermissionError")

    def test_static_environment_refresh_token_is_fallback_only(self):
        old = os.environ.get("YOUTUBE_REFRESH_TOKEN")
        os.environ["YOUTUBE_REFRESH_TOKEN"] = "env-refresh"
        try:
            self.assertEqual(self.manager.get_refresh_token(), "env-refresh")
            self.assertEqual(self.manager.status()["mode"], "environment_refresh_token")
        finally:
            if old is None:
                os.environ.pop("YOUTUBE_REFRESH_TOKEN", None)
            else:
                os.environ["YOUTUBE_REFRESH_TOKEN"] = old


if __name__ == "__main__":
    unittest.main()
