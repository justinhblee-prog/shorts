import os
import tempfile
import unittest
from unittest.mock import patch

from development_github_intake import (
    normalize_issue, normalize_snapshot, read_github_snapshot,
    summarize_pull_request, summarize_workflow_run, sync_labeled_issues, sync_github_backlog,
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

    def test_sync_deduplicates_sources_beyond_the_first_500_jobs(self):
        for number in range(500):
            self.store.create(
                f"Existing job {number}", priority=1,
                source_ref=f"github:acme/app#existing-{number}",
            )
        source_ref = "github:acme/app#501"
        target = self.store.create(
            "Older imported issue", priority=100, source_ref=source_ref,
        )
        self.assertNotIn(target["id"], {job["id"] for job in self.store.list(limit=500)})
        issue = {
            "number": 501, "title": "Older imported issue", "state": "open",
            "labels": ["development-job"], "repository": "acme/app",
        }
        resolver = lambda _: ["backend/approved.py"]

        result = sync_labeled_issues(self.store, [issue], scope_resolver=resolver)
        self.assertEqual(result["created_count"], 0)
        self.assertEqual(result["skipped"][0]["reason"], "duplicate")

        # Simulate the race where another intake inserts the same source after
        # the preflight read. The store's BEGIN IMMEDIATE check must still win.
        with patch.object(self.store, "source_ref_exists", return_value=False):
            raced = sync_labeled_issues(self.store, [issue], scope_resolver=resolver)
        self.assertEqual(raced["created_count"], 0)
        self.assertEqual(raced["skipped"][0]["reason"], "duplicate")
        with self.store.db() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM development_jobs WHERE source_ref=?", (source_ref,)
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_sync_github_backlog_requires_per_issue_scope_approval(self):
        client = FakeReadOnlyGitHub()
        source_ref = "github:issue:acme/app#7"
        result = sync_github_backlog(
            self.store, client, "acme", "app",
            approved_scopes={source_ref: ["backend/export.py"]},
        )
        self.assertEqual(result["import"]["created_count"], 1)
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["snapshot_counts"]["pull_requests"], 1)
        self.assertEqual(self.store.list()[0]["scope"], ["backend/export.py"])

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
                    return [{"id": 1, "name": "CI", "status": "completed", "conclusion": "success"}]
                return []

        client = RecordingClient()
        self.assertEqual(client.list_issues("acme", "app"), [])
        self.assertEqual(client.list_pull_requests("acme", "app"), [])
        self.assertEqual(client.list_workflow_runs("acme", "app"), [
            {"id": 1, "name": "CI", "status": "completed", "conclusion": "success"}
        ])
        self.assertEqual([item[0] for item in client.paths], [
            "/repos/acme/app/issues", "/repos/acme/app/pulls",
            "/repos/acme/app/actions/runs",
        ])
        with self.assertRaises(ValueError):
            client.list_issues("acme", "app", state="all")

    def test_rest_client_parses_and_paginates_actions_run_envelopes(self):
        import json
        from unittest.mock import patch
        from development_github_intake import GitHubReadOnlyClient

        class Response:
            def __init__(self, payload, link=""):
                self.payload = payload
                self.headers = {"Link": link}

            def read(self):
                return json.dumps(self.payload).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        second_page = (
            "https://api.github.com/repos/acme/app/actions/runs?per_page=100&page=2"
        )
        pages = [
            Response(
                {"total_count": 2, "workflow_runs": [
                    {"id": 101, "name": "Backend tests", "status": "completed",
                     "conclusion": "success", "head_sha": "a" * 40}
                ]},
                f'<{second_page}>; rel="next"',
            ),
            Response(
                {"total_count": 2, "workflow_runs": [
                    {"id": 102, "name": "Backend tests", "status": "completed",
                     "conclusion": "failure", "head_sha": "b" * 40}
                ]},
            ),
        ]
        with patch("urllib.request.urlopen", side_effect=pages) as request:
            client = GitHubReadOnlyClient("test-token")
            runs = client.list_workflow_runs("acme", "app")

        self.assertEqual([run["id"] for run in runs], [101, 102])
        self.assertEqual([run["conclusion"] for run in runs], ["success", "failure"])
        self.assertEqual(request.call_count, 2)
        self.assertTrue(all(call.args[0].get_method() == "GET" for call in request.call_args_list))

    def test_rest_client_requires_token(self):
        from development_github_intake import GitHubReadOnlyClient
        with self.assertRaises(ValueError):
            GitHubReadOnlyClient(" ")


if __name__ == "__main__":
    unittest.main()
