import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from production_quality import evaluate_production_quality


class ProductionQualityTests(unittest.TestCase):
    def test_complete_provider_metadata_is_ready_only_for_human_review(self):
        report = evaluate_production_quality(
            "A clear opening explains the problem. Evidence supports the claim. "
            "The ending gives viewers a useful next step with a concise summary.",
            {"factual_claims_verified": True},
            {"duration_seconds": 30, "language": "en"},
            {"duration_seconds": 30, "aspect_ratio": "9:16",
             "audio_track_present": True, "subtitles_enabled": True},
            {"language": "en"},
        )
        self.assertEqual(report["status"], "ready_for_human_review")
        self.assertEqual(report["blockers"], [])
        self.assertFalse(report["automatic_publication"])
        self.assertEqual(report["score_adjustment"], 0)

    def test_missing_metadata_is_review_warning_not_false_success_or_block(self):
        report = evaluate_production_quality(
            "A short script with a hook and useful takeaway.",
            {}, {}, {}, {"trend_context": {"url": "https://news.example/story"}},
        )
        self.assertEqual(report["status"], "review_required")
        self.assertIn("trend_source_citations_not_returned_by_script_provider",
                      report["warnings"])
        self.assertIn("render_aspect_ratio_not_reported", report["warnings"])
        self.assertIn("does not download or inspect audio/video bytes",
                      report["verification_boundary"])

    def test_explicit_wrong_format_or_missing_audio_blocks_review_handoff(self):
        report = evaluate_production_quality(
            "A sufficiently long script explains the subject with an opening and ending.",
            {"factual_claims_verified": True},
            {"duration_seconds": 30},
            {"duration_seconds": 30, "aspect_ratio": "16:9",
             "audio_track_present": False, "subtitles_enabled": True},
            {},
        )
        self.assertEqual(report["status"], "blocked")
        self.assertIn("render_format_is_not_vertical_9_16", report["blockers"])
        self.assertIn("rendered_video_reports_no_audio_track", report["blockers"])


if __name__ == "__main__":
    unittest.main()
