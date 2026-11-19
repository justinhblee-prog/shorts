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
        for path in (
            "../outside.py", ".env", ".env.production",
            "backend/credentials.json", "config/client_credential.json",
            "backend/private_config.py", "id_rsa", "id_ed25519_work",
            ".ssh/id_ed25519", ".aws/credentials", ".azure/client_secret.json",
            ".kube/config", ".docker/config.json", ".gnupg/private-keys-v1.d",
            ".terraform/terraform.tfstate", ".pulumi/credentials.json",
            ".netrc", ".npmrc", ".pypirc", ".git-credentials",
            "service-account.json", "service_account.json", "kubeconfig",
            "terraform.tfvars", ".config/gcloud/application_default_credentials.json",
            ".config/gh/hosts.yml", ".config/pip/pip.conf",
            ".config/containers/auth.json", "authorized_keys", "known_hosts",
        ):
            with self.subTest(path=path):
                with self.assertRaises(NonRetryableDevelopmentJobError):
                    self.executor._validated_scope({"scope": [path]})

    def test_scope_rejects_symlink_aliases_to_internal_secret_files(self):
        ssh_dir = self.root / ".ssh"
        ssh_dir.mkdir()
        private_key = ssh_dir / "id_ed25519"
        private_key.write_text("private-key", encoding="utf-8")
        alias = self.root / "backend" / "ordinary_module.py"
        try:
            alias.symlink_to(private_key)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are not supported in this environment")
        with self.assertRaises(NonRetryableDevelopmentJobError):
            self.executor._validated_scope({"scope": ["backend/ordinary_module.py"]})

        credential = self.root / "backend" / "credentials.json"
        credential.write_text("{}", encoding="utf-8")
        alias.unlink()
        alias.symlink_to(credential)
        with self.assertRaises(NonRetryableDevelopmentJobError):
            self.executor._validated_scope({"scope": ["backend/ordinary_module.py"]})

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
            "GITHUB_ENV": "C:/runner/_temp/env-file",
            "GITHUB_OUTPUT": "C:/runner/_temp/output-file",
            "GITHUB_PATH": "C:/runner/_temp/path-file",
            "GITHUB_STEP_SUMMARY": "C:/runner/_temp/summary-file",
            "GITHUB_STATE": "C:/runner/_temp/state-file",
            "GITHUB_EVENT_PATH": "C:/runner/_temp/event.json",
            "ACTIONS_CACHE_URL": "https://cache.example",
            "ACTIONS_RESULTS_URL": "https://results.example",
            "RUNNER_TEMP": "C:/runner/_temp",
            "RUNNER_WORKSPACE": "C:/runner/_work",
            "RUNNER_TOOL_CACHE": "C:/runner/_tool",
            "RUNNER_TRACKING_ID": "runner-tracking-sensitive",
            "RUNNER_NAME": "private-runner-name",
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
            "AWS_ACCESS_KEY_ID", "AZURE_CLIENT_SECRET", "GITHUB_ENV", "GITHUB_OUTPUT",
            "GITHUB_PATH", "GITHUB_STEP_SUMMARY", "GITHUB_STATE",
            "GITHUB_EVENT_PATH", "ACTIONS_CACHE_URL", "ACTIONS_RESULTS_URL",
            "RUNNER_TEMP", "RUNNER_WORKSPACE", "RUNNER_TOOL_CACHE",
            "RUNNER_TRACKING_ID", "RUNNER_NAME",
        ):
            with self.subTest(secret=key):
                self.assertNotIn(key, child_env)

        self.assertEqual(child_env["OLLAMA_API_BASE"], "http://127.0.0.1:11434")
        self.assertEqual(child_env["GITHUB_WORKSPACE"], str(self.root))
        self.assertEqual(child_env["NEXUS_APPROVED_SCOPES"], "{}")
        self.assertEqual(child_env["NEXUS_DEV_AGENT_MODEL"], "ollama_chat/qwen2.5-coder:7b")

    def test_diagnostic_redaction_removes_bearer_and_common_api_tokens(self):
        message = (
            "Bearer abc.def token=private123 "
            "NEXUS_BACKUP_ENCRYPTION_KEY=backup-secret "
            "DATABASE_URL=postgres://user:password@db.example/nexus "
            "SUPABASE_SERVICE_ROLE_KEY=service-role-secret "
            "PRIVATE_KEY=private-key-secret "
            "ghp_123456789012345678901234567890"
        )
        safe = _tail(message)
        for secret in (
            "abc.def", "private123", "backup-secret",
            "postgres://user:password@db.example/nexus",
            "service-role-secret", "private-key-secret",
            "ghp_123456789012345678901234567890",
        ):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, safe)
        self.assertIn("[REDACTED]", safe)


if __name__ == "__main__":
    unittest.main()
