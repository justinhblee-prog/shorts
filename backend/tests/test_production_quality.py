import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from production_quality import evaluate_production_quality


class ProductionQualityTests(unittest.TestCase):
    def test_provider_metadata_alone_requires_actual_media_inspection(self):
        report = evaluate_production_quality(
            "A clear opening explains the problem. Evidence supports the claim. "
            "The ending gives viewers a useful next step with a concise summary.",
            {"factual_claims_verified": True},
            {"duration_seconds": 30, "language": "en"},
            {"duration_seconds": 30, "aspect_ratio": "9:16",
             "audio_track_present": True, "subtitles_enabled": True},
            {"language": "en"},
        )
        self.assertEqual(report["status"], "review_required")
        self.assertIn("actual_media_bytes_not_inspected", report["warnings"])
        self.assertEqual(report["blockers"], [])
        self.assertFalse(report["automatic_publication"])
        self.assertEqual(report["score_adjustment"], 0)

    def test_complete_media_inspection_can_clear_actual_media_warning(self):
        report = evaluate_production_quality(
            "A clear opening explains the problem. Evidence supports the claim. "
            "The ending gives viewers a useful next step with a concise summary.",
            {"factual_claims_verified": True},
            {"duration_seconds": 30},
            {"duration_seconds": 30, "aspect_ratio": "9:16",
             "audio_track_present": True, "subtitles_enabled": True},
            {},
            media_inspection={
                "status": "inspected", "inspection_method": "ffprobe_file_bytes",
                "duration_seconds": 30, "width": 1080, "height": 1920,
                "audio_track_present": True, "video_codec": "h264",
                "audio_codec": "aac", "subtitle_stream_present": True,
            },
        )
        self.assertEqual(report["status"], "ready_for_human_review")
        self.assertNotIn("actual_media_bytes_not_inspected", report["warnings"])
        self.assertEqual(report["checks"][-1]["status"], "inspected")

    def test_missing_metadata_is_review_warning_not_false_success_or_block(self):
        report = evaluate_production_quality(
            "A short script with a hook and useful takeaway.",
            {}, {}, {}, {"trend_context": {"url": "https://news.example/story"}},
        )
        self.assertEqual(report["status"], "review_required")
        self.assertIn("trend_source_citations_not_returned_by_script_provider",
                      report["warnings"])
        self.assertIn("render_aspect_ratio_not_reported", report["warnings"])
        self.assertIn("When configured, staged video bytes are inspected with ffprobe",
                      report["verification_boundary"])
        self.assertIn("does not verify burned-in caption text",
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
