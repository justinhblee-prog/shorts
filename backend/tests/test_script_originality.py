import unittest

from script_originality import compare_script_text, build_script_originality_report


class ScriptOriginalityTests(unittest.TestCase):
    def setUp(self):
        self.script = (
            "The human brain predicts what happens next using patterns from previous "
            "experiences. When expectations are violated, attention increases and the "
            "brain updates its model of the world. This process helps people learn, "
            "adapt, and make decisions under uncertainty."
        )

    def test_exact_duplicate_is_detected(self):
        result = compare_script_text(self.script, self.script)
        self.assertTrue(result["comparable"])
        self.assertTrue(result["exact_match"])
        self.assertEqual(result["similarity"], 1.0)

    def test_unrelated_script_has_low_similarity(self):
        other = (
            "Deep ocean ecosystems contain unusual organisms adapted to darkness and "
            "pressure. Researchers use submersibles to study chemical energy sources "
            "and discover new species around hydrothermal vents."
        )
        result = compare_script_text(self.script, other)
        self.assertTrue(result["comparable"])
        self.assertFalse(result["exact_match"])
        self.assertLess(result["similarity"], 0.82)

    def test_short_scripts_are_not_scored(self):
        result = compare_script_text("Hook. Evidence. Takeaway.", self.script)
        self.assertFalse(result["comparable"])
        self.assertIsNone(result["similarity"])

    def test_report_lists_cross_brand_matches_but_does_not_claim_policy_violation(self):
        report = build_script_originality_report(self.script, [{
            "job_id": "previous-job", "brand": "Brain Glitch",
            "region": "US", "topic": "Brain prediction", "script": self.script,
        }])
        self.assertEqual(report["status"], "similar_content_found")
        self.assertEqual(report["similar_matches"][0]["job_id"], "previous-job")
        self.assertIn("not a copyright finding", report["warning"])

    def test_threshold_is_validated(self):
        with self.assertRaises(ValueError):
            build_script_originality_report(self.script, [], threshold=0.4)


if __name__ == "__main__":
    unittest.main()
