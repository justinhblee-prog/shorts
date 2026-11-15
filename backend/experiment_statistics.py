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
    # Round degrees of freedom DOWN to the nearest tabulated value. Using the
    # next higher row would understate the critical value and narrow the CI.
    selected = 1.96
    for boundary, value in _T95:
        if boundary > df:
            break
        selected = value
    return selected


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
    if type(randomized_assignment) is not bool or type(verified_exposure) is not bool:
        raise ValueError("verification gates must be explicit booleans")
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

def evaluate_preregistered_decision(primary, *, expected_direction,
                                    minimum_meaningful_effect, guardrails=()):
    """Apply predeclared practical-effect and non-inferiority guardrail gates.

    This only produces a review candidate. It never deploys a variant or changes
    recommendation ranking. All comparisons must already be verified, randomized
    and available from compare_experiment_arms().
    """
    if expected_direction not in ("higher", "lower"):
        raise ValueError("expected_direction must be higher or lower")
    if (isinstance(minimum_meaningful_effect, bool)
            or not isinstance(minimum_meaningful_effect, (int, float))
            or not math.isfinite(float(minimum_meaningful_effect))
            or minimum_meaningful_effect <= 0):
        raise ValueError("minimum_meaningful_effect must be a finite positive number")
    if not isinstance(primary, dict):
        raise ValueError("primary comparison must be an object")
    if not isinstance(guardrails, (list, tuple)) or len(guardrails) > 20:
        raise ValueError("guardrails must be a list containing at most 20 comparisons")
    base = {
        "status": "blocked",
        "primary_metric": primary.get("metric"),
        "expected_direction": expected_direction,
        "minimum_meaningful_effect": float(minimum_meaningful_effect),
        "guardrail_results": [],
        "ranking_score_adjustment": 0,
        "deployment_authorized": False,
    }
    comparisons = [("primary", primary)] + [
        (f"guardrail_{index + 1}", item) for index, item in enumerate(guardrails)
    ]
    for label, comparison in comparisons:
        if (not isinstance(comparison, dict)
                or comparison.get("status") != "comparison_available"
                or comparison.get("randomized_assignment_verified") is not True
                or comparison.get("served_exposure_verified") is not True
                or not isinstance(comparison.get("confidence_interval"), list)
                or len(comparison["confidence_interval"]) != 2):
            return {
                **base, "status": "blocked_missing_verified_comparison",
                "reason": f"{label} comparison is not backed by verified randomized served-exposure evidence.",
            }
        low, high = comparison["confidence_interval"]
        if (any(isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(float(value)) for value in (low, high))
                or low > high):
            return {**base, "status": "blocked_invalid_confidence_interval",
                    "reason": f"{label} confidence interval is invalid."}
    primary_low, primary_high = primary["confidence_interval"]
    threshold = float(minimum_meaningful_effect)
    if expected_direction == "higher":
        primary_pass = primary_low > threshold
    else:
        primary_pass = primary_high < -threshold
    if not primary_pass:
        return {
            **base, "status": "inconclusive_practical_effect",
            "primary_confidence_interval": [primary_low, primary_high],
            "reason": "The full primary 95% confidence interval does not exceed the pre-registered practical-effect threshold.",
        }
    guardrail_results = []
    for index, comparison in enumerate(guardrails):
        margin = comparison.get("allowed_degradation")
        if (isinstance(margin, bool) or not isinstance(margin, (int, float))
                or not math.isfinite(float(margin)) or margin < 0):
            raise ValueError("each guardrail needs a finite non-negative allowed_degradation")
        low, high = comparison["confidence_interval"]
        passed = low >= -float(margin)
        guardrail_results.append({
            "metric": str(comparison.get("metric", f"guardrail_{index + 1}"))[:128],
            "allowed_degradation": float(margin),
            "confidence_interval": [low, high],
            "passed": passed,
        })
        if not passed:
            return {
                **base, "status": "blocked_guardrail_regression",
                "primary_confidence_interval": [primary_low, primary_high],
                "guardrail_results": guardrail_results,
                "reason": "At least one guardrail confidence interval permits degradation beyond its pre-registered margin.",
            }
    return {
        **base, "status": "review_candidate",
        "primary_confidence_interval": [primary_low, primary_high],
        "guardrail_results": guardrail_results,
        "reason": "Practical-effect and guardrail gates passed; independent human review is still required. No rollout or ranking change is authorized.",
    }
