"""Operator-facing recovery instructions derived from durable lifecycle evidence."""

def build_operator_recovery_plan(job, production, review, youtube=None, tiktok=None):
    job = job or {}
    production = production or {}
    review = review or {}
    youtube = youtube or {}
    tiktok = tiktok or {}
    latest = review.get("latest") or {}
    approved = latest.get("decision") == "approved"
    steps = []

    def step(step_id, platform, priority, instruction, endpoint=None, method=None, requires=None):
        steps.append({
            "id": step_id, "platform": platform, "priority": priority,
            "instruction": instruction, "endpoint": endpoint, "method": method,
            "requires_operator_evidence": requires or [],
        })

    if production.get("status") == "review_pending" and not approved:
        step("complete_human_review", "review", "required",
             "A reviewer must inspect the current artifacts and record an explicit approval or rejection.",
             "/api/review/jobs/{job_id}/decision", "POST",
             ["reviewer identity", "decision", "review rationale"])

    yt_status = youtube.get("status")
    if yt_status in ("uploading", "reconciliation_required"):
        step("verify_youtube_remote", "youtube", "blocking",
             "Search YouTube Studio for the exact upload attempt and verify whether a video exists. Do not retry while the result is ambiguous.",
             "/api/youtube/uploads/{job_id}/reconcile", "POST",
             ["operator identity", "YouTube Studio verification", "uploaded/not_uploaded decision",
              "video ID when uploaded", "verification note"])
    elif yt_status == "late_success_review_required":
        step("resolve_youtube_late_success", "youtube", "blocking",
             "Compare every preserved late-success video ID with YouTube Studio, then resolve the matching ID. Do not create another upload.",
             "/api/youtube/uploads/{job_id}/resolve-late-result", "POST",
             ["operator identity", "verified video ID", "verification note"])
    elif yt_status == "failed":
        step("verify_youtube_failure_before_retry", "youtube", "required",
             "Confirm in YouTube Studio that no matching video was created and that the previous attempt is definitively failed before initiating a new upload.",
             None, None, ["operator identity", "YouTube Studio search evidence"])

    tt_status = tiktok.get("status")
    if tt_status in ("initializing", "uploading", "processing", "reconciliation_required"):
        step("refresh_tiktok_status", "tiktok", "blocking",
             "Refresh the official TikTok publish status using the stored publish ID. If the result remains ambiguous, verify in the creator account and do not retry.",
             "/api/tiktok/publications/{job_id}/refresh-status", "POST",
             ["connected TikTok account", "official publish status", "creator-account verification if ambiguous"])
    elif tt_status == "failed":
        step("verify_tiktok_failure_before_retry", "tiktok", "required",
             "Verify in the creator account that no post or inbox handoff exists before considering a new attempt.",
             None, None, ["operator identity", "creator-account verification"])
    elif tt_status == "send_to_inbox":
        step("complete_tiktok_inbox_handoff", "tiktok", "informational",
             "The content was handed to the TikTok creator inbox; this is not a published-post confirmation. Complete any required in-app steps and verify the final post.",
             None, None, ["creator-inbox review", "final post URL or explicit not-published confirmation"])

    steps.sort(key=lambda item: ({"blocking": 0, "required": 1, "informational": 2}.get(item["priority"], 3), item["id"]))
    return {
        "job_id": job.get("id"),
        "queue_status": job.get("status"),
        "production_status": production.get("status"),
        "latest_review_decision": latest.get("decision"),
        "human_approval_current": approved,
        "read_only": True,
        "automatic_retry_performed": False,
        "steps": steps,
        "retry_policy": "No retry is authorized by this plan. Verify remote absence, current approval, policy evidence, and media readiness before a separately authorized new attempt.",
    }
