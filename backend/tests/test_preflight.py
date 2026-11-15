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
        self.assertFalse(result["checks"]["tiktok_publish"]["configured"])
        self.assertFalse(result["capabilities"]["tiktok_private_publish_configured"])

    def test_tiktok_oauth_configuration_enables_preflight_without_static_token(self):
        env = {
            "TIKTOK_CLIENT_KEY": "client-key",
            "TIKTOK_CLIENT_SECRET": "client-secret",
            "TIKTOK_REDIRECT_URI": "https://example.test/api/tiktok/oauth/callback",
            "TIKTOK_TOKEN_ENCRYPTION_KEY": "fernet-key-placeholder",
        }
        result = build_preflight(env)
        self.assertTrue(result["checks"]["tiktok_oauth"]["configured"])
        self.assertTrue(result["checks"]["tiktok_publish"]["configured"])
        self.assertEqual(result["checks"]["tiktok_publish"]["mode"], "oauth")
        self.assertFalse(result["live_connectivity_verified"])

    def test_complete_environment_reports_configuration_not_live_success(self):
        env = {
            "NEXUS_REVIEW_TOKEN": "configured",
            "SCRIPT_PROVIDER_URL": "https://script.example.test/generate",
            "SCRIPT_PROVIDER_TOKEN": "configured",
            "VOICE_PROVIDER_URL": "https://voice.example.test/generate",
            "VOICE_PROVIDER_TOKEN": "configured",
            "RENDER_PROVIDER_URL": "https://render.example.test/generate",
            "RENDER_PROVIDER_TOKEN": "configured",
            "RENDER_ARTIFACT_HOSTS": "cdn.example.test",
            "YOUTUBE_CLIENT_ID": "configured",
            "YOUTUBE_CLIENT_SECRET": "configured",
            "YOUTUBE_REFRESH_TOKEN": "configured",
            "YOUTUBE_DATA_API_KEY": "configured",
            "TIKTOK_ACCESS_TOKEN": "configured",
        }
        result = build_preflight(env)
        self.assertTrue(result["capabilities"]["ai_generation_configured"])
        self.assertTrue(result["capabilities"]["artifact_staging_configured"])
        self.assertTrue(result["capabilities"]["youtube_upload_configured"])
        self.assertTrue(result["checks"]["tiktok_publish"]["configured"])
        self.assertTrue(result["capabilities"]["tiktok_private_publish_configured"])
        self.assertFalse(result["live_connectivity_verified"])

    def test_http_provider_url_is_not_reported_as_configured_and_value_is_not_exposed(self):
        env = {
            "SCRIPT_PROVIDER_URL": "http://private-or-insecure.example/api",
            "SCRIPT_PROVIDER_TOKEN": "top-secret-token",
            "VOICE_PROVIDER_URL": "https://voice.example.test/api",
            "VOICE_PROVIDER_TOKEN": "voice-token",
            "RENDER_PROVIDER_URL": "https://render.example.test/api",
            "RENDER_PROVIDER_TOKEN": "render-token",
        }
        result = build_preflight(env)
        self.assertFalse(result["checks"]["script_generation"]["configured"])
        self.assertIn("SCRIPT_PROVIDER_URL", result["checks"]["script_generation"]["invalid"])
        self.assertIn("SCRIPT_PROVIDER_URL", result["missing"])
        self.assertNotIn("private-or-insecure.example", str(result))
        self.assertNotIn("top-secret-token", str(result))
        self.assertFalse(result["capabilities"]["ai_generation_configured"])

    def test_invalid_optional_transcription_endpoint_is_reported_without_enabling_it(self):
        result = build_preflight({
            "TRANSCRIPTION_PROVIDER_URL": "http://transcription.example.test/api"
        })
        self.assertTrue(result["checks"]["transcription_provider"]["enabled"])
        self.assertFalse(result["checks"]["transcription_provider"]["configured"])
        self.assertIn("TRANSCRIPTION_PROVIDER_URL", result["missing"])
        self.assertFalse(result["live_connectivity_verified"])


if __name__ == "__main__":
    unittest.main()
