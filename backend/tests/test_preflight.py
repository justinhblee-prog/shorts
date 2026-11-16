import base64
import os
import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest

from preflight import build_preflight


class PreflightTests(unittest.TestCase):
    def test_backup_encryption_is_optional_but_reported_when_not_required(self):
        result = build_preflight({})
        self.assertFalse(result["checks"]["backup_encryption"]["configured"])
        self.assertTrue(result["checks"]["backup_encryption"]["optional"])
        self.assertIn(
            "NEXUS_BACKUP_ENCRYPTION_KEY",
            result["checks"]["backup_encryption"]["optional_missing"],
        )
        self.assertNotIn("NEXUS_BACKUP_ENCRYPTION_KEY", result["missing"])

    def test_backup_encryption_required_without_key_blocks_preflight(self):
        result = build_preflight({"NEXUS_BACKUP_ENCRYPTION_REQUIRED": "true"})
        self.assertFalse(result["checks"]["backup_encryption"]["configured"])
        self.assertFalse(result["checks"]["backup_encryption"]["optional"])
        self.assertIn("NEXUS_BACKUP_ENCRYPTION_KEY", result["missing"])

    def test_backup_encryption_accepts_only_urlsafe_base64_32_byte_key(self):
        key = base64.urlsafe_b64encode(b"x" * 32).decode("ascii")
        result = build_preflight({
            "NEXUS_BACKUP_ENCRYPTION_KEY": key,
            "NEXUS_BACKUP_ENCRYPTION_REQUIRED": "true",
        })
        self.assertTrue(result["checks"]["backup_encryption"]["configured"])
        self.assertNotIn("NEXUS_BACKUP_ENCRYPTION_KEY", result["missing"])
        invalid = build_preflight({
            "NEXUS_BACKUP_ENCRYPTION_KEY": "short-invalid-key",
        })
        self.assertIn(
            "NEXUS_BACKUP_ENCRYPTION_KEY (must be URL-safe base64 for 32 bytes)",
            invalid["missing"],
        )

    def test_media_malware_scan_is_optional_when_disabled(self):
        result = build_preflight({})
        self.assertFalse(result["checks"]["media_malware_scan"]["configured"])
        self.assertTrue(result["checks"]["media_malware_scan"]["optional"])
        self.assertNotIn("ClamAV", str(result["missing"]))

    def test_enabled_media_scan_requires_executable_signatures_and_valid_timeout(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_dir = Path(temp_dir) / "signatures"
            database_dir.mkdir()
            (database_dir / "main.cvd").write_bytes(b"signature-db")
            with patch("preflight.shutil.which", return_value="/usr/bin/clamscan"):
                ready = build_preflight({
                    "NEXUS_MEDIA_SCAN_ENABLED": "true",
                    "NEXUS_CLAMSCAN_PATH": "/usr/bin/clamscan",
                    "NEXUS_CLAMAV_DATABASE_DIR": str(database_dir),
                    "NEXUS_MEDIA_SCAN_TIMEOUT_SECONDS": "90",
                })
                invalid_timeout = build_preflight({
                    "NEXUS_MEDIA_SCAN_ENABLED": "true",
                    "NEXUS_CLAMSCAN_PATH": "/usr/bin/clamscan",
                    "NEXUS_CLAMAV_DATABASE_DIR": str(database_dir),
                    "NEXUS_MEDIA_SCAN_TIMEOUT_SECONDS": "0",
                })
            self.assertTrue(ready["checks"]["media_malware_scan"]["configured"])
            self.assertEqual(ready["checks"]["media_malware_scan"]["missing"], [])
            self.assertIn(
                "NEXUS_MEDIA_SCAN_TIMEOUT_SECONDS (must be a positive integer)",
                invalid_timeout["missing"],
            )

    def test_invalid_media_scan_toggle_fails_closed_in_preflight(self):
        result = build_preflight({"NEXUS_MEDIA_SCAN_ENABLED": "treu"})
        self.assertFalse(result["checks"]["media_malware_scan"]["configured"])
        self.assertIn(
            "NEXUS_MEDIA_SCAN_ENABLED (must be true or false)",
            result["missing"],
        )

    def test_enabled_media_scan_rejects_size_limits_above_clamav_capacity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_dir = Path(temp_dir) / "signatures"
            database_dir.mkdir()
            (database_dir / "main.cvd").write_bytes(b"signature-db")
            with patch("preflight.shutil.which", return_value="/usr/bin/clamscan"):
                result = build_preflight({
                    "NEXUS_MEDIA_SCAN_ENABLED": "true",
                    "NEXUS_CLAMSCAN_PATH": "/usr/bin/clamscan",
                    "NEXUS_CLAMAV_DATABASE_DIR": str(database_dir),
                    "NEXUS_MAX_MEDIA_BYTES": str(3 * 1024 * 1024 * 1024),
                })
        self.assertIn(
            "NEXUS_MAX_MEDIA_BYTES (ClamAV supports up to 2 GiB)",
            result["missing"],
        )

    def test_enabled_media_scan_fails_preflight_without_signatures(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("preflight.shutil.which", return_value="/usr/bin/clamscan"):
                result = build_preflight({
                    "NEXUS_MEDIA_SCAN_ENABLED": "true",
                    "NEXUS_CLAMSCAN_PATH": "/usr/bin/clamscan",
                    "NEXUS_CLAMAV_DATABASE_DIR": temp_dir,
                })
        self.assertFalse(result["checks"]["media_malware_scan"]["configured"])
        self.assertTrue(any("signature database" in item for item in result["missing"]))

    def test_provider_endpoints_require_https_and_reject_embedded_credentials(self):
        result = build_preflight({
            "SCRIPT_PROVIDER_URL": "http://script.example.test/generate",
            "VOICE_PROVIDER_URL": "https://user:password@voice.example.test/generate",
            "RENDER_PROVIDER_URL": "https://render.example.test/generate",
        })
        self.assertFalse(result["checks"]["script_generation"]["configured"])
        self.assertIn(
            "SCRIPT_PROVIDER_URL (provider URL must use HTTPS)",
            result["checks"]["script_generation"]["missing"],
        )
        self.assertFalse(result["checks"]["voice_generation"]["configured"])
        self.assertIn(
            "VOICE_PROVIDER_URL (provider URL must not contain embedded credentials)",
            result["checks"]["voice_generation"]["missing"],
        )
        self.assertTrue(result["checks"]["video_rendering"]["configured"])

    def test_optional_transcription_endpoint_is_validated_when_present(self):
        result = build_preflight({
            "TRANSCRIPTION_PROVIDER_URL": "http://transcriber.example.test/api"
        })
        self.assertFalse(result["checks"]["transcription_provider"]["configured"])
        self.assertIn(
            "TRANSCRIPTION_PROVIDER_URL (provider URL must use HTTPS)",
            result["missing"],
        )

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
                "NEXUS_REVIEW_TOKEN": "operator-secret-with-at-least-32-characters",
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
        for secret in ("operator-secret-with-at-least-32-characters", "youtube-secret", "youtube-refresh"):
            self.assertNotIn(secret, str(result))

    def test_tiktok_oauth_configuration_is_reported_separately(self):
        with tempfile.TemporaryDirectory() as media_dir:
            env = {
                "NEXUS_REVIEW_TOKEN": "operator-secret-with-at-least-32-characters",
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
                "NEXUS_REVIEW_TOKEN": "operator-secret-with-at-least-32-characters",
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




    def test_per_operator_credentials_satisfy_auth_preflight_without_legacy_token(self):
        result = build_preflight({
            "NEXUS_REVIEW_CREDENTIALS_JSON": '{"alice":"' + ("a" * 48) + '"}',
        })
        self.assertTrue(result["checks"]["operator_auth"]["configured"])
        self.assertNotIn("NEXUS_REVIEW_TOKEN", result["missing"])
        self.assertFalse(result["checks"]["operator_rbac"]["configured"])
        self.assertFalse(result["checks"]["operator_rbac"]["optional"])
        self.assertIn("NEXUS_REVIEW_ROLE_MAP_JSON", result["missing"])
        self.assertIn(
            "NEXUS_REVIEW_ROLE_MAP_JSON",
            result["checks"]["operator_rbac"]["missing"],
        )

    def test_legacy_single_token_mode_keeps_role_map_optional(self):
        result = build_preflight({
            "NEXUS_REVIEW_TOKEN": "legacy-secret-value-with-at-least-32-characters"
        })
        self.assertTrue(result["checks"]["operator_auth"]["configured"])
        self.assertTrue(result["checks"]["operator_rbac"]["configured"])
        self.assertTrue(result["checks"]["operator_rbac"]["optional"])
        self.assertNotIn("NEXUS_REVIEW_ROLE_MAP_JSON", result["missing"])

    def test_weak_legacy_token_does_not_satisfy_auth_preflight(self):
        result = build_preflight({"NEXUS_REVIEW_TOKEN": "short-secret"})
        self.assertFalse(result["checks"]["operator_auth"]["configured"])
        self.assertIn(
            "NEXUS_REVIEW_TOKEN (must be 32-512 printable ASCII characters)",
            result["checks"]["operator_auth"]["missing"],
        )

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
            "NEXUS_REVIEW_TOKEN": "operator-secret-with-at-least-32-characters",
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
            env["NEXUS_REVIEW_TOKEN"] = "valid-legacy-token-with-at-least-32-characters"
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
