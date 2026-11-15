import unittest

from operator_recovery import build_operator_recovery_plan


class OperatorRecoveryPlanTests(unittest.TestCase):
    def test_youtube_ambiguous_attempt_requires_remote_verification(self):
        plan = build_operator_recovery_plan(
            {"id": "job-1", "status": "review_pending"},
            {"status": "review_pending"},
            {"latest": {"decision": "approved"}},
            {"status": "reconciliation_required", "events": []}, {},
        )
        youtube = next(x for x in plan["steps"] if x["platform"] == "youtube")
        self.assertEqual(youtube["id"], "verify_youtube_remote")
        self.assertEqual(youtube["priority"], "blocking")
        self.assertIn("YouTube Studio verification",
                      youtube["requires_operator_evidence"])

    def test_late_youtube_success_uses_resolution_not_new_upload(self):
        plan = build_operator_recovery_plan(
            {"id": "job-2"}, {"status": "approved"},
            {"latest": {"decision": "approved"}},
            {"status": "late_success_review_required"}, {},
        )
        self.assertEqual(plan["steps"][0]["endpoint"],
                         "/api/youtube/uploads/{job_id}/resolve-late-result")

    def test_tiktok_inbox_handoff_is_not_treated_as_published(self):
        plan = build_operator_recovery_plan(
            {"id": "job-3"}, {"status": "approved"},
            {"latest": {"decision": "approved"}},
            {}, {"status": "send_to_inbox"},
        )
        step = next(x for x in plan["steps"] if x["platform"] == "tiktok")
        self.assertEqual(step["priority"], "informational")
        self.assertIn("not a published-post confirmation", step["instruction"])

    def test_unapproved_review_requires_human_decision(self):
        plan = build_operator_recovery_plan(
            {"id": "job-4"}, {"status": "review_pending"},
            {"latest": {"decision": "revision_requested"}}, {}, {},
        )
        self.assertFalse(plan["human_approval_current"])
        self.assertEqual(plan["steps"][0]["id"], "complete_human_review")

    def test_recovery_plan_never_authorizes_automatic_retry(self):
        plan = build_operator_recovery_plan(
            {"id": "job-5", "status": "queued"}, {"status": "approved"},
            {"latest": {"decision": "approved"}},
            {"status": "failed"}, {"status": "failed"},
        )
        self.assertTrue(plan["read_only"])
        self.assertFalse(plan["automatic_retry_performed"])
        self.assertIn("No retry is authorized", plan["retry_policy"])
        self.assertTrue(all(x["endpoint"] is None for x in plan["steps"]))


if __name__ == "__main__":
    unittest.main()
