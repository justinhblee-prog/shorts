import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from development_agent_executor import AiderDevelopmentExecutor, _tail
from development_job_worker import NonRetryableDevelopmentJobError


class AiderDevelopmentExecutorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "backend").mkdir()
        (self.root / ".github" / "workflows").mkdir(parents=True)
        self.executor = AiderDevelopmentExecutor(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_scope_preserves_dot_github_path_and_accepts_scoped_files(self):
        scope = self.executor._validated_scope({
            "scope": [".github/workflows/nexus.yml", "backend/module.py"]
        })
        self.assertEqual(scope, [".github/workflows/nexus.yml", "backend/module.py"])

    def test_scope_rejects_traversal_and_environment_files(self):
        for path in ("../outside.py", ".env", ".env.production", "backend/credentials.json", "config/client_credential.json", "backend/private_config.py"):
            with self.subTest(path=path):
                with self.assertRaises(NonRetryableDevelopmentJobError):
                    self.executor._validated_scope({"scope": [path]})

    def test_changed_file_must_be_inside_declared_scope(self):
        self.assertTrue(self.executor._matches_scope("backend/a.py", ["backend"]))
        self.assertTrue(self.executor._matches_scope("backend/a.py", ["backend/"]))
        self.assertFalse(self.executor._matches_scope("frontend/a.js", ["backend"]))

    def test_persisted_source_artifact_is_outside_checkout_and_integrity_checked(self):
        source = self.root / "backend" / "new_module.py"
        source.write_text("VALUE = 42\\n", encoding="utf-8")
        artifact_root = self.root.parent / "persistent-artifacts"
        path, digest = self.executor._persist_artifact(
            {"id": "job-1"}, ["backend/new_module.py"],
            {"NEXUS_DEVELOPMENT_ARTIFACT_DIR": str(artifact_root)},
        )
        artifact = Path(path)
        self.assertTrue(artifact.is_file())
        self.assertNotIn(str(self.root), str(artifact))
        self.assertEqual(hashlib.sha256(artifact.read_bytes()).hexdigest(), digest)
        with zipfile.ZipFile(artifact) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["job_id"], "job-1")
            self.assertEqual(manifest["files"][0]["path"], "backend/new_module.py")
            self.assertIsNone(manifest["files"][0]["base_sha256"])
            self.assertEqual(archive.read("files/backend/new_module.py"), b"VALUE = 42\\n")

    def test_persisted_artifact_rejects_checkout_directory(self):
        with self.assertRaises(NonRetryableDevelopmentJobError):
            self.executor._persist_artifact(
                {"id": "job-2"}, ["backend/new_module.py"],
                {"NEXUS_DEVELOPMENT_ARTIFACT_DIR": str(self.root / "inside")},
            )

    def test_diagnostic_redaction_removes_bearer_and_common_api_tokens(self):
        message = "Bearer abc.def token=private123 ghp_123456789012345678901234567890"
        safe = _tail(message)
        self.assertNotIn("abc.def", safe)
        self.assertNotIn("private123", safe)
        self.assertNotIn("ghp_123456789012345678901234567890", safe)
        self.assertIn("[REDACTED]", safe)


if __name__ == "__main__":
    unittest.main()
