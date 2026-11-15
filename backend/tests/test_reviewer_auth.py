import json
import unittest
from reviewer_auth import ReviewCredentialConfigurationError, resolve_review_principal

class ReviewerAuthTests(unittest.TestCase):
    def test_individual_tokens_resolve_to_configured_identity(self):
        credentials = json.dumps({"alice": "a" * 48, "review-team-2": "b" * 48})
        self.assertEqual(resolve_review_principal("a" * 48, credentials_json=credentials), "alice")
        self.assertEqual(resolve_review_principal("b" * 48, credentials_json=credentials), "review-team-2")

    def test_invalid_token_does_not_authenticate(self):
        credentials = json.dumps({"alice": "a" * 48})
        self.assertIsNone(resolve_review_principal("wrong-token", credentials_json=credentials))
        self.assertIsNone(resolve_review_principal(None, credentials_json=credentials))

    def test_individual_credentials_disable_legacy_shared_token_fallback(self):
        credentials = json.dumps({"alice": "a" * 48})
        self.assertIsNone(resolve_review_principal("legacy-shared-token", credentials_json=credentials, legacy_token="legacy-shared-token"))

    def test_legacy_shared_token_has_fixed_non_spoofable_identity(self):
        self.assertEqual(resolve_review_principal("legacy-shared-token", credentials_json="", legacy_token="legacy-shared-token"), "legacy-operator")
        self.assertIsNone(resolve_review_principal("wrong", credentials_json="", legacy_token="legacy-shared-token"))

    def test_malformed_or_weak_credentials_fail_configuration_closed(self):
        values = ["not-json", "[]", "{}", json.dumps({"alice": "short"}), json.dumps({"alice": "a" * 40, "bob": "a" * 40})]
        for raw in values:
            with self.subTest(raw=raw):
                with self.assertRaises(ReviewCredentialConfigurationError):
                    resolve_review_principal("a" * 48, credentials_json=raw)

    def test_reviewer_identity_is_validated(self):
        values = [json.dumps({"": "a" * 40}), json.dumps({"x" * 129: "a" * 40})]
        for raw in values:
            with self.subTest(raw=raw):
                with self.assertRaises(ReviewCredentialConfigurationError):
                    resolve_review_principal("a" * 40, credentials_json=raw)

if __name__ == "__main__":
    unittest.main()
