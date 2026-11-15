"""Fail-closed statistical comparison for genuinely randomized experiments.

This module deliberately separates shadow assignment from served exposure. It will
not produce an effect estimate unless the caller supplies verified randomized
exposure evidence and finite, independent outcome observations for both arms.
"""
import math
import statistics


# Conservative two-sided 95% Student-t critical values by degrees of freedom.
_T95 = ((1, 12.706), (2, 4.303), (3, 3.182), (4, 2.776),
        (5, 2.571), (6, 2.447), (7, 2.365), (8, 2.306),
        (9, 2.262), (10, 2.228), (12, 2.179), (15, 2.131),
        (20, 2.086), (25, 2.060), (30, 2.042), (40, 2.021),
        (60, 2.000), (120, 1.980), (10**9, 1.960))


def _critical_95(df):
    for boundary, value in _T95:
        if df <= boundary:
            return value
    return 1.96


def _clean_sample(values, label):
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{label} outcomes must be a list")
    if len(values) > 100000:
        raise ValueError(f"{label} outcome sample exceeds the 100000 limit")
    cleaned = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{label} outcomes must contain only finite numbers")
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"{label} outcomes must contain only finite numbers")
        cleaned.append(number)
    return cleaned


def compare_experiment_arms(control, treatment, *, randomized_assignment,
                            verified_exposure, metric_name="primary_metric",
                            minimum_per_arm=30):
    """Return Welch mean-difference diagnostics, or a reasoned fail-closed result.

    This is an intention-to-treat style comparison only when each observation is
    linked to a verified served assignment. Callers must not pass shadow assignments.
    The interval is descriptive/inferential under independent observations and
    approximate Welch assumptions; it does not correct multiple testing.
    """
    control_values = _clean_sample(control, "control")
    treatment_values = _clean_sample(treatment, "treatment")
    if isinstance(minimum_per_arm, bool) or not isinstance(minimum_per_arm, int):
        raise ValueError("minimum_per_arm must be an integer")
    if not 2 <= minimum_per_arm <= 10000:
        raise ValueError("minimum_per_arm must be between 2 and 10000")
    base = {
        "metric": str(metric_name)[:128],
        "method": "welch_two_sample_mean_difference",
        "control_count": len(control_values),
        "treatment_count": len(treatment_values),
        "randomized_assignment_verified": bool(randomized_assignment),
        "served_exposure_verified": bool(verified_exposure),
        "minimum_per_arm": minimum_per_arm,
        "effect_estimate": None,
        "confidence_level": 0.95,
        "confidence_interval": None,
        "welch_t_statistic": None,
        "welch_degrees_freedom": None,
        "p_value": None,
        "ranking_score_adjustment": 0,
    }
    if not randomized_assignment or not verified_exposure:
        return {
            **base, "status": "blocked_no_verified_randomized_exposure",
            "reason": "Shadow assignment or client-only render acknowledgement is not verified randomized served exposure.",
        }
    if len(control_values) < minimum_per_arm or len(treatment_values) < minimum_per_arm:
        return {
            **base, "status": "insufficient_sample",
            "reason": "Both arms must meet the predeclared minimum sample size.",
        }
    control_mean = statistics.mean(control_values)
    treatment_mean = statistics.mean(treatment_values)
    control_var = statistics.variance(control_values)
    treatment_var = statistics.variance(treatment_values)
    control_term = control_var / len(control_values)
    treatment_term = treatment_var / len(treatment_values)
    standard_error = math.sqrt(control_term + treatment_term)
    if standard_error == 0:
        return {
            **base, "status": "inconclusive_zero_variance",
            "reason": "Both arms have zero estimated sampling variance; inferential comparison is undefined.",
        }
    df_denominator = (
        control_term * control_term / (len(control_values) - 1)
        + treatment_term * treatment_term / (len(treatment_values) - 1)
    )
    if df_denominator <= 0:
        return {**base, "status": "inconclusive_degrees_of_freedom",
                "reason": "Welch degrees of freedom could not be established."}
    degrees_freedom = (control_term + treatment_term) ** 2 / df_denominator
    difference = treatment_mean - control_mean
    t_statistic = difference / standard_error
    critical = _critical_95(degrees_freedom)
    margin = critical * standard_error
    return {
        **base,
        "status": "comparison_available",
        "effect_estimate": round(difference, 6),
        "effect_unit": "raw_metric_units",
        "confidence_interval": [round(difference - margin, 6),
                                round(difference + margin, 6)],
        "welch_t_statistic": round(t_statistic, 6),
        "welch_degrees_freedom": round(degrees_freedom, 4),
        "p_value": None,
        "reason": (
            "Welch mean difference and approximate 95% confidence interval. "
            "No p-value is reported; independence, assignment integrity, metric "
            "pre-registration and multiple-testing controls still require review."
        ),
    }
