import os
import tempfile
import unittest

from production_pipeline import ProductionStore
from review_workflow import ReviewStore, ReviewConflict, ReviewNotFound, valid_review_token
from queue_store import JobQueue
from queue_store import JobQueue


class ReviewWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "review.sqlite3")
        self.production = ProductionStore(self.db)
        self.queue = JobQueue(self.db)
        self.review = ReviewStore(self.db)
        self.production.create("job-1", {
            "brand": "Brain Glitch", "region": "US",
            "language": "English", "topic": "Sleep"
        })
        self.production.stage("job-1", "rendered", "review_pending")
        self.production.artifact("job-1", "rendering", "video",
                                  "https://media.example/video.mp4", {"duration": 30})

    def tearDown(self):
        self.tmp.cleanup()

    def test_pending_queue_contains_real_artifact_reference(self):
        pending = self.review.list_pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["artifacts"][0]["artifact_url"],
                         "https://media.example/video.mp4")

    def test_pending_review_exposes_frozen_brand_guidance_from_job_payload(self):
        queue = JobQueue(self.db)
        job = queue.enqueue("short_video_production", {
            "brand": "Brain Glitch", "region": "US", "language": "English",
            "topic": "Sleep", "brand_profile": {
                "positioning": "Evidence-led brain explainers",
                "audience": "curious adults", "tone": ["clear", "careful"],
                "risk_level": "high",
                "review_rules": ["Cite sources", "No diagnosis"],
            },
        })
        self.production.create(job["id"], {
            "brand": "Brain Glitch", "region": "US",
            "language": "English", "topic": "Sleep",
        })
        self.production.stage(job["id"], "rendered", "review_pending")
        pending = self.review.list_pending()
        item = next(entry for entry in pending if entry["job_id"] == job["id"])
        self.assertEqual(item["brand_profile"]["risk_level"], "high")
        self.assertEqual(item["brand_profile"]["review_rules"],
                         ["Cite sources", "No diagnosis"])
        self.assertNotIn("job_payload_json", item)

    def test_policy_review_required_needs_explicit_approval_note(self):
        self.production.artifact("job-1", "script", "text", None, {
            "script": "Example", "policy_preflight": {
                "status": "review_required",
                "required_confirmations": ["rights.visuals_cleared", "factual_claims_verified"]
            }
        })
        with self.assertRaisesRegex(ValueError, "explicit reviewer confirmation"):
            self.review.decide("job-1", "approved", "operator-1", "")
        result = self.review.decide("job-1", "approved", "operator-1",
                                    "Confirmed rights and factual claims in source records")
        self.assertEqual(result["production"]["status"], "approved")
        self.assertIn("Confirmed rights", result["decision"]["comment"])

    def test_policy_blocked_content_cannot_be_approved(self):
        self.production.artifact("job-1", "script", "text", None, {
            "script": "Example", "policy_preflight": {
                "status": "blocked", "blocking_reasons": ["known_unauthorized_assets"]
            }
        })
        with self.assertRaisesRegex(ReviewConflict, "Policy-blocked"):
            self.review.decide("job-1", "approved", "operator-1", "Reviewed")
        self.assertEqual(self.production.get("job-1")["status"], "review_pending")

    def test_approval_is_explicit_and_audited_with_snapshot(self):
        result = self.review.decide("job-1", "approved", "operator-1", "Looks good")
        self.assertEqual(result["production"]["status"], "approved")
        self.assertEqual(result["decision"]["reviewer_id"], "operator-1")
        self.assertEqual(result["decision"]["artifact_snapshot"][0]["artifact_url"],
                         "https://media.example/video.mp4")
        self.assertEqual(len(self.review.history("job-1")), 1)


    def test_approved_queue_contains_only_approved_jobs(self):
        self.review.decide("job-1", "approved", "operator-1", "Looks good")
        items = self.review.list_approved()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["job_id"], "job-1")
        self.assertEqual(items[0]["status"], "approved")
        self.assertEqual(items[0]["artifacts"][0]["artifact_type"], "video")

    def test_rejection_and_revision_require_reason(self):
        with self.assertRaises(ValueError):
            self.review.decide("job-1", "rejected", "operator-1", "")
        result = self.review.decide("job-1", "revision_requested",
                                    "operator-1", "Captions are inaccurate")
        self.assertEqual(result["production"]["status"], "revision_requested")

    def test_second_decision_cannot_overwrite_first(self):
        self.review.decide("job-1", "approved", "operator-1")
        with self.assertRaises(ReviewConflict):
            self.review.decide("job-1", "rejected", "operator-2", "Changed mind")
        self.assertEqual(len(self.review.history("job-1")), 1)

    def test_unknown_job(self):
        with self.assertRaises(ReviewNotFound):
            self.review.decide("missing", "approved", "operator-1")

    def test_review_token_fails_closed(self):
        self.assertFalse(valid_review_token("abc", None))
        self.assertFalse(valid_review_token("wrong", "secret"))
        self.assertTrue(valid_review_token("secret", "secret"))


if __name__ == "__main__":
    unittest.main()
