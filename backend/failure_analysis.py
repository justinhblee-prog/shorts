"""Deterministic, conservative classification of persisted pipeline failures."""
from __future__ import annotations


def classify_failure(error_code, error_message="", job_type="", status="failed_terminal",
                     attempt=0, max_attempts=0, event_retryable=None):
    code = str(error_code or "unknown").strip().lower()
    message = str(error_message or "")[:2000]
    production = str(job_type or "") == "short_video_production"

    if code.startswith("provider_") or code == "production_lease_expired_ambiguous":
        category = "external_outcome_ambiguous"
        severity = "critical"
        retry = "blocked_pending_reconciliation"
        action = "공급자 대시보드와 요청 기록에서 이전 실행의 성공·실패 여부 및 중복 과금·생성 여부를 확인하십시오."
        rationale = "외부 공급자 호출은 응답 유실 후에도 작업이 완료됐을 수 있어 자동 재시도가 안전하지 않습니다."
    elif code in {"worker_lease_expired", "lease_expired"}:
        category = "worker_lease"
        severity = "high"
        retry = "operator_review"
        action = "Worker 로그와 heartbeat, 작업 산출물 및 외부 부작용 여부를 대조한 뒤 운영자가 재처리 여부를 결정하십시오."
        rationale = "Lease 만료만으로 기존 Worker가 실제 중단됐거나 외부 작업이 수행되지 않았음을 증명할 수 없습니다."
    elif code in {"worker_lease_incomplete", "worker_paused"}:
        category = "worker_control_or_ownership"
        severity = "high"
        retry = "blocked_pending_reconciliation"
        action = "Worker 소유권과 큐 중지 이벤트를 확인하고, 현재 작업 상태를 운영자가 대조하십시오."
        rationale = "작업 소유권 또는 운영 중지 상태가 불완전하여 안전한 재처리 여부를 판정할 수 없습니다."
    elif code in {"policy_blocked", "policy_preflight_blocked"} or "policy" in code:
        category = "policy_or_compliance"
        severity = "high"
        retry = "blocked_pending_policy_review"
        action = "정책 차단 사유와 최신 검수·권리·플랫폼 정책 증거를 확인하고 필요한 수정 및 재승인을 받으십시오."
        rationale = "정책 차단은 일시적 시스템 오류가 아니며 승인 없이 우회하면 안 됩니다."
    elif code in {"pipeline_internal_error", "validation_error", "invalid_artifact"}:
        category = "pipeline_or_artifact_defect"
        severity = "high"
        retry = "blocked_pending_fix"
        action = "오류 단계의 로그와 입력·산출물 검증 결과를 확인하고 결함을 수정한 후 새 검증을 수행하십시오."
        rationale = "결함이 수정되지 않은 상태의 재시도는 같은 실패를 반복할 수 있습니다."
    elif code in {"rate_limited", "provider_rate_limited"}:
        category = "provider_throttling"
        severity = "medium"
        retry = "operator_review"
        action = "공급자 제한 응답과 Retry-After 정책, 이전 요청 결과를 확인한 뒤 재시도 시점을 결정하십시오."
        rationale = "호출 제한은 일시적일 수 있지만 이전 요청 결과 확인 없이 반복 호출하면 중복 실행이나 추가 제한을 유발할 수 있습니다."
    else:
        category = "unclassified"
        severity = "high"
        retry = "blocked_pending_classification"
        action = "오류 코드와 관련 이벤트·Worker 로그를 수집하고 원인을 분류하기 전까지 재처리하지 마십시오."
        rationale = "등록되지 않은 오류 유형에는 안전한 자동 재시도 규칙이 없습니다."

    # Queue retry state is descriptive evidence only; it never authorizes a retry.
    return {
        "error_code": code,
        "category": category,
        "severity": severity,
        "message": message,
        "job_type": str(job_type or ""),
        "production_job": production,
        "queue_status": str(status or ""),
        "attempt": int(attempt or 0),
        "max_attempts": int(max_attempts or 0),
        "event_retryable": event_retryable if isinstance(event_retryable, bool) else None,
        "retry_recommendation": retry,
        "retry_authorized": False,
        "recommended_operator_action": action,
        "rationale": rationale,
        "read_only": True,
        "actions_taken": [],
    }
