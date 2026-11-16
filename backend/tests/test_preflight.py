import os
import tempfile
import unittest

from preflight import build_preflight


class PreflightTests(unittest.TestCase):
    def test_empty_environment_fails_closed_without_exposing_secrets(self):
        result = build_preflight({})
        self.assertFalse(result["capabilities"]["end_to_end_configured"])
        self.assertFalse(result["checks"]["operator_auth"]["configured"])
        self.assertIn("NEXUS_REVIEW_TOKEN", result["missing"])
        self.assertNotIn("configured-value", str(result))
        self.assertFalse(result["live_connectivity_verified"])
        self.assertFalse(result["platforms"]["youtube"]["configuration_ready"])
        self.assertFalse(result["platforms"]["tiktok"]["configuration_ready"])

    def test_provider_bearer_tokens_are_optional(self):
        with tempfile.TemporaryDirectory() as media_dir:
            env = {
                "NEXUS_REVIEW_TOKEN": "operator-secret",
                "NEXUS_MEDIA_DIR": media_dir,
                "SCRIPT_PROVIDER_URL": "https://script.example.test",
                "VOICE_PROVIDER_URL": "https://voice.example.test",
                "RENDER_PROVIDER_URL": "https://render.example.test",
                "RENDER_ARTIFACT_HOSTS": "cdn.example.test",
                "YOUTUBE_CLIENT_ID": "youtube-client",
                "YOUTUBE_CLIENT_SECRET": "youtube-secret",
                "YOUTUBE_REFRESH_TOKEN": "youtube-refresh",
                "YOUTUBE_DATA_API_KEY": "youtube-data-key",
            }
            result = build_preflight(env)

        self.assertTrue(result["capabilities"]["ai_generation_configured"])
        self.assertTrue(result["capabilities"]["artifact_staging_configured"])
        self.assertTrue(result["capabilities"]["youtube_upload_configured"])
        self.assertTrue(result["platforms"]["youtube"]["configuration_ready"])
        self.assertFalse(result["platforms"]["youtube"]["live_connectivity_verified"])
        self.assertIn(
            "SCRIPT_PROVIDER_TOKEN",
            result["checks"]["script_generation"]["optional_missing"],
        )
        self.assertNotIn("SCRIPT_PROVIDER_TOKEN", result["missing"])
        for secret in ("operator-secret", "youtube-secret", "youtube-refresh"):
            self.assertNotIn(secret, str(result))

    def test_tiktok_oauth_configuration_is_reported_separately(self):
        with tempfile.TemporaryDirectory() as media_dir:
            env = {
                "NEXUS_REVIEW_TOKEN": "operator-secret",
                "NEXUS_MEDIA_DIR": media_dir,
                "SCRIPT_PROVIDER_URL": "https://script.example.test",
                "VOICE_PROVIDER_URL": "https://voice.example.test",
                "RENDER_PROVIDER_URL": "https://render.example.test",
                "RENDER_ARTIFACT_HOSTS": "cdn.example.test",
                "TIKTOK_CLIENT_KEY": "client-key",
                "TIKTOK_CLIENT_SECRET": "client-secret",
                "TIKTOK_REDIRECT_URI": "https://studio.example.test/api/tiktok/oauth/callback",
                "TIKTOK_TOKEN_ENCRYPTION_KEY": "fernet-key-placeholder",
            }
            result = build_preflight(env)

        self.assertTrue(result["capabilities"]["tiktok_oauth_configured"])
        self.assertTrue(result["capabilities"]["tiktok_publish_configured"])
        self.assertTrue(result["platforms"]["tiktok"]["configuration_ready"])
        self.assertTrue(result["platforms"]["tiktok"]["oauth_configured"])
        self.assertFalse(result["platforms"]["tiktok"]["metrics_configured"])
        self.assertFalse(result["platforms"]["tiktok"]["live_connectivity_verified"])

    def test_tiktok_static_token_is_explicit_fallback_not_oauth_readiness(self):
        result = build_preflight({"TIKTOK_ACCESS_TOKEN": "static-secret"})
        self.assertFalse(result["capabilities"]["tiktok_oauth_configured"])
        self.assertTrue(result["capabilities"]["tiktok_publish_configured"])
        self.assertTrue(result["platforms"]["tiktok"]["static_token_fallback"])
        self.assertFalse(result["platforms"]["tiktok"]["configuration_ready"])

    def test_static_tiktok_token_is_a_nonblocking_oauth_fallback(self):
        with tempfile.TemporaryDirectory() as media_dir:
            env = {
                "NEXUS_REVIEW_TOKEN": "operator-secret",
                "NEXUS_MEDIA_DIR": media_dir,
                "SCRIPT_PROVIDER_URL": "https://script.example.test",
                "VOICE_PROVIDER_URL": "https://voice.example.test",
                "RENDER_PROVIDER_URL": "https://render.example.test",
                "RENDER_ARTIFACT_HOSTS": "cdn.example.test",
                "TIKTOK_ACCESS_TOKEN": "static-secret",
            }
            result = build_preflight(env)

        self.assertTrue(result["platforms"]["tiktok"]["configuration_ready"])
        self.assertTrue(result["platforms"]["tiktok"]["static_token_fallback"])
        self.assertFalse(result["platforms"]["tiktok"]["oauth_configured"])
        self.assertIn(
            "TIKTOK_CLIENT_KEY",
            result["checks"]["tiktok_oauth"]["optional_missing"],
        )
        self.assertNotIn("TIKTOK_CLIENT_KEY", result["missing"])
        self.assertNotIn("static-secret", str(result))



    def test_youtube_oauth_redirect_and_encryption_are_optional_preflight_settings(self):
        result = build_preflight({})
        self.assertFalse(result["checks"]["youtube_oauth"]["configured"])
        self.assertTrue(result["checks"]["youtube_oauth"]["optional"])
        self.assertIn(
            "YOUTUBE_REDIRECT_URI",
            result["checks"]["youtube_oauth"]["optional_missing"],
        )
        self.assertNotIn("YOUTUBE_REDIRECT_URI", result["missing"])
        self.assertNotIn("YOUTUBE_TOKEN_ENCRYPTION_KEY", result["missing"])

    def test_encrypted_youtube_oauth_token_satisfies_refresh_token_preflight(self):
        env = {
            "NEXUS_REVIEW_TOKEN": "operator-secret",
            "YOUTUBE_CLIENT_ID": "client-id",
            "YOUTUBE_CLIENT_SECRET": "client-secret",
            "YOUTUBE_DATA_API_KEY": "data-api-key",
        }
        result = build_preflight(env, youtube_refresh_token_configured=True)
        self.assertTrue(result["checks"]["youtube_upload"]["configured"])
        self.assertNotIn("YOUTUBE_REFRESH_TOKEN", result["missing"])
        self.assertTrue(result["capabilities"]["youtube_upload_configured"])

    def test_complete_environment_reports_configuration_not_live_success(self):
        with tempfile.TemporaryDirectory() as media_dir:
            env = {
                key: "configured"
                for key in [
                    "NEXUS_REVIEW_TOKEN",
                    "SCRIPT_PROVIDER_URL",
                    "VOICE_PROVIDER_URL",
                    "RENDER_PROVIDER_URL",
                    "RENDER_ARTIFACT_HOSTS",
                    "YOUTUBE_CLIENT_ID",
                    "YOUTUBE_CLIENT_SECRET",
                    "YOUTUBE_REFRESH_TOKEN",
                    "YOUTUBE_DATA_API_KEY",
                    "TIKTOK_CLIENT_KEY",
                    "TIKTOK_CLIENT_SECRET",
                    "TIKTOK_REDIRECT_URI",
                    "TIKTOK_TOKEN_ENCRYPTION_KEY",
                ]
            }
            env["NEXUS_MEDIA_DIR"] = media_dir
            result = build_preflight(env)

        self.assertTrue(result["capabilities"]["ai_generation_configured"])
        self.assertTrue(result["capabilities"]["artifact_staging_configured"])
        self.assertTrue(result["capabilities"]["youtube_upload_configured"])
        self.assertTrue(result["capabilities"]["tiktok_publish_configured"])
        self.assertTrue(result["capabilities"]["end_to_end_configured"])
        self.assertFalse(result["live_connectivity_verified"])


if __name__ == "__main__":
    unittest.main()
