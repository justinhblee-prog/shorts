import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from run_development_agent import _normalize_approved_scopes, run_once


class FakeStore:
    def __init__(self, path):
        self.path = path

    def summary(self):
        return {"ready": 0, "completed": 0}


class FakeService:
    last_kwargs = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        FakeService.last_kwargs = kwargs

    def run_cycle(self):
        return {"intake": {"import": {"created_count": 0}},
                "execution": {"processed": 0}}


class RunDevelopmentAgentTests(unittest.TestCase):
    def test_requires_token_and_repository(self):
        with self.assertRaises(ValueError):
            run_once({})

    def test_rejects_malformed_repository(self):
        with self.assertRaises(ValueError):
            run_once({"GITHUB_TOKEN": "token", "GITHUB_REPOSITORY": "owner-only"})

    def test_runs_one_cycle_with_local_model_configuration(self):
        env = {
            "GITHUB_TOKEN": "read-only-test-token",
            "GITHUB_REPOSITORY": "acme/app",
            "GITHUB_WORKSPACE": "/tmp/nexus",
            "RUNNER_NAME": "nexus-runner",
            "NEXUS_APPROVED_SCOPES": '{"github:issue:acme/app#1":["backend/a.py"]}',
        }
        with patch("run_development_agent.DevelopmentJobStore", FakeStore), \
             patch("run_development_agent.seed_development_jobs", return_value=[{}, {}]), \
             patch("run_development_agent.GitHubReadOnlyClient") as github, \
             patch("run_development_agent.AiderDevelopmentExecutor") as executor, \
             patch("run_development_agent.DevelopmentBacklogService", FakeService):
            result = run_once(env)

        github.assert_called_once_with("read-only-test-token")
        self.assertEqual(result["seeded_job_count"], 2)
        self.assertEqual(result["execution"]["processed"], 0)
        self.assertEqual(result["database_summary"]["ready"], 0)
        self.assertTrue(FakeService.last_kwargs["require_execution_verifier"])

    def test_approved_scope_symlink_aliases_resolve_to_canonical_targets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            backend = root / "backend"
            target_dir = backend / "real"
            target_dir.mkdir(parents=True)
            alias_dir = backend / "alias"
            alias_dir.symlink_to(target_dir, target_is_directory=True)

            target_file = backend / "real.py"
            target_file.write_text("value = 1", encoding="utf-8")
            alias_file = backend / "alias.py"
            alias_file.symlink_to(target_file)

            result = _normalize_approved_scopes(
                {"github:issue:acme/app#2": ["backend/alias", "backend/alias.py"]},
                root,
            )
            self.assertEqual(
                result["github:issue:acme/app#2"],
                ["backend/real/", "backend/real.py"],
            )

    def test_rejects_non_object_scope_configuration(self):
        env = {
            "GITHUB_TOKEN": "token", "GITHUB_REPOSITORY": "acme/app",
            "NEXUS_APPROVED_SCOPES": "[]",
        }
        with self.assertRaises(ValueError):
            run_once(env)


if __name__ == "__main__":
    unittest.main()
