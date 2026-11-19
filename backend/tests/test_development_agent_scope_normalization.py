import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from run_development_agent import _normalize_approved_scopes, _worker_session_id, main


class ApprovedScopeNormalizationTests(unittest.TestCase):
    def test_existing_directories_are_explicit_and_extensionless_files_stay_exact(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "backend").mkdir()
            (root / "LICENSE").write_text("license", encoding="utf-8")
            scopes = _normalize_approved_scopes(
                {"github:issue:acme/app#1": ["backend", "LICENSE"]},
                root,
            )
        self.assertEqual(scopes, {"github:issue:acme/app#1": ["backend/", "LICENSE"]})

    def test_worker_session_identity_is_unique_per_workflow_attempt(self):
        base = {
            "RUNNER_NAME": "windows-nexus-runner",
            "GITHUB_RUN_ID": "44520050960",
            "GITHUB_RUN_ATTEMPT": "1",
        }
        first = _worker_session_id(base)
        second = _worker_session_id(base)
        retry = _worker_session_id({**base, "GITHUB_RUN_ATTEMPT": "2"})
        self.assertNotEqual(first, second)
        self.assertNotEqual(first, retry)
        self.assertTrue(first.startswith("windows-nexus-runner:run-44520050960:attempt-1:"))
        self.assertTrue(retry.startswith("windows-nexus-runner:run-44520050960:attempt-2:"))
        self.assertLessEqual(len(first), 128)

    def test_worker_session_identity_bounds_long_host_names(self):
        worker_id = _worker_session_id({"RUNNER_NAME": "x" * 200})
        self.assertLessEqual(len(worker_id), 128)
        self.assertTrue(worker_id.startswith("x"))

    def test_runner_redacts_secrets_from_top_level_workflow_errors(self):
        secret = "ghp_123456789012345678901234567890"
        output = io.StringIO()
        with patch("run_development_agent.run_once",
                   side_effect=RuntimeError("GITHUB_TOKEN=" + secret)):
            with redirect_stderr(output):
                self.assertEqual(main(), 1)
        self.assertNotIn(secret, output.getvalue())
        self.assertIn("[REDACTED]", output.getvalue())

    def test_nested_directories_are_marked_and_traversal_is_not_rewritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "backend" / "tools").mkdir(parents=True)
            scopes = _normalize_approved_scopes(
                {"github:issue:acme/app#2": ["backend/tools", "../outside"]},
                root,
            )
        self.assertEqual(scopes, {"github:issue:acme/app#2": ["backend/tools/", "../outside"]})


if __name__ == "__main__":
    unittest.main()
