import unittest
from failure_analysis import classify_failure


class FailureAnalysisTests(unittest.TestCase):
    def test_provider_failure_is_ambiguous_even_when_queue_marks_retryable(self):
        result = classify_failure("provider_rendering", "gateway timed out", "short_video_production",
                                  "failed_retriable", 1, 3, True)
        self.assertEqual(result["category"], "external_outcome_ambiguous")
        self.assertEqual(result["retry_recommendation"], "blocked_pending_reconciliation")
        self.assertFalse(result["retry_authorized"])

    def test_production_lease_expiry_requires_external_reconciliation(self):
        result = classify_failure("production_lease_expired_ambiguous", job_type="short_video_production")
        self.assertEqual(result["severity"], "critical")
        self.assertEqual(result["retry_recommendation"], "blocked_pending_reconciliation")

    def test_policy_failure_requires_policy_review(self):
        result = classify_failure("policy_blocked", job_type="short_video_production")
        self.assertEqual(result["category"], "policy_or_compliance")
        self.assertEqual(result["retry_recommendation"], "blocked_pending_policy_review")

    def test_internal_error_requires_fix_not_retry(self):
        result = classify_failure("pipeline_internal_error", "ValueError", "short_video_production")
        self.assertEqual(result["category"], "pipeline_or_artifact_defect")
        self.assertEqual(result["retry_recommendation"], "blocked_pending_fix")

    def test_unknown_failure_fails_closed(self):
        result = classify_failure("new_unmapped_code")
        self.assertEqual(result["category"], "unclassified")
        self.assertEqual(result["retry_recommendation"], "blocked_pending_classification")
        self.assertFalse(result["retry_authorized"])

    def test_retryable_flag_never_authorizes_retry(self):
        result = classify_failure("rate_limited", status="failed_retriable",
                                  event_retryable=True)
        self.assertEqual(result["retry_recommendation"], "operator_review")
        self.assertFalse(result["retry_authorized"])
        self.assertEqual(result["actions_taken"], [])


if __name__ == "__main__":
    unittest.main()
