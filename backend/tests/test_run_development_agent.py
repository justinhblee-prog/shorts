import unittest
from unittest.mock import patch

from run_development_agent import run_once


class FakeStore:
    def __init__(self, path):
        self.path = path

    def summary(self):
        return {"ready": 0, "completed": 0, "review_pending": 0}

    def list(self, statuses=None, limit=100):
        return []



class PendingFakeStore(FakeStore):
    def list(self, statuses=None, limit=100):
        if statuses == ["review_pending"]:
            return [{"id": "pending-job"}]
        return []


class FakeService:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

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


    def test_restores_pending_publication_before_claiming_new_work(self):
        env = {
            "GITHUB_TOKEN": "read-only-test-token",
            "GITHUB_REPOSITORY": "acme/app",
            "GITHUB_WORKSPACE": "/tmp/nexus",
            "RUNNER_NAME": "nexus-runner",
            "NEXUS_APPROVED_SCOPES": "{}",
            "NEXUS_DEVELOPMENT_ARTIFACT_DIR": "/tmp/nexus-state/artifacts",
        }
        with patch("run_development_agent.DevelopmentJobStore", PendingFakeStore), \
             patch("run_development_agent.seed_development_jobs", return_value=[]), \
             patch("run_development_agent.GitHubReadOnlyClient"), \
             patch("run_development_agent.AiderDevelopmentExecutor"), \
             patch("run_development_agent.DevelopmentBacklogService") as service, \
             patch("run_development_agent.restore_pending_artifacts", return_value=["pending-job"]) as restore:
            result = run_once(env)
        restore.assert_called_once()
        service.return_value.run_cycle.assert_not_called()
        self.assertEqual(result["restored_pending_job_ids"], ["pending-job"])
        self.assertEqual(result["execution"]["processed"], 0)

    def test_rejects_non_object_scope_configuration(self):
        env = {
            "GITHUB_TOKEN": "token", "GITHUB_REPOSITORY": "acme/app",
            "NEXUS_APPROVED_SCOPES": "[]",
        }
        with self.assertRaises(ValueError):
            run_once(env)


if __name__ == "__main__":
    unittest.main()
