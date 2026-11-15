import unittest
from policy_engine import evaluate_content_policy


class PolicyEngineTests(unittest.TestCase):
    def test_unknown_rights_and_disclosure_are_review_requirements_not_fake_passes(self):
        report = evaluate_content_policy({"brand": "Brain Glitch", "topic": "Sleep"})
        self.assertEqual(report["status"], "review_required")
        self.assertIn("rights.visuals_cleared", report["required_confirmations"])
        self.assertIn("synthetic_media_status", report["required_confirmations"])
        self.assertIn("synthetic_media_status", report["approval_blockers"])
        self.assertNotIn("compliant", report["status"])

    def test_explicit_unauthorized_asset_blocks_preproduction(self):
        report = evaluate_content_policy({"policy_flags": {"known_unauthorized_assets": True}})
        self.assertEqual(report["status"], "blocked")
        self.assertIn("known_unauthorized_assets", report["blocking_reasons"])

    def test_complete_attestations_and_platform_disclosures_only_advance_to_human_review(self):
        report = evaluate_content_policy({
            "rights": {"visuals_cleared": True, "audio_cleared": True,
                       "likeness_authorized": True},
            "synthetic_media_status": "ai_generated",
            "platform_disclosures": {
                "youtube_altered_content": True,
                "tiktok_ai_generated_content": True,
            },
            "factual_claims_verified": True,
            "originality_notes": "Original explanatory narrative and examples.",
        })
        self.assertEqual(report["status"], "ready_for_human_review")
        self.assertEqual(report["platforms"], ["youtube", "tiktok"])
        self.assertEqual(report["approval_blockers"], [])
        self.assertEqual(len(report["policy_sources"]), 6)
        self.assertTrue(report["limitations"])

    def test_youtube_realistic_alteration_requires_explicit_api_disclosure(self):
        base = {
            "platforms": ["youtube"],
            "synthetic_media_status": "realistic_alteration",
            "platform_disclosures": {"youtube_altered_content": True},
            "rights": {"visuals_cleared": True, "audio_cleared": True,
                       "likeness_authorized": True},
            "factual_claims_verified": True,
            "originality_notes": "Original scene.",
        }
        report = evaluate_content_policy(base)
        self.assertTrue(report["youtube_contains_synthetic_media"])
        self.assertNotIn("youtube_contains_synthetic_media", report["approval_blockers"])
        base["youtube_contains_synthetic_media"] = False
        with self.assertRaises(ValueError):
            evaluate_content_policy(base)

    def test_youtube_ai_generated_requires_realism_classification(self):
        report = evaluate_content_policy({
            "platforms": ["youtube"],
            "synthetic_media_status": "ai_generated",
            "platform_disclosures": {"youtube_altered_content": True},
            "rights": {"visuals_cleared": True, "audio_cleared": True,
                       "likeness_authorized": True},
        })
        self.assertIn("youtube_contains_synthetic_media", report["approval_blockers"])

    def test_tiktok_ai_generated_disclosure_is_separate_from_youtube_realism_field(self):
        report = evaluate_content_policy({
            "platforms": ["tiktok"],
            "synthetic_media_status": "ai_generated",
            "platform_disclosures": {"tiktok_ai_generated_content": True},
            "rights": {"visuals_cleared": True, "audio_cleared": True,
                       "likeness_authorized": True},
            "factual_claims_verified": True,
            "originality_notes": "Original stylized animation.",
        })
        self.assertIsNone(report["youtube_contains_synthetic_media"])
        self.assertEqual(report["approval_blockers"], [])

    def test_explicit_denial_of_asset_rights_blocks(self):
        report = evaluate_content_policy({"rights": {"visuals_cleared": False}})
        self.assertEqual(report["status"], "blocked")
        self.assertIn("rights.visuals_cleared", report["blocking_reasons"])

    def test_realistic_ai_requires_each_selected_platform_disclosure(self):
        report = evaluate_content_policy({
            "platforms": ["youtube", "tiktok"],
            "synthetic_media_status": "realistic_alteration",
            "rights": {"visuals_cleared": True, "audio_cleared": True,
                       "likeness_authorized": True},
        })
        self.assertIn("platform_disclosures.youtube_altered_content",
                      report["approval_blockers"])
        self.assertIn("platform_disclosures.tiktok_ai_generated_content",
                      report["approval_blockers"])

    def test_platform_specific_disclosure_only_applies_to_selected_platform(self):
        report = evaluate_content_policy({
            "platforms": ["youtube"],
            "synthetic_media_status": "ai_generated",
            "platform_disclosures": {"youtube_altered_content": True},
            "rights": {"visuals_cleared": True, "audio_cleared": True,
                       "likeness_authorized": True},
        })
        self.assertNotIn("platform_disclosures.youtube_altered_content",
                         report["required_confirmations"])
        self.assertNotIn("platform_disclosures.tiktok_ai_generated_content",
                         report["required_confirmations"])

    def test_high_impact_claims_require_source_evidence_and_are_explained(self):
        brief = {
            "risk_flags": {"financial_or_investment_claims": True},
            "factual_claims_verified": True,
            "originality_notes": "Original explanation.",
            "rights": {"visuals_cleared": True, "audio_cleared": True,
                       "likeness_authorized": True},
            "synthetic_media_status": "none",
        }
        report = evaluate_content_policy(brief)
        self.assertIn("claim_evidence_notes", report["required_confirmations"])
        self.assertEqual(report["risk_assessments"][0]["risk"],
                         "financial_or_investment_claims")
        brief["claim_evidence_notes"] = "Primary regulator source checked."
        report = evaluate_content_policy(brief)
        self.assertNotIn("claim_evidence_notes", report["required_confirmations"])

    def test_news_requires_https_source_and_invalid_flags_fail_closed(self):
        brief = {
            "risk_flags": {"current_events_or_news": True},
            "factual_claims_verified": True,
            "originality_notes": "Original reporting summary.",
            "rights": {"visuals_cleared": True, "audio_cleared": True,
                       "likeness_authorized": True},
            "synthetic_media_status": "none",
        }
        report = evaluate_content_policy(brief)
        self.assertIn("source_urls", report["required_confirmations"])
        brief["source_urls"] = ["https://news.example/story"]
        report = evaluate_content_policy(brief)
        self.assertNotIn("source_urls", report["required_confirmations"])
        with self.assertRaises(ValueError):
            evaluate_content_policy({"policy_flags": {"fake_flag": True}})
        with self.assertRaises(ValueError):
            evaluate_content_policy({"risk_flags": {"health_or_medical_claims": "yes"}})

    def test_invalid_platform_or_media_status_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_content_policy({"platforms": ["youtube", "unknown"]})
        with self.assertRaises(ValueError):
            evaluate_content_policy({"synthetic_media_status": "maybe"})


if __name__ == "__main__":
    unittest.main()
