import os
import tempfile
import unittest

from development_github_intake import (
    normalize_issue, normalize_snapshot, read_github_snapshot,
    summarize_pull_request, summarize_workflow_run, sync_labeled_issues,
)
from development_jobs import DevelopmentJobStore


class FakeReadOnlyGitHub:
    def __init__(self):
        self.calls = []

    def list_issues(self, owner, repository, **kwargs):
        self.calls.append(("issues", owner, repository, kwargs))
        return [{"number": 7, "title": "Implement export", "state": "open",
                 "labels": [{"name": "nexus:development-job"}],
                 "body": "Add CSV export", "repository": "acme/app"}]

    def list_pull_requests(self, owner, repository, **kwargs):
        self.calls.append(("pulls", owner, repository, kwargs))
        return [{"number": 8, "title": "WIP", "state": "open", "draft": True,
                 "head": {"sha": "abc"}}]

    def list_workflow_runs(self, owner, repository, **kwargs):
        self.calls.append(("runs", owner, repository, kwargs))
        return [{"id": 99, "name": "CI", "status": "completed",
                 "conclusion": "failure", "head_sha": "abc"}]


class DevelopmentGitHubIntakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = DevelopmentJobStore(os.path.join(self.tmp.name, "jobs.sqlite3"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_explicitly_labeled_open_issue_becomes_candidate(self):
        candidate = normalize_issue({
            "number": 4, "title": "Fix render", "state": "open",
            "labels": ["development-job"], "repository": "acme/app",
        })
        self.assertEqual(candidate["source_ref"], "github:issue:acme/app#4")
        self.assertEqual(candidate["scope"], [])
        self.assertIsNone(normalize_issue({
            "number": 5, "title": "Ordinary issue", "state": "open", "labels": [],
        }))
        self.assertIsNone(normalize_issue({
            "number": 6, "title": "Closed", "state": "closed",
            "labels": ["development-job"],
        }))
        self.assertIsNone(normalize_issue({
            "number": 7, "title": "PR masquerading as issue", "state": "open",
            "labels": ["development-job"], "pull_request": {"url": "https://api.github.com/..."}
        }))

    def test_sync_is_idempotent_and_does_not_import_prs(self):
        issue = {"number": 4, "title": "Fix render", "state": "open",
                 "labels": ["development-job"], "repository": "acme/app"}
        resolver = lambda _: ["backend/export.py"]
        first = sync_labeled_issues(self.store, [issue], scope_resolver=resolver)
        second = sync_labeled_issues(self.store, [issue], scope_resolver=resolver)
        self.assertEqual(first["created_count"], 1)
        self.assertEqual(second["created_count"], 0)
        self.assertEqual(second["skipped"][0]["reason"], "duplicate")
        self.assertEqual(len(self.store.list()), 1)

    def test_scope_must_be_configured_before_import(self):
        issue = {"number": 3, "title": "Feature", "state": "open", "labels": ["development-job"], "repository": "acme/app"}
        result = sync_labeled_issues(self.store, [issue])
        self.assertEqual(result["created_count"], 0)
        self.assertEqual(result["skipped"][0]["reason"], "scope_not_configured")
        self.assertEqual(self.store.list(), [])

    def test_pull_request_states_are_context_only(self):
        self.assertEqual(summarize_pull_request({
            "number": 10, "state": "open", "draft": True,
        })["state"], "draft")
        self.assertEqual(summarize_pull_request({
            "number": 11, "state": "closed", "merged": True,
        })["state"], "closed")
        self.assertIsNone(summarize_pull_request({"number": "bad"}))

    def test_workflow_failure_is_evidence_context_not_job(self):
        result = summarize_workflow_run({
            "id": 99, "status": "completed", "conclusion": "failure",
        })
        self.assertEqual(result["conclusion"], "failure")
        self.assertIsNone(summarize_workflow_run({"id": -1}))

    def test_snapshot_uses_bounded_read_only_client(self):
        client = FakeReadOnlyGitHub()
        snapshot = read_github_snapshot(client, "acme", "app")
        self.assertEqual(snapshot["issues"][0]["repository"], "acme/app")
        normalized = normalize_snapshot(snapshot)
        self.assertEqual(len(normalized["job_candidates"]), 1)
        self.assertEqual(normalized["pull_requests"][0]["state"], "draft")
        self.assertEqual(normalized["workflow_runs"][0]["conclusion"], "failure")
        self.assertEqual([call[0] for call in client.calls], ["issues", "pulls", "runs"])
        self.assertTrue(all(call[3]["per_page"] == 100 for call in client.calls))


    def test_rest_client_exposes_get_only_bounded_endpoints(self):
        from development_github_intake import GitHubReadOnlyClient

        class RecordingClient(GitHubReadOnlyClient):
            def __init__(self):
                super().__init__("test-token")
                self.paths = []

            def _get_pages(self, path, params=""):
                self.paths.append((path, params))
                if path.endswith("/actions/runs"):
                    return [{"workflow_runs": [{"id": 1}]}]
                return []

        client = RecordingClient()
        self.assertEqual(client.list_issues("acme", "app"), [])
        self.assertEqual(client.list_pull_requests("acme", "app"), [])
        self.assertEqual(client.list_workflow_runs("acme", "app"), [{"id": 1}])
        self.assertEqual([item[0] for item in client.paths], [
            "/repos/acme/app/issues", "/repos/acme/app/pulls",
            "/repos/acme/app/actions/runs",
        ])
        with self.assertRaises(ValueError):
            client.list_issues("acme", "app", state="all")

    def test_rest_client_requires_token(self):
        from development_github_intake import GitHubReadOnlyClient
        with self.assertRaises(ValueError):
            GitHubReadOnlyClient(" ")


if __name__ == "__main__":
    unittest.main()
