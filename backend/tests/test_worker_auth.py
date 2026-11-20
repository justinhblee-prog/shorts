import hashlib
import json
import unittest

from worker_auth import (
    authenticate_worker,
    WorkerAuthConfigurationError,
    WorkerAuthenticationError,
)


class WorkerAuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.token = "worker-secret-for-test-only-32-bytes-minimum"
        self.credentials = json.dumps({
            "worker-alpha": {
                "token_sha256": hashlib.sha256(self.token.encode()).hexdigest(),
                "workspace_ids": ["workspace-a", "workspace-b"],
            }
        })

    def test_valid_digest_returns_immutable_identity_and_explicit_grants(self):
        identity = authenticate_worker(
            "Bearer " + self.token, credentials_json=self.credentials
        )
        self.assertEqual(identity.worker_id, "worker-alpha")
        self.assertEqual(identity.workspace_ids, ("workspace-a", "workspace-b"))

    def test_invalid_or_missing_bearer_is_rejected(self):
        for authorization in (None, "Basic " + self.token, "Bearer wrong-token",
                             "Bearer " + self.token + " "):
            with self.subTest(authorization=authorization):
                with self.assertRaises(WorkerAuthenticationError):
                    authenticate_worker(authorization, credentials_json=self.credentials)

    def test_configuration_fails_closed_for_wildcard_empty_or_duplicate_grants(self):
        invalid_entries = [
            {"token_sha256": "a" * 64, "workspace_ids": ["*"]},
            {"token_sha256": "a" * 64, "workspace_ids": []},
            {"token_sha256": "a" * 64, "workspace_ids": ["workspace-a", "workspace-a"]},
            {"token_sha256": "not-a-digest", "workspace_ids": ["workspace-a"]},
        ]
        for entry in invalid_entries:
            with self.subTest(entry=entry):
                with self.assertRaises(WorkerAuthConfigurationError):
                    authenticate_worker(
                        "Bearer " + self.token,
                        credentials_json=json.dumps({"worker-alpha": entry}),
                    )

    def test_missing_or_malformed_configuration_is_unavailable(self):
        for config in (None, "", "not-json", "[]"):
            with self.subTest(config=config):
                with self.assertRaises(WorkerAuthConfigurationError):
                    authenticate_worker("Bearer " + self.token, credentials_json=config)


if __name__ == "__main__":
    unittest.main()
