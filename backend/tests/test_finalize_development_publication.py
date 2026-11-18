import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from development_jobs import DevelopmentJobStore
from finalize_development_publication import finalize


class DevelopmentPublicationFinalizerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "jobs.sqlite3"
        self.artifact = Path(self.tmp.name) / "source.zip"
        self.artifact.write_bytes(b"persisted source snapshot")
        self.store = DevelopmentJobStore(str(self.db))
        job = self.store.create("Wait for review publication", scope=["backend/module.py"])
        claim = self.store.claim_ready("worker-a")
        self.store.prepare_review(
            job["id"], "worker-a", claim["lease_token"],
            ["backend/module.py"], True, "ci://run/901",
            str(self.artifact), hashlib.sha256(self.artifact.read_bytes()).hexdigest(),
        )
        self.job_id = job["id"]
        self.sha = "e" * 40
        self.env = {
            "NEXUS_DEVELOPMENT_DB": str(self.db),
            "NEXUS_PUBLICATION_PR_URL": "https://github.com/acme/app/pull/789",
            "NEXUS_PUBLICATION_HEAD_SHA": self.sha,
            "NEXUS_PUBLICATION_BRANCH_SHA": self.sha,
            "NEXUS_PUBLICATION_FILES_JSON": json.dumps(["backend/module.py"]),
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_finalizer_persists_pr_url_and_exact_head_sha(self):
        result = finalize(self.env)
        self.assertEqual(result["completed_job_ids"], [self.job_id])
        job = DevelopmentJobStore(str(self.db)).get(self.job_id)
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["review_pr_url"], self.env["NEXUS_PUBLICATION_PR_URL"])
        self.assertEqual(job["review_head_sha"], self.sha)

    def test_finalizer_rejects_branch_and_pr_head_mismatch(self):
        env = dict(self.env)
        env["NEXUS_PUBLICATION_BRANCH_SHA"] = "f" * 40
        with self.assertRaisesRegex(RuntimeError, "head SHA"):
            finalize(env)
        self.assertEqual(self.store.get(self.job_id)["status"], "review_pending")

    def test_finalizer_keeps_pending_when_no_draft_pr_exists(self):
        with self.assertRaisesRegex(RuntimeError, "no open Draft PR"):
            finalize(self.env, allow_no_publication=True)
        self.assertEqual(self.store.get(self.job_id)["status"], "review_pending")


if __name__ == "__main__":
    unittest.main()
