import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
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

    def test_oauth_callback_started_before_disconnect_cannot_restore_connection(self):
        auth = self.manager.start_authorization()
        state = parse_qs(urlparse(auth["authorization_url"]).query)["state"][0]
        expected_epoch = self.store.consume_state(
            hashlib.sha256(state.encode()).hexdigest()
        )
        self.assertEqual(expected_epoch, 0)
        self.manager._save_token_response({
            "access_token": "access-before-disconnect",
            "refresh_token": "refresh-before-disconnect",
            "open_id": "creator-123",
            "scope": "video.publish",
            "token_type": "Bearer",
            "expires_in": 7200,
            "refresh_expires_in": 15552000,
        })
        operation = "disconnect-epoch-test"
        row = self.store.token_record()
        self.assertTrue(self.store.begin_disconnect(
            operation, row["access_token_encrypted"]
        ))
        self.assertTrue(self.store.finish_disconnect(operation, success=True))
        with self.assertRaisesRegex(TikTokOAuthError, "authorization became stale"):
            self.manager._save_token_response({
                "access_token": "late-callback-access",
                "refresh_token": "late-callback-refresh",
                "open_id": "creator-456",
                "scope": "video.publish",
                "token_type": "Bearer",
                "expires_in": 7200,
                "refresh_expires_in": 15552000,
            }, expected_epoch=expected_epoch)
        self.assertIsNone(self.store.token_record())

    def test_new_oauth_state_uses_incremented_connection_epoch(self):
        self.manager._save_token_response({
            "access_token": "access-old",
            "refresh_token": "refresh-old",
            "open_id": "creator-123",
            "scope": "video.publish",
            "token_type": "Bearer",
            "expires_in": 7200,
            "refresh_expires_in": 15552000,
        })
        operation = "disconnect-epoch-increment"
        row = self.store.token_record()
        self.assertTrue(self.store.begin_disconnect(
            operation, row["access_token_encrypted"]
        ))
        self.assertTrue(self.store.finish_disconnect(operation, success=True))
        auth = self.manager.start_authorization()
        state = parse_qs(urlparse(auth["authorization_url"]).query)["state"][0]
        epoch = self.store.consume_state(
            __import__("hashlib").sha256(state.encode()).hexdigest()
        )
        self.assertEqual(epoch, 1)

    def test_disconnect_lease_fences_token_write_and_preserves_tokens_on_failure(self):
        self.manager._save_token_response({
            "access_token": "access-original",
            "refresh_token": "refresh-original",
            "open_id": "creator-123",
            "scope": "video.publish",
            "token_type": "Bearer",
            "expires_in": 7200,
            "refresh_expires_in": 15552000,
        })
        original = self.store.token_record()
        operation = "disconnect-test"
        self.assertTrue(self.store.begin_disconnect(
            operation, original["access_token_encrypted"]
        ))
        with self.assertRaisesRegex(TikTokOAuthError, "concurrent token operation"):
            self.manager._save_token_response({
                "access_token": "access-new",
                "refresh_token": "refresh-new",
                "open_id": "creator-456",
                "scope": "video.publish",
                "token_type": "Bearer",
                "expires_in": 7200,
                "refresh_expires_in": 15552000,
            })
        self.assertTrue(self.store.finish_disconnect(operation, success=False))
        self.assertEqual(
            self.store.token_record()["access_token_encrypted"],
            original["access_token_encrypted"],
        )
        self.manager._save_token_response({
            "access_token": "access-new",
            "refresh_token": "refresh-new",
            "open_id": "creator-456",
            "scope": "video.publish",
            "token_type": "Bearer",
            "expires_in": 7200,
            "refresh_expires_in": 15552000,
        })
        self.assertEqual(self.store.token_record()["open_id"], "creator-456")

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

    def test_refresh_response_cannot_overwrite_tokens_after_lease_is_replaced(self):
        self.manager._save_token_response({
            "access_token": "access-old",
            "refresh_token": "refresh-old",
            "open_id": "creator-123",
            "scope": "user.info.basic,video.publish,video.list",
            "token_type": "Bearer",
            "expires_in": 7200,
            "refresh_expires_in": 15552000,
        })
        lease_a = self.store.acquire_refresh_lease(self.manager._owner_id, 60)
        self.assertIsNotNone(lease_a)
        with self.store.db() as connection:
            connection.execute(
                "UPDATE tiktok_oauth_refresh_lease SET expires_at=? WHERE id=1",
                ("2000-01-01T00:00:00+00:00",),
            )
        lease_b = self.store.acquire_refresh_lease("process-b", 60)
        self.assertIsNotNone(lease_b)
        before = self.store.token_record()
        with self.assertRaisesRegex(TikTokOAuthError, "lease was lost"):
            self.manager._save_token_response({
                "access_token": "stale-access",
                "refresh_token": "stale-rotated-refresh",
                "open_id": "creator-123",
                "scope": "user.info.basic,video.publish,video.list",
                "token_type": "Bearer",
                "expires_in": 7200,
                "refresh_expires_in": 15552000,
            }, refresh_lease=(self.manager._owner_id, lease_a))
        after = self.store.token_record()
        self.assertEqual(after["access_token_encrypted"], before["access_token_encrypted"])
        self.assertEqual(after["refresh_token_encrypted"], before["refresh_token_encrypted"])
        self.assertTrue(self.store.release_refresh_lease("process-b", lease_b))

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
