import unittest

from speech_alignment import compare_transcript_to_script, build_speech_alignment_report


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

    def test_short_text_is_not_given_a_false_pass(self):
        report = compare_transcript_to_script("Hello world", "Hello world")
        self.assertEqual(report["status"], "insufficient_text")
        self.assertIsNone(report["word_error_rate"])

    def test_report_identifies_provider_and_boundary(self):
        report = build_speech_alignment_report(self.script, self.script, "test-asr")
        self.assertEqual(report["provider"], "test-asr")
        self.assertTrue(report["transcript_available"])
        self.assertIn("not proof of factual correctness", report["warning"])


if __name__ == "__main__":
    unittest.main()
