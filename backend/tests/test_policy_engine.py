import unittest
from policy_engine import evaluate_content_policy


class PolicyEngineTests(unittest.TestCase):
    def test_unknown_rights_and_disclosure_are_review_requirements_not_fake_passes(self):
        report = evaluate_content_policy({"brand": "Brain Glitch", "topic": "Sleep"})
        self.assertEqual(report["status"], "review_required")
        self.assertIn("rights.visuals_cleared", report["required_confirmations"])
        self.assertIn("synthetic_media_status", report["required_confirmations"])
        self.assertNotIn("compliant", report["status"])

    def test_explicit_unauthorized_asset_blocks_preproduction(self):
        report = evaluate_content_policy({"policy_flags": {"known_unauthorized_assets": True}})
        self.assertEqual(report["status"], "blocked")
        self.assertIn("known_unauthorized_assets", report["blocking_reasons"])

    def test_complete_attestations_only_advance_to_human_review(self):
        report = evaluate_content_policy({
            "rights": {"visuals_cleared": True, "audio_cleared": True,
                       "likeness_authorized": True},
            "synthetic_media_status": "ai_generated",
            "ai_disclosure_acknowledged": True,
            "factual_claims_verified": True,
            "originality_notes": "Original explanatory narrative and examples.",
        })
        self.assertEqual(report["status"], "ready_for_human_review")
        self.assertEqual(report["platforms"], ["youtube", "tiktok"])
        self.assertTrue(report["limitations"])

    def test_explicit_denial_of_asset_rights_blocks(self):
        report = evaluate_content_policy({"rights": {"visuals_cleared": False}})
        self.assertEqual(report["status"], "blocked")
        self.assertIn("rights.visuals_cleared", report["blocking_reasons"])

    def test_invalid_platform_or_media_status_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_content_policy({"platforms": ["youtube", "unknown"]})
        with self.assertRaises(ValueError):
            evaluate_content_policy({"synthetic_media_status": "maybe"})


if __name__ == "__main__":
    unittest.main()
