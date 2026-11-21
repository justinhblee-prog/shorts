"""Read-only retention eligibility evaluation.

This module never deletes files, changes database rows or schedules a purge.
Callers must provide an explicit, versioned policy and verified reference,
hold, storage and backup state. Unknown inputs fail closed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


_RETENTION_CLASSES = {"workspace_asset", "render_artifact"}
_TERMINAL_REVIEWS = {"approved", "rejected", "revision_requested"}


def _aware_datetime(value):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        raw = value.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _bounded_days(value, *, allow_zero):
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    minimum = 0 if allow_zero else 1
    if not minimum <= value <= 3650:
        return None
    return value


def evaluate_retention_candidate(candidate, policy, *, now):
    """Return a deterministic, read-only eligibility assessment.

    `eligible_for_review` means a candidate may be considered by a separately
    approved tombstone workflow. It is not authorization to delete a binary.
    The policy must explicitly contain policy_version, retention_days for the
    candidate class and grace_days. Candidate state must explicitly attest
    complete reference checks, no active/snapshot references, no legal hold,
    verified integrity, known storage state and known backup implications.
    """
    reasons = []
    if not isinstance(candidate, dict):
        candidate = {}
        reasons.append("candidate_invalid")
    if not isinstance(policy, dict):
        policy = {}
        reasons.append("policy_invalid")

    candidate_id = candidate.get("id")
    if not isinstance(candidate_id, str) or not candidate_id.strip():
        reasons.append("candidate_id_missing")
        candidate_id = None

    data_class = candidate.get("data_class")
    if not isinstance(data_class, str) or data_class not in _RETENTION_CLASSES:
        reasons.append("unsupported_data_class")

    policy_version = policy.get("policy_version")
    if not isinstance(policy_version, str) or not policy_version.strip():
        reasons.append("policy_version_missing")
        policy_version = None

    retention_map = policy.get("retention_days")
    retention_days = None
    if not isinstance(data_class, str) or not isinstance(retention_map, dict) or data_class not in retention_map:
        reasons.append("retention_period_missing")
    else:
        retention_days = _bounded_days(retention_map.get(data_class), allow_zero=False)
        if retention_days is None:
            reasons.append("retention_period_invalid")

    grace_days = _bounded_days(policy.get("grace_days"), allow_zero=True)
    if grace_days is None:
        reasons.append("grace_period_invalid")

    created_at = _aware_datetime(candidate.get("created_at"))
    if created_at is None:
        reasons.append("created_at_invalid")
    evaluation_time = _aware_datetime(now)
    if evaluation_time is None:
        reasons.append("evaluation_time_invalid")

    if candidate.get("reference_check_complete") is not True:
        reasons.append("reference_check_incomplete")
    active_refs = candidate.get("active_reference_count")
    if isinstance(active_refs, bool) or not isinstance(active_refs, int) or active_refs < 0:
        reasons.append("active_reference_count_unknown")
    elif active_refs:
        reasons.append("active_references_present")
    snapshot_refs = candidate.get("snapshot_reference_count")
    if isinstance(snapshot_refs, bool) or not isinstance(snapshot_refs, int) or snapshot_refs < 0:
        reasons.append("snapshot_reference_count_unknown")
    elif snapshot_refs:
        reasons.append("immutable_snapshot_references_present")

    if not isinstance(candidate.get("legal_hold"), bool):
        reasons.append("legal_hold_state_unknown")
    elif candidate["legal_hold"]:
        reasons.append("legal_hold_active")
    if candidate.get("integrity_verified") is not True:
        reasons.append("integrity_unverified")
    if candidate.get("storage_state_known") is not True:
        reasons.append("storage_state_unknown")
    if candidate.get("backup_state_known") is not True:
        reasons.append("backup_implications_unknown")

    if data_class == "workspace_asset":
        if candidate.get("asset_status") != "active":
            reasons.append("asset_not_active")
        scan_status = candidate.get("scan_status")
        if scan_status == "pending":
            reasons.append("asset_scan_pending")
        elif not isinstance(scan_status, str) or scan_status not in {"clean", "rejected"}:
            reasons.append("asset_scan_state_unknown")
    elif data_class == "render_artifact":
        review_status = candidate.get("review_status")
        if not isinstance(review_status, str) or review_status not in _TERMINAL_REVIEWS:
            reasons.append("review_not_terminal")

    expires_at = None
    eligible_after = None
    if created_at is not None and retention_days is not None and grace_days is not None:
        expires_at = created_at + timedelta(days=retention_days)
        eligible_after = expires_at + timedelta(days=grace_days)
        if evaluation_time is not None:
            if evaluation_time < expires_at:
                reasons.append("retention_period_not_elapsed")
            elif evaluation_time < eligible_after:
                reasons.append("grace_period_active")

    reasons = sorted(set(reasons))
    return {
        "candidate_id": candidate_id,
        "data_class": data_class if isinstance(data_class, str) else None,
        "policy_version": policy_version,
        "decision": "not_eligible" if reasons else "eligible_for_review",
        "eligible_for_review": not reasons,
        "reason_codes": reasons,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "eligible_after": eligible_after.isoformat() if eligible_after else None,
        "evaluation_time": evaluation_time.isoformat() if evaluation_time else None,
        "destructive_action_performed": False,
    }
