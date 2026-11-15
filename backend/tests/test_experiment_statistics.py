import math
import unittest

from experiment_statistics import compare_experiment_arms


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

    def test_minimum_sample_configuration_is_bounded(self):
        for invalid in (True, 1, 10001, 2.5):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    compare_experiment_arms(
                        [1, 2], [2, 3],
                        randomized_assignment=True, verified_exposure=True,
                        minimum_per_arm=invalid,
                    )


if __name__ == "__main__":
    unittest.main()
