import os
import tempfile
import unittest

from development_jobs import DevelopmentJobStore
from publish_development_reviews import publish_pending_reviews, recover_pending_reviews


HEAD_SHA = "a" * 40
PR_URL = "https://github.com/acme/app/pull/42"
HEAD_REF = "automation/nexus-development-cycle"
BASE_REF = "main"


def make_pr(head_sha=HEAD_SHA, head_ref=HEAD_REF, base_ref=BASE_REF,
            draft=True, state="open", merged_at=None, head_repo="acme/app",
            base_repo="acme/app"):
    return {
        "number": 42,
        "html_url": PR_URL,
        "state": state,
        "draft": draft,
        "merged_at": merged_at,
        "head": {"ref": head_ref, "sha": head_sha, "repo": {"full_name": head_repo}},
        "base": {"ref": base_ref, "repo": {"full_name": base_repo}},
    }


class FakeReviewClient:
    def __init__(self, pull_request=None, files=None):
        self.pull_request = pull_request or make_pr()
        self.files = files or [{"filename": "backend/example.py"}]
        self.requested = []

    def get_pull_request(self, owner, repository, number):
        self.requested.append(("pull", owner, repository, number))
        return self.pull_request

    def list_pull_request_files(self, owner, repository, number):
        self.requested.append(("files", owner, repository, number))
        return self.files

    def list_open_pull_requests(self, owner, repository):
        self.requested.append(("open", owner, repository))
        return [self.pull_request]


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
        client = FakeReviewClient(pull_request=make_pr(head_sha="b" * 40))
        with self.assertRaisesRegex(RuntimeError, "head SHA"):
            self.publish(client)
        self.assertEqual(self.store.get(self.job_id)["status"], "review_pending")

    def test_non_draft_or_closed_pr_cannot_complete_job(self):
        for pr in (
            make_pr(draft=False),
            make_pr(state="closed"),
            make_pr(merged_at="2026-11-18T00:00:00Z"),
        ):
            with self.subTest(pr=pr):
                with self.assertRaises(RuntimeError):
                    self.publish(FakeReviewClient(pull_request=pr))
                self.assertEqual(self.store.get(self.job_id)["status"], "review_pending")

    def test_wrong_head_or_base_branch_cannot_complete_job(self):
        for head_ref, base_ref in (("other-branch", BASE_REF), (HEAD_REF, "develop")):
            pr = make_pr(head_ref=head_ref, base_ref=base_ref)
            with self.subTest(head_ref=head_ref, base_ref=base_ref):
                with self.assertRaises(RuntimeError):
                    self.publish(FakeReviewClient(pull_request=pr))
                self.assertEqual(self.store.get(self.job_id)["status"], "review_pending")

    def test_fork_head_cannot_be_used_as_review_artifact(self):
        with self.assertRaisesRegex(RuntimeError, "head must belong"):
            self.publish(FakeReviewClient(pull_request=make_pr(head_repo="attacker/fork")))
        self.assertEqual(self.store.get(self.job_id)["status"], "review_pending")

    def test_pr_missing_job_change_keeps_job_pending(self):
        result = self.publish(FakeReviewClient(files=[{"filename": "backend/other.py"}]))
        self.assertEqual(result["published_count"], 0)
        self.assertEqual(result["pending_count"], 1)
        self.assertEqual(self.store.get(self.job_id)["status"], "review_pending")

    def test_recovery_verifies_existing_exact_draft_pr_without_creating_or_mutating_it(self):
        client = FakeReviewClient()
        result = recover_pending_reviews(self.store, client, "acme/app", HEAD_REF, BASE_REF)
        self.assertEqual(result["published_count"], 1)
        self.assertEqual(self.store.get(self.job_id)["status"], "completed")
        self.assertEqual(client.requested, [
            ("open", "acme", "app"), ("pull", "acme", "app", 42),
            ("files", "acme", "app", 42),
        ])

    def test_recovery_without_matching_pr_preserves_pending_job_and_history(self):
        client = FakeReviewClient(pull_request=make_pr(head_ref="unrelated-branch"))
        before = self.store.events(self.job_id)
        result = recover_pending_reviews(self.store, client, "acme/app", HEAD_REF, BASE_REF)
        self.assertEqual(result["published_count"], 0)
        self.assertEqual(result["pending_count"], 1)
        self.assertEqual(self.store.get(self.job_id)["status"], "review_pending")
        self.assertEqual(self.store.events(self.job_id), before)

    def test_recovery_with_ambiguous_matching_prs_fails_closed(self):
        class AmbiguousClient(FakeReviewClient):
            def list_open_pull_requests(self, owner, repository):
                return [make_pr(), make_pr(head_sha="b" * 40)]
        client = AmbiguousClient()
        result = recover_pending_reviews(self.store, client, "acme/app", HEAD_REF, BASE_REF)
        self.assertEqual(result["published_count"], 0)
        self.assertEqual(result["skipped"][0]["candidate_count"], 2)
        self.assertEqual(self.store.get(self.job_id)["status"], "review_pending")

    def test_recovery_with_no_pending_jobs_does_not_call_github(self):
        self.store.publish_review_artifact(
            self.job_id, PR_URL, HEAD_SHA, ["backend/example.py"],
            is_draft=True, is_open=True,
        )
        client = FakeReviewClient()
        result = recover_pending_reviews(self.store, client, "acme/app", HEAD_REF, BASE_REF)
        self.assertEqual(result["pending_count"], 0)
        self.assertEqual(client.requested, [])

    def test_repository_mismatch_is_rejected_before_github_read(self):
        client = FakeReviewClient()
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.publish(client, review_url="https://github.com/other/repo/pull/42")
        self.assertEqual(client.requested, [])
        self.assertEqual(self.store.get(self.job_id)["status"], "review_pending")


if __name__ == "__main__":
    unittest.main()
