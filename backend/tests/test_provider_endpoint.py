import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from io import BytesIO

from provider_endpoint import provider_endpoint_error
from production_pipeline import JsonProvider, ProviderError


class ProviderEndpointTests(unittest.TestCase):
    def test_accepts_valid_https_provider_urls(self):
        for value in (
            "https://api.example.test/v1/generate",
            "https://api.example.test:8443/v1/generate?region=KR",
        ):
            self.assertIsNone(provider_endpoint_error(value))

    def test_rejects_insecure_or_malformed_urls(self):
        invalid = (
            "http://api.example.test/generate",
            "ftp://api.example.test/generate",
            "https:///missing-host",
            "https://user:password@api.example.test/generate",
            "https://api.example.test/generate#fragment",
            "https://api.example.test:bad/generate",
            "https://api.example.test:70000/generate",
        )
        for value in invalid:
            with self.subTest(value=value):
                self.assertIsNotNone(provider_endpoint_error(value))

    def test_http_endpoint_is_rejected_before_transport_receives_bearer_token(self):
        calls = []
        provider = JsonProvider(
            "http://attacker.example/collect",
            token="must-not-leak",
            transport=lambda *args: calls.append(args),
        )
        with self.assertRaises(ProviderError) as caught:
            provider.post("script", {"topic": "test"})
        self.assertFalse(caught.exception.retryable)
        self.assertEqual(calls, [])
        self.assertNotIn("must-not-leak", str(caught.exception))
        self.assertNotIn("attacker.example", str(caught.exception))

    def test_provider_http_error_body_is_not_persisted(self):
        error = HTTPError(
            "https://api.example.test/generate", 401, "Unauthorized", {},
            BytesIO(b"upstream echoed bearer=secret-value"),
        )
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(ProviderError) as caught:
                JsonProvider._request(
                    "https://api.example.test/generate", {}, b"{}", 1
                )
        self.assertNotIn("secret-value", str(caught.exception))
        self.assertIn("401", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
