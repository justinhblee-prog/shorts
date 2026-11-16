import json
import os
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet
from youtube_oauth import (
    YouTubeOAuthStore, YouTubeOAuthManager, YouTubeOAuthError,
    REQUIRED_SCOPES, ANALYTICS_READ_SCOPE,
)


class GoogleOAuthTransport:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append((url, headers, body, timeout))
        status, payload = self.responses.pop(0)
        return status, json.dumps(payload).encode("utf-8")


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
