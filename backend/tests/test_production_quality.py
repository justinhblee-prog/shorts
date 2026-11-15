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
            speech_report={
                "status": "aligned", "provider": "test-asr",
                "script_token_count": 25, "transcript_token_count": 25,
                "word_error_rate": 0, "match_rate": 1.0,
                "threshold_word_error_rate": 0.25,
            },
        )
        self.assertEqual(report["status"], "ready_for_human_review")
        self.assertNotIn("actual_media_bytes_not_inspected", report["warnings"])
        self.assertEqual(report["checks"][-1]["status"], "inspected")

    def test_black_frame_and_audio_silence_signals_require_human_review(self):
        report = evaluate_production_quality(
            "A clear opening explains the problem. Evidence supports the claim. "
            "The ending gives viewers a useful next step with a concise summary.",
            {"factual_claims_verified": True},
            {"duration_seconds": 30},
            {"duration_seconds": 30, "aspect_ratio": "9:16",
             "audio_track_present": True, "subtitles_enabled": True},
            {},
            media_inspection={
                "status": "inspected", "duration_seconds": 30,
                "width": 1080, "height": 1920, "audio_track_present": True,
                "signal_analysis": {
                    "status": "analyzed", "black_segments": [
                        {"start_seconds": 0, "end_seconds": 3, "duration_seconds": 3}
                    ],
                    "silence_segments": [
                        {"start_seconds": 0, "end_seconds": 2, "duration_seconds": 2}
                    ],
                    "signal_warnings": [
                        "black_frame_segment_at_least_2_seconds_detected",
                        "audio_silence_segment_at_least_2_seconds_detected",
                    ],
                },
            },
        )
        self.assertEqual(report["status"], "review_required")
        self.assertEqual(report["blockers"], [])
        self.assertIn("black_frame_segment_at_least_2_seconds_detected",
                      report["warnings"])
        self.assertIn("audio_silence_segment_at_least_2_seconds_detected",
                      report["warnings"])

    def test_speech_alignment_mismatch_is_a_warning_not_automatic_rejection(self):
        report = evaluate_production_quality(
            "The human brain predicts what happens next using patterns from previous "
            "experiences. When expectations are violated, attention increases and the "
            "brain updates its model of the world.",
            {"factual_claims_verified": True},
            {"duration_seconds": 30},
            {"duration_seconds": 30, "aspect_ratio": "9:16",
             "audio_track_present": True, "subtitles_enabled": True},
            {},
            speech_report={
                "status": "material_mismatch", "provider": "test-asr",
                "script_token_count": 25, "transcript_token_count": 24,
                "word_error_rate": 0.8, "match_rate": 0.2,
                "threshold_word_error_rate": 0.25,
                "method": "test", "warning": "ASR can make mistakes.",
            },
        )
        self.assertEqual(report["status"], "review_required")
        self.assertEqual(report["blockers"], [])
        self.assertIn("spoken_audio_differs_from_generated_script",
                      report["warnings"])
        self.assertEqual(report["speech_alignment"]["provider"], "test-asr")

    def test_unconfigured_asr_is_explicitly_not_verified(self):
        report = evaluate_production_quality(
            "A clear opening explains the problem. Evidence supports the claim. "
            "The ending gives viewers a useful next step with a concise summary.",
            {"factual_claims_verified": True}, {"duration_seconds": 30},
            {"duration_seconds": 30, "aspect_ratio": "9:16",
             "audio_track_present": True, "subtitles_enabled": True}, {},
        )
        self.assertIn("speech_transcription_not_configured", report["warnings"])
        check = next(item for item in report["checks"]
                     if item["name"] == "speech_script_alignment")
        self.assertEqual(check["status"], "not_configured")

    def test_subtitle_mismatch_requires_human_review_not_auto_rejection(self):
        report = evaluate_production_quality(
            "The human brain predicts what happens next using patterns from previous "
            "experiences. When expectations are violated, attention increases and the "
            "brain updates its model of the world.",
            {"factual_claims_verified": True}, {"duration_seconds": 30},
            {"duration_seconds": 30, "aspect_ratio": "9:16",
             "audio_track_present": True, "subtitles_enabled": True}, {},
            caption_report={
                "status": "material_mismatch", "extraction_status": "extracted",
                "reference": "independent_asr_transcript",
                "subtitle_token_count": 24, "word_error_rate": 0.9,
                "match_rate": 0.1, "threshold_word_error_rate": 0.25,
            },
        )
        self.assertEqual(report["status"], "review_required")
        self.assertEqual(report["blockers"], [])
        self.assertIn("subtitle_text_differs_from_speech_or_script",
                      report["warnings"])
        self.assertEqual(report["caption_alignment"]["status"], "material_mismatch")

    def test_absent_text_subtitle_stream_is_not_mistaken_for_verified_captions(self):
        report = evaluate_production_quality(
            "A clear opening explains the problem. Evidence supports the claim. "
            "The ending gives viewers a useful next step with a concise summary.",
            {"factual_claims_verified": True}, {"duration_seconds": 30},
            {"duration_seconds": 30, "aspect_ratio": "9:16",
             "audio_track_present": True, "subtitles_enabled": True}, {},
            caption_report={
                "status": "not_present", "extraction_status": "not_present",
                "reference": "generated_script",
            },
        )
        self.assertIn("text_subtitle_stream_not_present_or_burned_in",
                      report["warnings"])

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
