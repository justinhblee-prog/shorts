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
        self.assertFalse(result["live_provider_calls_verified"])

    def test_complete_environment_reports_configuration_not_live_success(self):
        env = {
            "NEXUS_REVIEW_TOKEN": "secret-value",
            "SCRIPT_PROVIDER_URL": "https://script.example/api",
            "SCRIPT_PROVIDER_TOKEN": "script-secret",
            "VOICE_PROVIDER_URL": "https://voice.example/api",
            "VOICE_PROVIDER_TOKEN": "voice-secret",
            "RENDER_PROVIDER_URL": "https://render.example/api",
            "RENDER_PROVIDER_TOKEN": "render-secret",
            "RENDER_ARTIFACT_HOSTS": "cdn.example",
            "YOUTUBE_CLIENT_ID": "client-id",
            "YOUTUBE_CLIENT_SECRET": "client-secret",
            "YOUTUBE_REFRESH_TOKEN": "refresh-secret",
            "YOUTUBE_DATA_API_KEY": "data-api-secret",
        }
        result = build_preflight(env)
        self.assertTrue(result["capabilities"]["ai_generation_configured"])
        self.assertTrue(result["capabilities"]["artifact_staging_configured"])
        self.assertTrue(result["capabilities"]["youtube_upload_configured"])
        self.assertFalse(result["live_connectivity_verified"])
        self.assertFalse(result["live_provider_calls_verified"])
        self.assertTrue(result["providers"]["script_generation"]["credential_present"])
        self.assertEqual(result["providers"]["script_generation"]["endpoint_host"], "script.example")
        self.assertEqual(result["providers"]["script_generation"]["integration_mode"], "generic_json_http")
        self.assertFalse(result["providers"]["script_generation"]["live_call_verified"])
        self.assertNotIn("script-secret", str(result))
        self.assertNotIn("client-secret", str(result))

    def test_invalid_or_insecure_remote_provider_urls_are_not_ready(self):
        env = {
            "SCRIPT_PROVIDER_URL": "http://provider.example/generate",
            "SCRIPT_PROVIDER_TOKEN": "secret",
            "VOICE_PROVIDER_URL": "not-a-url",
            "VOICE_PROVIDER_TOKEN": "secret",
            "RENDER_PROVIDER_URL": "https://user:pass@render.example/api",
            "RENDER_PROVIDER_TOKEN": "secret",
        }
        result = build_preflight(env)
        self.assertFalse(result["capabilities"]["ai_generation_configured"])
        self.assertFalse(result["providers"]["script_generation"]["endpoint_valid"])
        self.assertFalse(result["providers"]["voice_generation"]["configured"])
        self.assertFalse(result["providers"]["video_rendering"]["endpoint_valid"])

    def test_localhost_http_is_allowed_for_development(self):
        env = {
            "SCRIPT_PROVIDER_URL": "http://127.0.0.1:9000/script",
            "SCRIPT_PROVIDER_TOKEN": "local",
        }
        result = build_preflight(env)
        self.assertTrue(result["providers"]["script_generation"]["configured"])


if __name__ == "__main__":
    unittest.main()
