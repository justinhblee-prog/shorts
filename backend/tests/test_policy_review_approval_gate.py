import json
import os
import tempfile
import unittest
from datetime import datetime, timezone

from production_pipeline import ProductionStore
from queue_store import JobQueue
from review_workflow import ReviewConflict, ReviewStore


class PolicyReviewApprovalGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "review.sqlite3")
        self.production = ProductionStore(self.db)
        self.queue = JobQueue(self.db)
        self.review = ReviewStore(self.db)
        brief = {"brand": "Test", "region": "US", "language": "English", "topic": "Test"}
        self.production.create("job-policy-gate", brief)
        self.production.stage("job-policy-gate", "rendered", "review_pending")
        now = datetime.now(timezone.utc).isoformat()
        with self.queue.db() as connection:
            connection.execute("""
                INSERT INTO pipeline_jobs
                  (id,job_type,payload_json,status,priority,attempt,max_attempts,
                   available_at,created_at,updated_at)
                VALUES(?,?,?,'review_pending',100,0,3,?,?,?)
            """, ("job-policy-gate", "short_video_production",
                  json.dumps(brief), now, now, now))
        self.production.artifact(
            "job-policy-gate", "script", "text", None,
            {"script": "Test script", "policy_preflight": {
                "status": "ready_for_human_review", "approval_blockers": []}},
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_approval_rejects_missing_policy_report(self):
        with self.review.db() as connection:
            connection.execute(
                "UPDATE production_artifacts SET metadata_json=? WHERE job_id=?",
                (json.dumps({"script": "Test script"}), "job-policy-gate"),
            )
        with self.assertRaisesRegex(ReviewConflict, "Policy preflight report is required"):
            self.review.decide("job-policy-gate", "approved", "operator", "Reviewed")
        self.assertEqual(self.production.get("job-policy-gate")["status"], "review_pending")

    def test_approval_rejects_unknown_policy_status(self):
        with self.review.db() as connection:
            connection.execute(
                "UPDATE production_artifacts SET metadata_json=? WHERE job_id=?",
                (json.dumps({"script": "Test", "policy_preflight": {
                    "status": "approved", "approval_blockers": []}}), "job-policy-gate"),
            )
        with self.assertRaisesRegex(ReviewConflict, "unsupported status"):
            self.review.decide("job-policy-gate", "approved", "operator", "Reviewed")
        self.assertEqual(self.production.get("job-policy-gate")["status"], "review_pending")

    def test_approval_rejects_malformed_blocker_collection(self):
        with self.review.db() as connection:
            connection.execute(
                "UPDATE production_artifacts SET metadata_json=? WHERE job_id=?",
                (json.dumps({"script": "Test", "policy_preflight": {
                    "status": "ready_for_human_review", "approval_blockers": "none"}}),
                 "job-policy-gate"),
            )
        with self.assertRaisesRegex(ReviewConflict, "blockers are malformed"):
            self.review.decide("job-policy-gate", "approved", "operator", "Reviewed")
        self.assertEqual(self.production.get("job-policy-gate")["status"], "review_pending")


if __name__ == "__main__":
    unittest.main()
