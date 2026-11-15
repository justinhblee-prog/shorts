"""Deterministic, evidence-bounded pre-production policy gate.

This is a risk-screening aid, not legal advice or a platform-policy certification.
Unknown facts remain review requirements; the engine never claims platform approval.
"""
from datetime import datetime, timezone

POLICY_VERSION = "2026-11-15.1"
PLATFORMS = ("youtube", "tiktok")
BLOCKING_FLAGS = (
    "known_unauthorized_assets",
    "nonconsensual_likeness",
    "deceptive_impersonation",
    "prohibited_content",
    "fake_engagement_or_platform_evasion",
)


def evaluate_content_policy(brief):
    if not isinstance(brief, dict):
        raise ValueError("brief must be an object")
    flags = brief.get("policy_flags") or {}
    if not isinstance(flags, dict):
        raise ValueError("policy_flags must be an object")
    blocked = [key for key in BLOCKING_FLAGS if flags.get(key) is True]

    rights = brief.get("rights") or {}
    if not isinstance(rights, dict):
        raise ValueError("rights must be an object")
    required_rights = ("visuals_cleared", "audio_cleared", "likeness_authorized")
    unknown = [f"rights.{key}" for key in required_rights if rights.get(key) is not True]
    denied = [f"rights.{key}" for key in required_rights if rights.get(key) is False]
    blocked.extend(denied)

    synthetic = brief.get("synthetic_media_status", "unknown")
    if synthetic not in ("none", "ai_generated", "realistic_alteration", "unknown"):
        raise ValueError("synthetic_media_status is invalid")
    if synthetic in ("ai_generated", "realistic_alteration") and brief.get("ai_disclosure_acknowledged") is not True:
        unknown.append("ai_disclosure_acknowledged")
    if synthetic == "unknown":
        unknown.append("synthetic_media_status")
    if brief.get("factual_claims_verified") is not True:
        unknown.append("factual_claims_verified")
    if not str(brief.get("originality_notes") or "").strip():
        unknown.append("originality_notes")

    platforms = brief.get("platforms", list(PLATFORMS))
    if not isinstance(platforms, list) or not platforms or any(item not in PLATFORMS for item in platforms):
        raise ValueError("platforms must be a non-empty list of supported platforms")

    status = "blocked" if blocked else ("review_required" if unknown else "ready_for_human_review")
    return {
        "policy_version": POLICY_VERSION,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "platforms": list(dict.fromkeys(platforms)),
        "blocking_reasons": sorted(set(blocked)),
        "required_confirmations": sorted(set(unknown)),
        "limitations": [
            "Deterministic preflight only; it does not inspect every video frame, audio segment, or platform rule.",
            "A ready result is not legal advice, platform approval, monetization eligibility, or a guarantee against enforcement.",
            "Platform policies change; verify current official rules before publication."
        ],
    }
