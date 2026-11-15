"""Read-only consistency checks across queue, production, review and publishers."""

def inspect_lifecycle_consistency(job, production, review, youtube=None, tiktok=None):
    """Return deterministic findings; never mutates state or triggers remote retries."""
    findings = []
    queue_status = (job or {}).get("status")
    production_status = (production or {}).get("status")
    latest_review = (review or {}).get("latest") or {}
    decision = latest_review.get("decision")
    youtube = youtube or {}
    tiktok = tiktok or {}

    def add(code, severity, message, stage):
        findings.append({"code": code, "severity": severity,
                         "message": message, "stage": stage})

    if queue_status == "running":
        missing_lease = [
            field for field in ("worker_id", "lease_token", "lease_expires_at")
            if not (job or {}).get(field)
        ]
        if missing_lease:
            add("queue_running_without_lease", "blocker",
                "Running queue job is missing lease ownership fields: "
                + ", ".join(missing_lease), "queue")
    elif any((job or {}).get(field) for field in (
        "worker_id", "lease_token", "lease_expires_at"
    )):
        add("queue_stale_lease_fields", "blocker",
            "Non-running queue job still contains worker lease ownership fields", "queue")

    terminal_pairs = {
        "cancelled": {"cancelled"},
        "failed_terminal": {"failed_terminal"},
    }
    if queue_status in terminal_pairs and production_status not in terminal_pairs[queue_status]:
        add("queue_production_terminal_mismatch", "warning",
            "Queue and production records disagree about a terminal outcome", "production")
    # The queue intentionally remains review_pending after handoff; human review
    # updates production_runs independently to one of these durable decisions.
    if queue_status == "review_pending" and production_status not in (
        "review_pending", "approved", "rejected", "revision_requested"
    ):
        add("review_handoff_incomplete", "warning",
            "Queue completed but production is not in a recognized review lifecycle state", "production")
    if production_status == "review_pending" and queue_status != "review_pending":
        add("review_handoff_without_queue_completion", "warning",
            "Production is review-pending while the durable queue is not", "queue")

    yt_status = youtube.get("status")
    tt_status = tiktok.get("status")
    yt_events = youtube.get("events") or []
    tt_events = tiktok.get("events") or []
    yt_started = any(e.get("event_type") == "upload_attempt_started" for e in yt_events)
    tt_started = any(e.get("event_type") in (
        "operator_consent_recorded", "publish_initialization_started",
        "publication_attempt_started") for e in tt_events)
    if decision != "approved" and (yt_started or tt_started):
        add("publication_without_current_approval", "blocker",
            "A platform publication attempt exists but the latest review decision is not approved", "review")

    unresolved = {
        "reconciliation_required", "late_success_review_required",
        "initializing", "uploading", "processing", "failed_uncertain",
    }
    if yt_status in unresolved:
        add("youtube_manual_reconciliation_required", "blocker",
            "YouTube outcome is unresolved; verify YouTube Studio before any retry", "youtube")
    if yt_status in ("uploading", "reconciliation_required") and not youtube.get("attempt_id"):
        add("youtube_attempt_id_missing", "blocker",
            "YouTube upload state has no attempt identifier for safe reconciliation", "youtube")
    if yt_status == "uploaded" and not youtube.get("video_id"):
        add("youtube_success_missing_video_id", "blocker",
            "YouTube is marked uploaded without a confirmed video ID", "youtube")
    if tt_status in unresolved:
        add("tiktok_manual_reconciliation_required", "blocker",
            "TikTok outcome is unresolved; verify the creator account before any retry", "tiktok")
    if tt_status in ("initializing", "uploading", "processing", "reconciliation_required") and not tiktok.get("attempt_id"):
        add("tiktok_attempt_id_missing", "blocker",
            "TikTok publication state has no attempt identifier for safe reconciliation", "tiktok")
    if tt_status == "publish_complete" and not tiktok.get("video_id"):
        add("tiktok_success_missing_video_id", "blocker",
            "TikTok is marked publish-complete without a confirmed video ID", "tiktok")

    findings.sort(key=lambda item: ({"blocker": 0, "warning": 1}.get(item["severity"], 2), item["code"]))
    has_blocker = any(item["severity"] == "blocker" for item in findings)
    return {
        "status": "blocked" if has_blocker else "attention_required" if findings else "consistent",
        "read_only": True,
        "automatic_retry_performed": False,
        "findings": findings,
    }
