import unittest
from preflight import build_preflight

class PreflightTests(unittest.TestCase):
    def test_empty_environment_fails_closed_without_exposing_secrets(self):
        result=build_preflight({})
        self.assertFalse(result["capabilities"]["end_to_end_configured"])
        self.assertFalse(result["checks"]["operator_auth"]["configured"])
        self.assertIn("NEXUS_REVIEW_TOKEN",result["missing"])
        self.assertNotIn("configured-value",str(result))
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
        env={k:"configured" for k in [
            "NEXUS_REVIEW_TOKEN","SCRIPT_PROVIDER_URL","SCRIPT_PROVIDER_TOKEN",
            "VOICE_PROVIDER_URL","VOICE_PROVIDER_TOKEN","RENDER_PROVIDER_URL",
            "RENDER_PROVIDER_TOKEN","RENDER_ARTIFACT_HOSTS","YOUTUBE_CLIENT_ID",
            "YOUTUBE_CLIENT_SECRET","YOUTUBE_REFRESH_TOKEN","YOUTUBE_DATA_API_KEY",
            "TIKTOK_ACCESS_TOKEN"]}
        result=build_preflight(env)
        self.assertTrue(result["capabilities"]["ai_generation_configured"])
        self.assertTrue(result["capabilities"]["artifact_staging_configured"])
        self.assertTrue(result["capabilities"]["youtube_upload_configured"])
        self.assertTrue(result["checks"]["tiktok_publish"]["configured"])
        self.assertTrue(result["capabilities"]["tiktok_private_publish_configured"])
        self.assertFalse(result["live_connectivity_verified"])
if __name__=="__main__":unittest.main()
