import unittest
from datetime import datetime, timedelta, timezone

from artifact_retention import evaluate_retention_candidate


class ArtifactRetentionEligibilityTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
        self.policy = {
            "policy_version": "test-policy-v1",
            "retention_days": {"workspace_asset": 30, "render_artifact": 90},
            "grace_days": 7,
        }
        self.asset = {
            "id": "asset_test",
            "data_class": "workspace_asset",
            "created_at": (self.now - timedelta(days=40)).isoformat(),
            "asset_status": "active",
            "scan_status": "clean",
            "reference_check_complete": True,
            "active_reference_count": 0,
            "snapshot_reference_count": 0,
            "legal_hold": False,
            "integrity_verified": True,
            "storage_state_known": True,
            "backup_state_known": True,
        }

    def test_returns_review_eligible_only_after_expiry_and_grace(self):
        result = evaluate_retention_candidate(self.asset, self.policy, now=self.now)
        self.assertTrue(result["eligible_for_review"])
        self.assertEqual(result["decision"], "eligible_for_review")
        self.assertEqual(result["policy_version"], "test-policy-v1")
        self.assertFalse(result["destructive_action_performed"])
        self.assertEqual(result["reason_codes"], [])

    def test_retention_and_grace_windows_are_separate(self):
        recent = {**self.asset, "created_at": (self.now - timedelta(days=20)).isoformat()}
        result = evaluate_retention_candidate(recent, self.policy, now=self.now)
        self.assertIn("retention_period_not_elapsed", result["reason_codes"])
        grace = {**self.asset, "created_at": (self.now - timedelta(days=33)).isoformat()}
        result = evaluate_retention_candidate(grace, self.policy, now=self.now)
        self.assertIn("grace_period_active", result["reason_codes"])

    def test_unknown_or_present_references_and_legal_holds_fail_closed(self):
        for mutation, reason in (
            ({"reference_check_complete": False}, "reference_check_incomplete"),
            ({"active_reference_count": 1}, "active_references_present"),
            ({"snapshot_reference_count": 1}, "immutable_snapshot_references_present"),
            ({"legal_hold": True}, "legal_hold_active"),
            ({"legal_hold": None}, "legal_hold_state_unknown"),
        ):
            candidate = {**self.asset, **mutation}
            with self.subTest(mutation=mutation):
                result = evaluate_retention_candidate(candidate, self.policy, now=self.now)
                self.assertFalse(result["eligible_for_review"])
                self.assertIn(reason, result["reason_codes"])

    def test_unknown_integrity_storage_or_backup_state_fails_closed(self):
        for mutation, reason in (
            ({"integrity_verified": False}, "integrity_unverified"),
            ({"storage_state_known": False}, "storage_state_unknown"),
            ({"backup_state_known": False}, "backup_implications_unknown"),
        ):
            with self.subTest(mutation=mutation):
                result = evaluate_retention_candidate(
                    {**self.asset, **mutation}, self.policy, now=self.now
                )
                self.assertIn(reason, result["reason_codes"])
                self.assertFalse(result["eligible_for_review"])

    def test_pending_asset_scan_and_unknown_asset_state_fail_closed(self):
        for mutation, reason in (
            ({"scan_status": "pending"}, "asset_scan_pending"),
            ({"scan_status": "unknown"}, "asset_scan_state_unknown"),
            ({"asset_status": "deleted"}, "asset_not_active"),
        ):
            with self.subTest(mutation=mutation):
                result = evaluate_retention_candidate(
                    {**self.asset, **mutation}, self.policy, now=self.now
                )
                self.assertIn(reason, result["reason_codes"])

    def test_render_artifact_requires_terminal_review(self):
        artifact = {
            **self.asset,
            "id": "rart_test",
            "data_class": "render_artifact",
            "review_status": "pending",
        }
        result = evaluate_retention_candidate(artifact, self.policy, now=self.now)
        self.assertIn("review_not_terminal", result["reason_codes"])
        approved = {**artifact, "review_status": "approved"}
        self.assertTrue(
            evaluate_retention_candidate(approved, self.policy, now=self.now)["eligible_for_review"]
        )

    def test_missing_or_invalid_policy_and_timestamps_fail_closed(self):
        for policy in (
            {},
            {**self.policy, "policy_version": ""},
            {**self.policy, "retention_days": {}},
            {**self.policy, "retention_days": {"workspace_asset": 0}},
            {**self.policy, "grace_days": -1},
        ):
            result = evaluate_retention_candidate(self.asset, policy, now=self.now)
            self.assertFalse(result["eligible_for_review"])
        naive = {**self.asset, "created_at": "2026-01-01T00:00:00"}
        self.assertIn(
            "created_at_invalid",
            evaluate_retention_candidate(naive, self.policy, now=self.now)["reason_codes"],
        )
        self.assertIn(
            "evaluation_time_invalid",
            evaluate_retention_candidate(self.asset, self.policy, now=datetime(2026, 11, 21))["reason_codes"],
        )

    def test_immutable_provenance_classes_are_not_purge_candidates(self):
        snapshot = {**self.asset, "data_class": "edl_snapshot"}
        result = evaluate_retention_candidate(snapshot, self.policy, now=self.now)
        self.assertFalse(result["eligible_for_review"])
        self.assertIn("unsupported_data_class", result["reason_codes"])

    def test_unhashable_candidate_fields_fail_closed_without_exceptions(self):
        for mutation, reason in (
            ({"data_class": []}, "unsupported_data_class"),
            ({"scan_status": []}, "asset_scan_state_unknown"),
        ):
            candidate = {**self.asset, **mutation}
            with self.subTest(mutation=mutation):
                result = evaluate_retention_candidate(candidate, self.policy, now=self.now)
                self.assertFalse(result["eligible_for_review"])
                self.assertIn(reason, result["reason_codes"])
        artifact = {
            **self.asset, "data_class": "render_artifact",
            "review_status": [],
        }
        result = evaluate_retention_candidate(artifact, self.policy, now=self.now)
        self.assertIn("review_not_terminal", result["reason_codes"])

    def test_invalid_candidate_shape_fails_closed(self):
        result = evaluate_retention_candidate(None, self.policy, now=self.now)
        self.assertFalse(result["eligible_for_review"])
        self.assertIn("candidate_invalid", result["reason_codes"])


if __name__ == "__main__":
    unittest.main()
