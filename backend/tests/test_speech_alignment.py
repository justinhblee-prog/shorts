import unittest

from speech_alignment import (
    compare_transcript_to_script, build_speech_alignment_report,
    build_caption_alignment_report, analyze_srt_timing,
)


class SpeechAlignmentTests(unittest.TestCase):
    def setUp(self):
        self.script = (
            "The human brain predicts what happens next using patterns from previous "
            "experiences. When expectations are violated, attention increases and the "
            "brain updates its model of the world."
        )

    def test_exact_transcript_is_aligned(self):
        report = compare_transcript_to_script(self.script, self.script)
        self.assertEqual(report["status"], "aligned")
        self.assertEqual(report["word_error_rate"], 0)
        self.assertEqual(report["match_rate"], 1)

    def test_missing_words_are_measured_as_edit_distance(self):
        transcript = (
            "The human brain predicts what happens next using patterns from previous "
            "experiences. Expectations are violated and attention increases."
        )
        report = compare_transcript_to_script(self.script, transcript)
        self.assertGreater(report["word_error_rate"], 0)
        self.assertLess(report["match_rate"], 1)

    def test_substantial_rewrite_is_flagged(self):
        report = compare_transcript_to_script(
            self.script,
            "Ocean researchers explore deep water habitats using specialized robotic vehicles "
            "to observe unusual species around underwater volcanic vents."
        )
        self.assertEqual(report["status"], "material_mismatch")
        self.assertGreater(report["word_error_rate"], 0.25)

    def test_punctuation_and_case_do_not_create_false_mismatch(self):
        report = compare_transcript_to_script(
            self.script.upper().replace(".", ","),
            self.script.lower(),
        )
        self.assertEqual(report["status"], "aligned")

    def test_srt_timing_reports_overlaps_gaps_and_fast_reading_cues(self):
        srt = (
            "1\n00:00:00,000 --> 00:00:02,000\n" + ("A" * 50) + "\n\n"
            "2\n00:00:01,000 --> 00:00:01,300\n" + ("B" * 100) + "\n\n"
            "3\n00:00:10,000 --> 00:00:20,000\n" + ("C" * 10) + "\n"
        )
        report = analyze_srt_timing(srt)
        self.assertEqual(report["status"], "analyzed")
        self.assertEqual(report["cue_count"], 3)
        self.assertEqual(report["overlap_count"], 1)
        self.assertEqual(report["long_gap_count"], 1)
        self.assertEqual(report["short_cue_count"], 1)
        self.assertEqual(report["long_cue_count"], 1)
        self.assertEqual(report["fast_reading_count"], 2)
        self.assertIn("subtitle_cues_overlap", report["warnings"])
        self.assertIn("subtitle_reading_speed_over_20_characters_per_second",
                      report["warnings"])

    def test_srt_timing_missing_timecodes_is_not_a_pass(self):
        report = analyze_srt_timing("Caption text with no timecodes.")
        self.assertEqual(report["status"], "not_available")
        self.assertEqual(report["cue_count"], 0)

    def test_transcript_token_limit_prevents_unbounded_edit_distance(self):
        long_text = "word " * 5001
        report = compare_transcript_to_script(long_text, long_text)
        self.assertEqual(report["status"], "too_large_to_compare")
        self.assertIsNone(report["word_error_rate"])

    def test_srt_cleanup_preserves_standalone_spoken_numbers(self):
        srt = (
            "1\n00:00:00,000 --> 00:00:02,000\n"
            "2026\n"
            "2\n00:00:02,000 --> 00:00:04,000\n"
            "The future starts now with new technology and ideas.\n"
        )
        report = build_caption_alignment_report(
            "2026 The future starts now with new technology and ideas.", srt
        )
        self.assertEqual(report["status"], "aligned")

    def test_short_text_is_not_given_a_false_pass(self):
        report = compare_transcript_to_script("Hello world", "Hello world")
        self.assertEqual(report["status"], "insufficient_text")
        self.assertIsNone(report["word_error_rate"])

    def test_report_identifies_provider_and_boundary(self):
        report = build_speech_alignment_report(self.script, self.script, "test-asr")
        self.assertEqual(report["provider"], "test-asr")
        self.assertTrue(report["transcript_available"])
        self.assertIn("not proof of factual correctness", report["warning"])


    def test_srt_caption_text_matches_asr_transcript_without_timecode_noise(self):
        srt = (
            "1\n00:00:00,000 --> 00:00:02,000\n"
            "The human brain predicts what happens next.\n\n"
            "2\n00:00:02,000 --> 00:00:04,000\n"
            "Patterns help the brain learn.\n"
        )
        reference = (
            "The human brain predicts what happens next. "
            "Patterns help the brain learn."
        )
        report = build_caption_alignment_report(
            self.script, srt, asr_transcript=reference,
        )
        self.assertEqual(report["status"], "aligned")
        self.assertEqual(report["reference"], "independent_asr_transcript")
        self.assertEqual(report["word_error_rate"], 0)

    def test_caption_mismatch_uses_generated_script_when_asr_missing(self):
        report = build_caption_alignment_report(
            self.script,
            "Ocean researchers explore deep water habitats using robotic vehicles "
            "to observe unusual species around underwater volcanic vents.",
        )
        self.assertEqual(report["reference"], "generated_script")
        self.assertEqual(report["status"], "material_mismatch")

if __name__ == "__main__":
    unittest.main()
