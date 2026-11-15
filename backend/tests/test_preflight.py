import unittest
from preflight import build_preflight

class PreflightTests(unittest.TestCase):
    def test_empty_environment_fails_closed_without_exposing_secrets(self):
        result=build_preflight({})
        self.assertFalse(result["capabilities"]["end_to_end_configured"])
        self.assertFalse(result["checks"]["operator_auth"]["configured"])
        self.assertIn("NEXUS_REVIEW_TOKEN",result["missing"])
        self.assertNotIn("secret",str(result).lower())
        self.assertFalse(result["live_connectivity_verified"])
    def test_complete_environment_reports_configuration_not_live_success(self):
        env={k:"configured" for k in [
            "NEXUS_REVIEW_TOKEN","SCRIPT_PROVIDER_URL","SCRIPT_PROVIDER_TOKEN",
            "VOICE_PROVIDER_URL","VOICE_PROVIDER_TOKEN","RENDER_PROVIDER_URL",
            "RENDER_PROVIDER_TOKEN","RENDER_ARTIFACT_HOSTS","YOUTUBE_CLIENT_ID",
            "YOUTUBE_CLIENT_SECRET","YOUTUBE_REFRESH_TOKEN","YOUTUBE_DATA_API_KEY"]}
        result=build_preflight(env)
        self.assertTrue(result["capabilities"]["ai_generation_configured"])
        self.assertTrue(result["capabilities"]["artifact_staging_configured"])
        self.assertTrue(result["capabilities"]["youtube_upload_configured"])
        self.assertFalse(result["live_connectivity_verified"])
if __name__=="__main__":unittest.main()
