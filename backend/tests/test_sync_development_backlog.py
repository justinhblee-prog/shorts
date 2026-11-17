import json
import os
import tempfile
import unittest
from unittest.mock import patch

from sync_development_backlog import run_from_environment


class SyncDevelopmentBacklogRunnerTests(unittest.TestCase):
    def test_requires_read_only_credentials_and_repository(self):
        with self.assertRaises(ValueError):
            run_from_environment({})

    def test_rejects_invalid_scope_configuration(self):
        env = {
            "GITHUB_TOKEN": "token",
            "GITHUB_REPOSITORY_OWNER": "acme",
            "GITHUB_REPOSITORY_NAME": "app",
            "NEXUS_APPROVED_SCOPES": "[]",
        }
        with self.assertRaises(ValueError):
            run_from_environment(env)

    def test_runs_sync_with_explicit_environment_and_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            env = {
                "GITHUB_TOKEN": "token",
                "GITHUB_REPOSITORY_OWNER": "acme",
                "GITHUB_REPOSITORY_NAME": "app",
                "NEXUS_DEVELOPMENT_DB": os.path.join(temp, "jobs.sqlite3"),
                "NEXUS_APPROVED_SCOPES": json.dumps({
                    "github:issue:acme/app#7": ["backend/export.py"]
                }),
            }

            class FakeClient:
                def __init__(self, token):
                    self.token = token

                def list_issues(self, owner, repository, **kwargs):
                    return [{
                        "number": 7, "title": "Implement export", "state": "open",
                        "labels": ["development-job"], "body": "CSV export",
                    }]

                def list_pull_requests(self, owner, repository, **kwargs):
                    return []

                def list_workflow_runs(self, owner, repository, **kwargs):
                    return []

            with patch("sync_development_backlog.GitHubReadOnlyClient", FakeClient):
                result = run_from_environment(env)

            self.assertEqual(result["import"]["created_count"], 1)
            self.assertEqual(result["candidate_count"], 1)


if __name__ == "__main__":
    unittest.main()
