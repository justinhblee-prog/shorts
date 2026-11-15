import os
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from unittest import mock

from cryptography.fernet import Fernet

from tiktok_publishing import TikTokOAuthStore, TikTokOAuthError


class FakeOAuthResponse:
    status_code = 200

    def __init__(self, body):
        self.body = body

    def json(self):
        return self.body


class FakeOAuthSession:
    def __init__(self):
        self.posts = []
        self.responses = []

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return self.responses.pop(0)


class TikTokOAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.temp.name) / "oauth.sqlite3")
        self.session = FakeOAuthSession()
        self.env = mock.patch.dict(os.environ, {
            "TIKTOK_CLIENT_KEY": "test-client",
            "TIKTOK_CLIENT_SECRET": "test-secret",
            "TIKTOK_REDIRECT_URI": "https://nexus.example/api/tiktok/oauth/callback",
            "TIKTOK_TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode("ascii"),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.store = TikTokOAuthStore(self.db, session=self.session)

    def tearDown(self):
        self.temp.cleanup()

    def test_authorization_uses_scoped_state_and_callback_uri(self):
        result = self.store.create_authorization("operator-1")
        query = parse_qs(urlparse(result["authorization_url"]).query)
        self.assertEqual(query["client_key"], ["test-client"])
        self.assertEqual(query["scope"], ["user.info.basic,video.publish"])
        self.assertEqual(query["redirect_uri"], ["https://nexus.example/api/tiktok/oauth/callback"])
        self.assertEqual(len(query["state"][0]), 43)
        self.assertEqual(result["state_expires_in_seconds"], 600)

    def test_connect_consumes_state_and_encrypts_tokens_at_rest(self):
        auth = self.store.create_authorization("operator-1")
        state = parse_qs(urlparse(auth["authorization_url"]).query)["state"][0]
        self.session.responses.append(FakeOAuthResponse({"data": {
            "access_token": "plain-access-secret",
            "refresh_token": "plain-refresh-secret",
            "open_id": "creator-123",
            "display_name": "Creator",
            "scope": "user.info.basic,video.publish",
            "expires_in": 86400,
            "refresh_expires_in": 2592000,
        }, "error": {"code": "ok"}}))
        result = self.store.connect("one-time-code", state)
        self.assertTrue(result["connected"])
        self.assertEqual(result["open_id"], "creator-123")
        self.assertIn("video.publish", result["scopes"])
        with self.store.db() as connection:
            row = connection.execute("SELECT * FROM tiktok_oauth_tokens").fetchone()
        self.assertNotIn("plain-access-secret", row["access_token_cipher"])
        self.assertNotIn("plain-refresh-secret", row["refresh_token_cipher"])
        self.assertEqual(self.store.get_access_token(), "plain-access-secret")
        with self.assertRaises(TikTokOAuthError):
            self.store.connect("replay-code", state)

    def test_connect_rejects_missing_publish_scope_and_does_not_store_tokens(self):
        auth = self.store.create_authorization("operator-1")
        state = parse_qs(urlparse(auth["authorization_url"]).query)["state"][0]
        self.session.responses.append(FakeOAuthResponse({"data": {
            "access_token": "access", "refresh_token": "refresh",
            "open_id": "creator-123", "scope": "user.info.basic",
            "expires_in": 3600, "refresh_expires_in": 86400,
        }, "error": {"code": "ok"}}))
        with self.assertRaisesRegex(TikTokOAuthError, "video.publish"):
            self.store.connect("code", state)
        self.assertFalse(self.store.status()["connected"])

    def test_token_request_handles_current_string_error_schema(self):
        self.session.responses.append(FakeOAuthResponse({
            "error": "invalid_grant",
            "error_description": "Authorization code is invalid",
            "log_id": "oauth-log-123",
        }))
        with self.assertRaisesRegex(TikTokOAuthError, "invalid_grant.*Authorization code is invalid"):
            self.store._token_request({"code": "bad-code", "grant_type": "authorization_code"})

    def test_token_request_accepts_legacy_nested_error_schema(self):
        self.session.responses.append(FakeOAuthResponse({
            "error": {"code": "invalid_grant", "message": "expired"}
        }))
        with self.assertRaisesRegex(TikTokOAuthError, "invalid_grant.*expired"):
            self.store._token_request({"code": "expired-code", "grant_type": "authorization_code"})

    def test_access_token_fails_closed_when_creator_is_not_connected(self):
        with mock.patch.dict(os.environ, {"TIKTOK_ACCESS_TOKEN": ""}):
            with self.assertRaisesRegex(TikTokOAuthError, "not connected"):
                self.store.get_access_token()


if __name__ == "__main__":
    unittest.main()
