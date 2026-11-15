"""Cohort-level, evidence-bounded pipeline performance statistics."""
from math import ceil
from stage_performance import build_stage_performance

MIN_STAGE_SAMPLES = 5


def _percentile(values, percentile):
    ordered = sorted(values)
    if not ordered:
        return None
    index = max(0, min(len(ordered) - 1, ceil(percentile * len(ordered)) - 1))
    return round(ordered[index], 3)


def build_pipeline_performance(jobs, event_map, min_samples=MIN_STAGE_SAMPLES):
    """Aggregate queue-state dwell observations; suppress weak cohort conclusions."""
    observations = {}
    stage_names = {}
    analyzed = 0
    warnings = set()
    for job in jobs or []:
        result = build_stage_performance(job, event_map.get(job.get("id"), []))
        if result["state_durations"]:
            analyzed += 1
        warnings.update(result["data_quality_warnings"])
        for item in result["state_durations"]:
            observations.setdefault(item["status"], []).append(item["observed_seconds"])
            stage_names[item["status"]] = item["stage"]

    stages = []
    for status, values in sorted(observations.items()):
        count = len(values)
        enough = count >= max(1, int(min_samples))
        stages.append({
            "status": status,
            "stage": stage_names.get(status, "unclassified"),
            "sample_count": count,
            "mean_seconds": round(sum(values) / count, 3) if enough else None,
            "median_seconds": _percentile(values, 0.5) if enough else None,
            "p90_seconds": _percentile(values, 0.9) if enough else None,
            "max_seconds": round(max(values), 3) if enough else None,
            "assessment": "measurable" if enough else "insufficient_samples",
        })
    eligible = [item for item in stages if item["assessment"] == "measurable"]
    bottleneck = max(eligible, key=lambda item: item["median_seconds"]) if eligible else None
    return {
        "cohort_jobs": len(jobs or []),
        "jobs_with_observations": analyzed,
        "minimum_samples_per_stage": max(1, int(min_samples)),
        "stages": stages,
        "bottleneck_candidate": bottleneck,
        "data_quality_warnings": sorted(warnings),
        "measurement": "durable_queue_state_dwell",
        "limitations": [
            "Queue-state dwell time includes waiting, retries, and operator delays.",
            "These measurements are not provider execution, render CPU, or remote API latency.",
            "Only jobs in the bounded queried cohort are included; this is not a lifetime census.",
            "Bottleneck candidates are suppressed until each stage has enough observations.",
        ],
        "read_only": True,
        "actions_taken": [],
    }
