import os
import tempfile
import unittest
from unittest.mock import patch
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

    def test_explicit_aider_executable_is_used_without_path_lookup(self):
        executable = self.root / "aider.exe"
        executable.write_text("test executable", encoding="utf-8")
        with patch.dict(os.environ, {"NEXUS_AIDER_EXECUTABLE": str(executable)}):
            with patch("development_agent_executor.shutil.which", return_value=None):
                self.assertEqual(self.executor._resolve_aider_executable(), str(executable))

    def test_invalid_explicit_aider_executable_fails_closed(self):
        missing = self.root / "missing-aider.exe"
        with patch.dict(os.environ, {"NEXUS_AIDER_EXECUTABLE": str(missing)}):
            with patch("development_agent_executor.shutil.which", return_value="aider"):
                with self.assertRaises(NonRetryableDevelopmentJobError):
                    self.executor._resolve_aider_executable()

    def test_child_environment_strips_encryption_database_and_service_credentials(self):
        values = {
            "GITHUB_TOKEN": "ghp_sensitive",
            "NEXUS_BACKUP_ENCRYPTION_KEY": "backup-key-sensitive",
            "DATABASE_URL": "postgres://user:password@db.example/nexus",
            "REDIS_URL": "redis://:password@cache.example/0",
            "SUPABASE_SERVICE_ROLE_KEY": "service-role-sensitive",
            "FIREBASE_SERVICE_ACCOUNT": "service-account-sensitive",
            "AWS_ACCESS_KEY_ID": "aws-access-sensitive",
            "AZURE_CLIENT_SECRET": "azure-secret-sensitive",
            "OLLAMA_API_BASE": "http://127.0.0.1:11434",
            "GITHUB_WORKSPACE": str(self.root),
            "NEXUS_APPROVED_SCOPES": "{}",
            "NEXUS_DEV_AGENT_MODEL": "ollama_chat/qwen2.5-coder:7b",
        }
        with patch.dict(os.environ, values):
            child_env = self.executor._child_environment()

        for key in (
            "GITHUB_TOKEN", "NEXUS_BACKUP_ENCRYPTION_KEY", "DATABASE_URL",
            "REDIS_URL", "SUPABASE_SERVICE_ROLE_KEY", "FIREBASE_SERVICE_ACCOUNT",
            "AWS_ACCESS_KEY_ID", "AZURE_CLIENT_SECRET",
        ):
            with self.subTest(secret=key):
                self.assertNotIn(key, child_env)

        self.assertEqual(child_env["OLLAMA_API_BASE"], "http://127.0.0.1:11434")
        self.assertEqual(child_env["GITHUB_WORKSPACE"], str(self.root))
        self.assertEqual(child_env["NEXUS_APPROVED_SCOPES"], "{}")
        self.assertEqual(child_env["NEXUS_DEV_AGENT_MODEL"], "ollama_chat/qwen2.5-coder:7b")

    def test_diagnostic_redaction_removes_bearer_and_common_api_tokens(self):
        message = "Bearer abc.def token=private123 ghp_123456789012345678901234567890"
        safe = _tail(message)
        self.assertNotIn("abc.def", safe)
        self.assertNotIn("private123", safe)
        self.assertNotIn("ghp_123456789012345678901234567890", safe)
        self.assertIn("[REDACTED]", safe)


if __name__ == "__main__":
    unittest.main()
