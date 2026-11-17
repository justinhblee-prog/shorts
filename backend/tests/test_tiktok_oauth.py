import json
import os
import tempfile
import unittest
import threading
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet
from tiktok_oauth import TikTokOAuthStore, TikTokOAuthManager, TikTokOAuthError


class OAuthTransport:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append((url, headers, body, timeout))
        status, payload = self.responses.pop(0)
        return status, json.dumps(payload).encode("utf-8")


class TikTokOAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "oauth.sqlite3")
        self.store = TikTokOAuthStore(self.db)
        self.key = Fernet.generate_key()
        self.transport = OAuthTransport([(
            200, {
                "access_token": "access-secret-1",
                "refresh_token": "refresh-secret-1",
                "open_id": "creator-123",
                "scope": "user.info.basic,video.publish,video.list",
                "token_type": "Bearer",
                "expires_in": 7200,
                "refresh_expires_in": 15552000,
            }
        )])
        self.manager = TikTokOAuthManager(
            self.store, "client-key", "client-secret",
            "https://example.test/api/tiktok/oauth/callback",
            self.key, self.transport,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_oauth_state_and_refresh_lease_clocks_wait_for_write_lock(self):
        decision = datetime(2036, 7, 8, 9, 10, 18, tzinfo=timezone.utc)

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
                with patch("tiktok_oauth._now", side_effect=controlled_now):
                    thread = threading.Thread(target=run)
                    thread.start()
                    self.assertTrue(started.wait(1))
                    self.assertFalse(clock_called.wait(0.1), expected_message)
                    holder.commit()
                    thread.join(2)
                self.assertFalse(thread.is_alive(), "TikTok OAuth transition did not finish")
            self.assertNotIn("error", outcome)
            return outcome.get("result")

        state_hash = "state-hash-lock-clock"
        assert_clock_waits(
            lambda: self.store.create_state(state_hash, 600),
            "TikTok OAuth state creation clock sampled before write lock",
        )
        with self.store.db() as connection:
            created = connection.execute(
                "SELECT created_at,expires_at FROM tiktok_oauth_states WHERE state_hash=?",
                (state_hash,),
            ).fetchone()
        self.assertEqual(created["created_at"], decision.isoformat())
        self.assertEqual(
            created["expires_at"],
            (decision + timedelta(seconds=600)).isoformat(),
        )

        assert_clock_waits(
            lambda: self.store.consume_state(state_hash),
            "TikTok OAuth state consumption clock sampled before write lock",
        )
        with self.store.db() as connection:
            consumed = connection.execute(
                "SELECT used_at FROM tiktok_oauth_states WHERE state_hash=?",
                (state_hash,),
            ).fetchone()
        self.assertEqual(consumed["used_at"], decision.isoformat())

        assert_clock_waits(
            lambda: self.store.acquire_refresh_lease("refresh-worker", 60),
            "TikTok refresh lease clock sampled before write lock",
        )
        with self.store.db() as connection:
            lease = connection.execute(
                "SELECT expires_at FROM tiktok_oauth_refresh_lease WHERE id=1"
            ).fetchone()
        self.assertEqual(
            lease["expires_at"],
            (decision + timedelta(seconds=60)).isoformat(),
        )

    def test_authorization_state_is_random_hashed_and_one_time(self):
        result = self.manager.start_authorization()
        query = parse_qs(urlparse(result["authorization_url"]).query)
        state = query["state"][0]
        self.assertEqual(query["client_key"], ["client-key"])
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["scope"], ["user.info.basic,video.publish,video.list"])
        self.assertEqual(result["expires_in"], 600)
        with self.store.db() as connection:
            row = connection.execute("SELECT * FROM tiktok_oauth_states").fetchone()
        self.assertNotEqual(row["state_hash"], state)
        self.manager.exchange_code("one-time-code", state)
        with self.assertRaisesRegex(TikTokOAuthError, "invalid, expired or already used"):
            self.manager.exchange_code("one-time-code", state)

    def test_tokens_are_encrypted_and_status_exposes_no_secret_values(self):
        auth = self.manager.start_authorization()
        state = parse_qs(urlparse(auth["authorization_url"]).query)["state"][0]
        result = self.manager.exchange_code("one-time-code", state)
        self.assertTrue(result["connected"])
        row = self.store.token_record()
        self.assertNotIn("access-secret-1", row["access_token_encrypted"])
        self.assertNotIn("refresh-secret-1", row["refresh_token_encrypted"])
        status = self.manager.status()
        self.assertEqual(status["open_id"], "creator-123")
        self.assertNotIn("access_token", status)
        self.assertNotIn("refresh_token", status)
        self.assertEqual(self.manager.get_access_token(), "access-secret-1")
        self.assertEqual(self.manager.get_access_token(required_scope="video.list"), "access-secret-1")

    def test_refresh_rotates_and_persists_the_new_refresh_token(self):
        self.manager._save_token_response({
            "access_token": "access-old",
            "refresh_token": "refresh-old",
            "open_id": "creator-123",
            "scope": "user.info.basic,video.publish,video.list",
            "token_type": "Bearer",
            "expires_in": 7200,
            "refresh_expires_in": 15552000,
        })
        with self.store.db() as connection:
            connection.execute(
                "UPDATE tiktok_oauth_tokens SET access_expires_at=? WHERE id=1",
                ((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),),
            )
        self.transport.responses.clear()
        self.transport.responses.append((200, {
            "access_token": "access-new",
            "refresh_token": "refresh-new",
            "open_id": "creator-123",
            "scope": "user.info.basic,video.publish,video.list",
            "token_type": "Bearer",
            "expires_in": 7200,
            "refresh_expires_in": 15552000,
        }))
        self.assertEqual(self.manager.get_access_token(), "access-new")
        row = self.store.token_record()
        cipher = Fernet(self.key)
        self.assertEqual(cipher.decrypt(row["refresh_token_encrypted"].encode()).decode(),
                         "refresh-new")
        self.assertEqual(cipher.decrypt(row["access_token_encrypted"].encode()).decode(),
                         "access-new")
        self.assertEqual(self.transport.calls[-1][0],
                         "https://open.tiktokapis.com/v2/oauth/token/")

    def test_connection_status_requires_encryption_key_and_client_credentials(self):
        self.manager._save_token_response({
            "access_token": "access-secret",
            "refresh_token": "refresh-secret",
            "open_id": "creator-123",
            "scope": "video.publish",
            "token_type": "Bearer",
            "expires_in": 7200,
            "refresh_expires_in": 15552000,
        })
        missing_key = TikTokOAuthManager(
            self.store, "client-key", "client-secret",
            "https://example.test/callback", None, self.transport
        )
        self.assertFalse(missing_key.status()["connected"])
        missing_client = TikTokOAuthManager(
            self.store, None, None,
            "https://example.test/callback", self.key, self.transport
        )
        self.assertFalse(missing_client.status()["connected"])

    def test_disconnect_revokes_remote_token_then_clears_encrypted_storage(self):
        self.manager._save_token_response({
            "access_token": "access-to-revoke",
            "refresh_token": "refresh-to-revoke",
            "open_id": "creator-123",
            "scope": "video.publish",
            "token_type": "Bearer",
            "expires_in": 7200,
            "refresh_expires_in": 15552000,
        })
        self.transport.responses.clear()
        self.transport.responses.append((200, {}))
        result = self.manager.disconnect()
        self.assertFalse(result["connected"])
        self.assertIsNone(self.store.token_record())
        self.assertEqual(self.transport.calls[-1][0],
                         "https://open.tiktokapis.com/v2/oauth/revoke/")
        body = parse_qs(self.transport.calls[-1][2].decode("utf-8"))
        self.assertEqual(body["token"], ["access-to-revoke"])
        self.assertEqual(body["client_secret"], ["client-secret"])

    def test_failed_remote_revoke_keeps_local_tokens(self):
        self.manager._save_token_response({
            "access_token": "access-still-connected",
            "refresh_token": "refresh-still-connected",
            "open_id": "creator-123",
            "scope": "video.publish",
            "token_type": "Bearer",
            "expires_in": 7200,
            "refresh_expires_in": 15552000,
        })
        self.transport.responses.clear()
        self.transport.responses.append((400, {"error": "invalid_request"}))
        with self.assertRaisesRegex(TikTokOAuthError, "revocation failed"):
            self.manager.disconnect()
        self.assertIsNotNone(self.store.token_record())

    def test_invalid_encryption_key_fails_closed_without_crashing_manager_creation(self):
        self.manager._save_token_response({
            "access_token": "access-secret",
            "refresh_token": "refresh-secret",
            "open_id": "creator-123",
            "scope": "video.publish",
            "token_type": "Bearer",
            "expires_in": 7200,
            "refresh_expires_in": 15552000,
        })
        manager = TikTokOAuthManager(
            self.store, "client-key", "client-secret",
            "https://example.test/callback", "not-a-fernet-key", self.transport
        )
        self.assertFalse(manager.status()["connected"])
        self.assertEqual(manager.status()["status"], "encryption_key_invalid")

    def test_account_without_video_publish_scope_cannot_publish(self):
        self.manager._save_token_response({
            "access_token": "access-no-publish",
            "refresh_token": "refresh-no-publish",
            "open_id": "creator-123",
            "scope": "user.info.basic",
            "token_type": "Bearer",
            "expires_in": 7200,
            "refresh_expires_in": 15552000,
        })
        self.assertFalse(self.manager.status()["connected"])
        self.assertEqual(self.manager.status()["status"], "required_scope_missing")
        with self.assertRaisesRegex(TikTokOAuthError, "video.publish scope"):
            self.manager.get_access_token()

    def test_video_list_scope_is_required_only_for_metrics_access(self):
        self.manager._save_token_response({
            "access_token": "publish-only", "refresh_token": "refresh-only",
            "open_id": "creator-123", "scope": "user.info.basic,video.publish",
            "token_type": "Bearer", "expires_in": 7200,
            "refresh_expires_in": 15552000,
        })
        self.assertEqual(self.manager.get_access_token(), "publish-only")
        with self.assertRaisesRegex(TikTokOAuthError, "video.list scope"):
            self.manager.get_access_token(required_scope="video.list")

    def test_refresh_lease_fences_concurrent_processes(self):
        first = self.store.acquire_refresh_lease("process-a", 60)
        second = self.store.acquire_refresh_lease("process-b", 60)
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertTrue(self.store.release_refresh_lease("process-a", first))
        third = self.store.acquire_refresh_lease("process-b", 60)
        self.assertIsNotNone(third)

    def test_expired_or_unknown_state_is_rejected(self):
        with self.assertRaisesRegex(TikTokOAuthError, "invalid, expired or already used"):
            self.store.consume_state("missing-state-hash")

    def test_redirect_uri_must_be_static_https(self):
        manager = TikTokOAuthManager(
            self.store, "client-key", "client-secret",
            "http://example.test/callback?x=1", self.key, self.transport,
        )
        with self.assertRaisesRegex(TikTokOAuthError, "absolute HTTPS"):
            manager.start_authorization()


if __name__ == "__main__":
    unittest.main()
