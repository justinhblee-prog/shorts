import math
import unittest

from experiment_statistics import _critical_95, compare_experiment_arms


class ExperimentStatisticsTests(unittest.TestCase):
    def test_shadow_assignments_never_produce_effect_estimate(self):
        result = compare_experiment_arms(
            [1] * 40, [2] * 40,
            randomized_assignment=False, verified_exposure=False,
        )
        self.assertEqual(result["status"], "blocked_no_verified_randomized_exposure")
        self.assertIsNone(result["effect_estimate"])
        self.assertIsNone(result["confidence_interval"])
        self.assertEqual(result["ranking_score_adjustment"], 0)

    def test_client_render_acknowledgement_alone_is_not_randomized_exposure(self):
        result = compare_experiment_arms(
            list(range(40)), list(range(1, 41)),
            randomized_assignment=False, verified_exposure=True,
        )
        self.assertEqual(result["status"], "blocked_no_verified_randomized_exposure")
        self.assertIsNone(result["effect_estimate"])

    def test_insufficient_arm_sample_is_blocked(self):
        result = compare_experiment_arms(
            [1] * 29, [2] * 30,
            randomized_assignment=True, verified_exposure=True,
        )
        self.assertEqual(result["status"], "insufficient_sample")
        self.assertIsNone(result["effect_estimate"])

    def test_welch_comparison_returns_difference_and_interval(self):
        control = [float(value) for value in range(30)]
        treatment = [value + 5 for value in control]
        result = compare_experiment_arms(
            control, treatment,
            randomized_assignment=True, verified_exposure=True,
        )
        self.assertEqual(result["status"], "comparison_available")
        self.assertEqual(result["effect_estimate"], 5.0)
        self.assertLess(result["confidence_interval"][0], 5.0)
        self.assertGreater(result["confidence_interval"][1], 5.0)
        self.assertIsNone(result["p_value"])
        self.assertEqual(result["ranking_score_adjustment"], 0)

    def test_non_finite_boolean_and_string_outcomes_rejected(self):
        for bad in (True, float("nan"), float("inf"), "4"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    compare_experiment_arms(
                        [1, bad], [2, 3],
                        randomized_assignment=True, verified_exposure=True,
                        minimum_per_arm=2,
                    )

    def test_zero_variance_is_inconclusive(self):
        result = compare_experiment_arms(
            [1] * 30, [2] * 30,
            randomized_assignment=True, verified_exposure=True,
        )
        self.assertEqual(result["status"], "inconclusive_zero_variance")
        self.assertIsNone(result["effect_estimate"])

    def test_critical_value_rounds_degrees_of_freedom_down_conservatively(self):
        # At df=11, use the df=10 critical value, not the smaller df=12 value.
        self.assertEqual(_critical_95(11), 2.228)
        self.assertEqual(_critical_95(14), 2.179)
        self.assertEqual(_critical_95(16), 2.131)
        self.assertGreaterEqual(_critical_95(11), _critical_95(12))

    def test_verification_gates_must_be_explicit_booleans(self):
        for invalid in (1, "yes", None):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    compare_experiment_arms(
                        [1, 2], [2, 3],
                        randomized_assignment=invalid, verified_exposure=True,
                        minimum_per_arm=2,
                    )

    def test_minimum_sample_configuration_is_bounded(self):
        for invalid in (True, 1, 10001, 2.5):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    compare_experiment_arms(
                        [1, 2], [2, 3],
                        randomized_assignment=True, verified_exposure=True,
                        minimum_per_arm=invalid,
                    )




    def test_preregistered_practical_effect_and_guardrails_create_review_candidate_only(self):
        from experiment_statistics import evaluate_preregistered_decision
        primary = {
            "metric": "views_per_hour", "status": "comparison_available",
            "randomized_assignment_verified": True, "served_exposure_verified": True,
            "confidence_interval": [4.2, 8.1],
        }
        guardrail = {
            "metric": "policy_block_rate", "status": "comparison_available",
            "randomized_assignment_verified": True, "served_exposure_verified": True,
            "confidence_interval": [-0.5, 0.2], "allowed_degradation": 1.0,
        }
        result = evaluate_preregistered_decision(
            primary, expected_direction="higher",
            minimum_meaningful_effect=3.0, guardrails=[guardrail],
        )
        self.assertEqual(result["status"], "review_candidate")
        self.assertFalse(result["deployment_authorized"])
        self.assertEqual(result["ranking_score_adjustment"], 0)
        self.assertTrue(result["guardrail_results"][0]["passed"])

    def test_practical_effect_gate_rejects_interval_crossing_threshold(self):
        from experiment_statistics import evaluate_preregistered_decision
        primary = {
            "metric": "views", "status": "comparison_available",
            "randomized_assignment_verified": True, "served_exposure_verified": True,
            "confidence_interval": [1.0, 5.0],
        }
        result = evaluate_preregistered_decision(
            primary, expected_direction="higher", minimum_meaningful_effect=2.0,
        )
        self.assertEqual(result["status"], "inconclusive_practical_effect")
        self.assertFalse(result["deployment_authorized"])

    def test_guardrail_degradation_blocks_review_candidate(self):
        from experiment_statistics import evaluate_preregistered_decision
        primary = {
            "metric": "views", "status": "comparison_available",
            "randomized_assignment_verified": True, "served_exposure_verified": True,
            "confidence_interval": [4.0, 7.0],
        }
        guardrail = {
            "metric": "negative_feedback", "status": "comparison_available",
            "randomized_assignment_verified": True, "served_exposure_verified": True,
            "confidence_interval": [-3.0, 0.2], "allowed_degradation": 1.0,
        }
        result = evaluate_preregistered_decision(
            primary, expected_direction="higher", minimum_meaningful_effect=2.0,
            guardrails=[guardrail],
        )
        self.assertEqual(result["status"], "blocked_guardrail_regression")
        self.assertFalse(result["deployment_authorized"])

    def test_shadow_or_unverified_primary_comparison_is_blocked(self):
        from experiment_statistics import evaluate_preregistered_decision
        primary = {
            "metric": "views", "status": "comparison_available",
            "randomized_assignment_verified": False, "served_exposure_verified": True,
            "confidence_interval": [4.0, 7.0],
        }
        result = evaluate_preregistered_decision(
            primary, expected_direction="higher", minimum_meaningful_effect=2.0,
        )
        self.assertEqual(result["status"], "blocked_missing_verified_comparison")

    def test_preregistered_threshold_and_guardrail_inputs_are_validated(self):
        from experiment_statistics import evaluate_preregistered_decision
        primary = {
            "metric": "views", "status": "comparison_available",
            "randomized_assignment_verified": True, "served_exposure_verified": True,
            "confidence_interval": [4.0, 7.0],
        }
        for invalid in (True, 0, -1, float("nan"), float("inf")):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    evaluate_preregistered_decision(
                        primary, expected_direction="higher",
                        minimum_meaningful_effect=invalid,
                    )


if __name__ == "__main__":
    unittest.main()
