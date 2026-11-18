import os
import tempfile
import unittest

from development_jobs import DevelopmentJobStore
from publish_development_reviews import publish_pending_reviews


HEAD_SHA = "a" * 40
PR_URL = "https://github.com/acme/app/pull/42"
HEAD_REF = "automation/nexus-development-cycle"
BASE_REF = "main"


class FakeReviewClient:
    def __init__(self, pull_request=None, files=None):
        self.pull_request = pull_request or {
            "state": "open",
            "draft": True,
            "merged_at": None,
            "head": {"ref": HEAD_REF, "sha": HEAD_SHA},
            "base": {"ref": BASE_REF},
        }
        self.files = files or [{"filename": "backend/example.py"}]
        self.requested = []

    def get_pull_request(self, owner, repository, number):
        self.requested.append(("pull", owner, repository, number))
        return self.pull_request

    def list_pull_request_files(self, owner, repository, number):
        self.requested.append(("files", owner, repository, number))
        return self.files


class PublishDevelopmentReviewsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = DevelopmentJobStore(os.path.join(self.tmp.name, "jobs.sqlite3"))
        job = self.store.create("Review artifact gate", scope=["backend/example.py"])
        lease = self.store.claim_ready("worker-a")
        self.job_id = job["id"]
        self.store.mark_review_pending(
            self.job_id, "worker-a", lease["lease_token"],
            ["backend/example.py"], True, "https://github.com/acme/app/actions/runs/99",
            "validated source and tests",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def publish(self, client=None, **overrides):
        args = {
            "store": self.store,
            "client": client or FakeReviewClient(),
            "repository": "acme/app",
            "review_url": PR_URL,
            "expected_head_sha": HEAD_SHA,
            "expected_head_ref": HEAD_REF,
            "expected_base_ref": BASE_REF,
        }
        args.update(overrides)
        return publish_pending_reviews(**args)

    def test_exact_open_draft_pr_and_changed_file_complete_job(self):
        client = FakeReviewClient()
        result = self.publish(client)
        job = self.store.get(self.job_id)
        self.assertEqual(result["published_count"], 1)
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["review_url"], PR_URL)
        self.assertEqual(job["review_head_sha"], HEAD_SHA)
        self.assertTrue(job["review_published_at"])
        self.assertEqual(client.requested, [
            ("pull", "acme", "app", 42), ("files", "acme", "app", 42)
        ])

    def test_head_sha_mismatch_leaves_job_review_pending(self):
        client = FakeReviewClient(pull_request={
            "state": "open", "draft": True, "merged_at": None,
            "head": {"ref": HEAD_REF, "sha": "b" * 40},
            "base": {"ref": BASE_REF},
        })
        with self.assertRaisesRegex(RuntimeError, "head SHA"):
            self.publish(client)
        self.assertEqual(self.store.get(self.job_id)["status"], "review_pending")

    def test_non_draft_or_closed_pr_cannot_complete_job(self):
        for pr in (
            {"state": "open", "draft": False, "merged_at": None,
             "head": {"ref": HEAD_REF, "sha": HEAD_SHA}, "base": {"ref": BASE_REF}},
            {"state": "closed", "draft": True, "merged_at": None,
             "head": {"ref": HEAD_REF, "sha": HEAD_SHA}, "base": {"ref": BASE_REF}},
            {"state": "open", "draft": True, "merged_at": "2026-11-18T00:00:00Z",
             "head": {"ref": HEAD_REF, "sha": HEAD_SHA}, "base": {"ref": BASE_REF}},
        ):
            with self.subTest(pr=pr):
                with self.assertRaises(RuntimeError):
                    self.publish(FakeReviewClient(pull_request=pr))
                self.assertEqual(self.store.get(self.job_id)["status"], "review_pending")

    def test_wrong_head_or_base_branch_cannot_complete_job(self):
        for head_ref, base_ref in (("other-branch", BASE_REF), (HEAD_REF, "develop")):
            pr = {
                "state": "open", "draft": True, "merged_at": None,
                "head": {"ref": head_ref, "sha": HEAD_SHA},
                "base": {"ref": base_ref},
            }
            with self.subTest(head_ref=head_ref, base_ref=base_ref):
                with self.assertRaises(RuntimeError):
                    self.publish(FakeReviewClient(pull_request=pr))
                self.assertEqual(self.store.get(self.job_id)["status"], "review_pending")

    def test_pr_missing_job_change_keeps_job_pending(self):
        result = self.publish(FakeReviewClient(files=[{"filename": "backend/other.py"}]))
        self.assertEqual(result["published_count"], 0)
        self.assertEqual(result["pending_count"], 1)
        self.assertEqual(self.store.get(self.job_id)["status"], "review_pending")

    def test_repository_mismatch_is_rejected_before_github_read(self):
        client = FakeReviewClient()
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.publish(client, review_url="https://github.com/other/repo/pull/42")
        self.assertEqual(client.requested, [])
        self.assertEqual(self.store.get(self.job_id)["status"], "review_pending")


if __name__ == "__main__":
    unittest.main()
