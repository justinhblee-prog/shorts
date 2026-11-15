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

    def test_reported_dimensions_must_match_vertical_short_ratio(self):
        report = evaluate_production_quality(
            "A clear opening explains the problem with enough words for a short video.",
            {"factual_claims_verified": True},
            {"duration_seconds": 30},
            {"duration_seconds": 30, "width": 1080, "height": 1350,
             "audio_track_present": True, "subtitles_enabled": True},
            {},
        )
        self.assertEqual(report["status"], "blocked")
        self.assertIn("render_format_is_not_vertical_9_16", report["blockers"])




    def test_explicit_string_false_audio_flag_blocks_review(self):
        report = evaluate_production_quality(
            "A clear opening explains the problem. Evidence supports the claim. "
            "The ending gives viewers a useful next step with a concise summary.",
            {"factual_claims_verified": True},
            {"duration_seconds": 30},
            {"duration_seconds": 30, "aspect_ratio": "9:16",
             "audio_track_present": "false", "subtitles_enabled": "false"},
            {},
        )
        self.assertEqual(report["status"], "blocked")
        self.assertIn("rendered_video_reports_no_audio_track", report["blockers"])
        self.assertIn("rendered_subtitles_reported_disabled", report["warnings"])

    def test_decimal_vertical_aspect_ratio_is_normalized(self):
        report = evaluate_production_quality(
            "A clear opening explains the problem. Evidence supports the claim. "
            "The ending gives viewers a useful next step with a concise summary.",
            {"factual_claims_verified": True},
            {"duration_seconds": 30},
            {"duration_seconds": 30, "aspect_ratio": "0.5625",
             "width": 1080, "height": 1920, "audio_track_present": True,
             "subtitles_enabled": True},
            {},
        )
        self.assertEqual(report["status"], "ready_for_human_review")
        self.assertEqual(report["blockers"], [])

    def test_trend_source_metadata_requires_a_valid_http_url(self):
        report = evaluate_production_quality(
            "A clear opening explains the problem. Evidence supports the claim. "
            "The ending gives viewers a useful next step with a concise summary.",
            {"source_urls": ["not-a-url"], "factual_claims_verified": True},
            {"duration_seconds": 30},
            {"duration_seconds": 30, "aspect_ratio": "9:16",
             "audio_track_present": True, "subtitles_enabled": True},
            {"trend_context": {"id": "trend-1"}},
        )
        self.assertEqual(report["status"], "review_required")
        self.assertIn("trend_source_citations_invalid_or_empty", report["warnings"])

    def test_nonfinite_and_boolean_measurements_are_treated_as_missing(self):
        report = evaluate_production_quality(
            "A script with enough words to explain the subject clearly and provide a useful next step.",
            {"factual_claims_verified": True},
            {"duration_seconds": True},
            {"duration_seconds": float("nan"), "width": float("inf"),
             "height": float("inf"), "audio_track_present": True,
             "subtitles_enabled": True},
            {},
        )
        self.assertEqual(report["status"], "review_required")
        self.assertIn("voice_duration_metadata_missing_or_invalid", report["warnings"])
        self.assertIn("render_duration_metadata_missing_or_invalid", report["warnings"])
        self.assertIn("render_aspect_ratio_not_reported", report["warnings"])
        render_check = next(item for item in report["checks"]
                            if item["name"] == "render_metadata")
        self.assertIsNone(render_check["width"])
        self.assertIsNone(render_check["height"])

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
