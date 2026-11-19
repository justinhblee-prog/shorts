import unittest

from development_security import redact_sensitive_text


class DevelopmentDiagnosticRedactionTests(unittest.TestCase):
    def test_redacts_quoted_json_credential_keys(self):
        secret = "ghp_123456789012345678901234567890"
        value = '{"GITHUB_TOKEN": "' + secret + '", "status": "failed"}'
        safe = redact_sensitive_text(value)
        self.assertNotIn(secret, safe)
        self.assertIn("[REDACTED]", safe)

    def test_redacts_basic_authorization_and_url_credentials(self):
        basic = "Basic dXNlcjpwYXNzd29yZA=="
        url = "https://runner:secret-password@example.test/private"
        safe = redact_sensitive_text(f"auth={basic} endpoint={url}")
        self.assertNotIn("dXNlcjpwYXNzd29yZA==", safe)
        self.assertNotIn("secret-password", safe)
        self.assertIn("Basic [REDACTED]", safe)

    def test_redacts_multiline_pem_private_key(self):
        value = (
            "before\n-----BEGIN PRIVATE KEY-----\n"
            "private-key-material\n-----END PRIVATE KEY-----\nafter"
        )
        safe = redact_sensitive_text(value)
        self.assertNotIn("private-key-material", safe)
        self.assertIn("[REDACTED PRIVATE KEY]", safe)

    def test_redacts_common_provider_token_formats(self):
        values = (
            "github_pat_123456789012345678901234567890",
            "xoxb-123456789012345678901234567890",
            "glpat-123456789012345678901234567890",
            "npm_123456789012345678901234567890",
            "pypi-123456789012345678901234567890",
            "AIza12345678901234567890123456789012",
            "AKIA1234567890ABCD12",
            "sk_live_123456789012",
        )
        safe = redact_sensitive_text(" ".join(values))
        for value in values:
            with self.subTest(value=value):
                self.assertNotIn(value, safe)

    def test_rejects_invalid_output_limits(self):
        for value in (0, -1, True, 1.5):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    redact_sensitive_text("diagnostic", value)


if __name__ == "__main__":
    unittest.main()
