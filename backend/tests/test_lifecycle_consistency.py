import unittest

from lifecycle_consistency import inspect_lifecycle_consistency


class LifecycleConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.job = {"status": "review_pending"}
        self.production = {"status": "review_pending"}
        self.review = {"latest": {"decision": "approved"}}

    def test_consistent_review_pending_job_has_no_findings(self):
        result = inspect_lifecycle_consistency(self.job, self.production, self.review)
        self.assertEqual(result["status"], "consistent")
        self.assertTrue(result["read_only"])
        self.assertFalse(result["automatic_retry_performed"])

    def test_queue_production_handoff_mismatch_is_reported(self):
        result = inspect_lifecycle_consistency(
            self.job, {"status": "rendered"}, self.review
        )
        self.assertIn("review_handoff_incomplete",
                      {item["code"] for item in result["findings"]})

    def test_approved_production_after_queue_review_handoff_is_consistent(self):
        result = inspect_lifecycle_consistency(
            self.job, {"status": "approved"}, self.review
        )
        self.assertEqual(result["status"], "consistent")
        self.assertEqual(result["findings"], [])

    def test_rejected_production_after_queue_review_handoff_is_consistent(self):
        result = inspect_lifecycle_consistency(
            self.job, {"status": "rejected"},
            {"latest": {"decision": "rejected"}},
        )
        self.assertEqual(result["status"], "consistent")
        self.assertEqual(result["findings"], [])

    def test_unapproved_publication_attempt_is_blocker(self):
        youtube = {"status": "uploaded", "events": [
            {"event_type": "upload_attempt_started"}
        ]}
        result = inspect_lifecycle_consistency(
            self.job, self.production, {"latest": {"decision": "rejected"}},
            youtube, {},
        )
        self.assertIn("publication_without_current_approval",
                      {item["code"] for item in result["findings"]})

    def test_uncertain_youtube_and_tiktok_outcomes_block_retry(self):
        result = inspect_lifecycle_consistency(
            self.job, self.production, self.review,
            {"status": "reconciliation_required", "events": []},
            {"status": "initializing", "events": []},
        )
        codes = {item["code"] for item in result["findings"]}
        self.assertIn("youtube_manual_reconciliation_required", codes)
        self.assertIn("tiktok_manual_reconciliation_required", codes)
        self.assertEqual(result["status"], "blocked")

    def test_tiktok_inbox_handoff_is_not_misreported_as_published(self):
        result = inspect_lifecycle_consistency(
            self.job, self.production, self.review,
            {}, {"status": "send_to_inbox", "events": []},
        )
        self.assertEqual(result["status"], "consistent")
        self.assertFalse(result["automatic_retry_performed"])

    def test_blocker_findings_set_top_level_status_to_blocked(self):
        result = inspect_lifecycle_consistency(
            self.job, self.production, self.review,
            {"status": "reconciliation_required", "attempt_id": "yt-1"},
            {"status": "processing", "attempt_id": "tt-1"},
        )
        self.assertEqual(result["status"], "blocked")

    def test_confirmed_success_without_video_id_is_blocked(self):
        youtube = inspect_lifecycle_consistency(
            self.job, self.production, self.review,
            {"status": "uploaded", "video_id": None}, {},
        )
        tiktok = inspect_lifecycle_consistency(
            self.job, self.production, self.review,
            {}, {"status": "publish_complete", "video_id": None},
        )
        self.assertIn(
            "youtube_success_missing_video_id",
            {item["code"] for item in youtube["findings"]},
        )
        self.assertIn(
            "tiktok_success_missing_video_id",
            {item["code"] for item in tiktok["findings"]},
        )
        self.assertEqual(youtube["status"], "blocked")
        self.assertEqual(tiktok["status"], "blocked")

    def test_running_queue_without_lease_is_blocked(self):
        result = inspect_lifecycle_consistency(
            {"status": "running"}, self.production, self.review,
        )
        self.assertEqual(result["status"], "blocked")
        self.assertIn(
            "queue_running_without_lease",
            {item["code"] for item in result["findings"]},
        )

    def test_cancelled_queue_must_match_production_terminal_state(self):
        result = inspect_lifecycle_consistency(
            {"status": "cancelled"}, {"status": "review_pending"}, self.review
        )
        self.assertIn("queue_production_terminal_mismatch",
                      {item["code"] for item in result["findings"]})


if __name__ == "__main__":
    unittest.main()
