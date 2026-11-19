import os
import tempfile
import unittest
from unittest.mock import patch

from development_backlog_service import DevelopmentBacklogService
from development_jobs import DevelopmentJobStore


class FakeGitHub:
    def list_issues(self, owner, repository, **kwargs):
        return [{
            "number": 12, "title": "Add export", "state": "open",
            "labels": ["development-job"], "body": "Implement export",
        }]

    def list_pull_requests(self, owner, repository, **kwargs):
        return []

    def list_workflow_runs(self, owner, repository, **kwargs):
        return []


class DevelopmentBacklogServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = DevelopmentJobStore(os.path.join(self.tmp.name, "jobs.sqlite3"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_cycle_syncs_approved_issue_then_worker_claims_it(self):
        source_ref = "github:issue:acme/app#12"
        service = DevelopmentBacklogService(
            store=self.store,
            github_client=FakeGitHub(),
            owner="acme",
            repository="app",
            executor=lambda job: {
                "changed_files": ["backend/export.py"],
                "tests_passed": True,
                "validation_ref": "ci://run/123",
                "result_summary": "export implementation validated",
            },
            worker_id="test-worker",
            approved_scopes={source_ref: ["backend/export.py"]},
            poll_seconds=1,
            idle_seconds=1,
        )
        result = service.run_cycle()
        self.assertEqual(result["intake"]["import"]["created_count"], 1)
        self.assertEqual(result["execution"]["processed"], 1)
        self.assertEqual(result["execution"]["outcomes"], {"review_pending": 1})
        jobs = self.store.list()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["status"], "review_pending")

    def test_run_forever_stops_after_any_claimed_attempt(self):
        service = DevelopmentBacklogService(
            store=self.store,
            github_client=FakeGitHub(),
            owner="acme",
            repository="app",
            executor=lambda job: {},
            worker_id="test-worker",
            approved_scopes={},
            poll_seconds=1,
            idle_seconds=1,
        )
        with patch.object(
            service, "run_cycle",
            return_value={"execution": {"processed": 1, "outcomes": {"retry_wait": 1}}},
        ) as run_cycle:
            result = service.run_forever()

        self.assertEqual(run_cycle.call_count, 1)
        self.assertEqual(result["cycles"], 1)
        self.assertEqual(result["last_result"]["execution"]["processed"], 1)

    def test_cycle_does_not_import_issue_without_scope_approval(self):
        service = DevelopmentBacklogService(
            store=self.store,
            github_client=FakeGitHub(),
            owner="acme",
            repository="app",
            executor=lambda job: {},
            worker_id="test-worker",
            approved_scopes={},
            poll_seconds=1,
            idle_seconds=1,
        )
        result = service.run_cycle()
        self.assertEqual(result["intake"]["import"]["created_count"], 0)
        self.assertEqual(result["execution"]["processed"], 0)
        self.assertEqual(self.store.list(), [])


if __name__ == "__main__":
    unittest.main()
