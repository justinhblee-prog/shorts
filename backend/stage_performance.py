"""Evidence-bounded per-job pipeline dwell-time diagnostics.

Durations are derived from durable queue transition timestamps. They describe time
spent in queue states, not provider CPU time or remote API execution time.
"""
from datetime import datetime, timezone

STATE_STAGE = {
    "queued": "queue_wait",
    "failed_retriable": "retry_wait",
    "running": "worker_execution",
    "review_pending": "human_review",
    "approved": "approved_waiting_for_publish",
    "uploaded": "published",
    "failed_terminal": "failed",
    "cancelled": "cancelled",
}


def _parse(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def build_stage_performance(job, events, now=None):
    """Summarize observed queue-state dwell times without mutating operational data."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    created = _parse(job.get("created_at"))
    updated = _parse(job.get("updated_at"))
    cursor = created
    state = None
    durations = {}
    samples = {}
    anomalies = []

    for event in events or []:
        occurred = _parse(event.get("created_at"))
        if occurred is None:
            anomalies.append("invalid_event_timestamp")
            continue
        if cursor is not None and occurred < cursor:
            anomalies.append("out_of_order_event_timestamp")
            continue
        prior = event.get("from_status") or state
        if cursor is not None and prior:
            seconds = max(0.0, (occurred - cursor).total_seconds())
            durations[prior] = durations.get(prior, 0.0) + seconds
            samples[prior] = samples.get(prior, 0) + 1
        cursor = occurred
        state = event.get("to_status") or state

    end = updated or now
    if cursor is not None and end >= cursor and state:
        seconds = max(0.0, (end - cursor).total_seconds())
        durations[state] = durations.get(state, 0.0) + seconds
        samples[state] = samples.get(state, 0) + 1

    stages = []
    for status, seconds in sorted(durations.items(), key=lambda item: item[1], reverse=True):
        stages.append({
            "status": status,
            "stage": STATE_STAGE.get(status, "unclassified"),
            "observed_seconds": round(seconds, 3),
            "sample_count": samples.get(status, 0),
        })
    total = sum(durations.values())
    bottleneck = stages[0] if stages else None
    return {
        "job_id": job.get("id"),
        "current_status": job.get("status"),
        "total_observed_seconds": round(total, 3),
        "state_durations": stages,
        "bottleneck": bottleneck,
        "measurement": "durable_queue_state_dwell",
        "limitations": [
            "Queue-state dwell time is not provider execution time.",
            "Time inside a state may include waiting, retries, and operator delays.",
            "A single job is not a statistically valid throughput or percentile cohort.",
        ],
        "data_quality_warnings": sorted(set(anomalies)),
        "read_only": True,
        "actions_taken": [],
    }
