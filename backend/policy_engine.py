"""Versioned, evidence-bounded pre-production policy risk screen.

This deterministic checklist is not legal advice, moderation, or platform approval.
It evaluates declarations supplied by the operator; it does not inspect media bytes.
"""
from datetime import datetime, timezone

POLICY_VERSION = "2026-11-15.2"
POLICY_CHECKED_ON = "2026-11-15"
PLATFORMS = ("youtube", "tiktok")

POLICY_SOURCES = [
    {
        "platform": "youtube",
        "topic": "spam_fake_engagement_and_automated_repetitive_content",
        "url": "https://support.google.com/youtube/answer/2801973",
    },
    {
        "platform": "youtube",
        "topic": "original_inauthentic_and_reused_content_monetization",
        "url": "https://support.google.com/youtube/answer/1311392",
    },
    {
        "platform": "youtube",
        "topic": "realistic_altered_or_synthetic_media_disclosure",
        "url": "https://support.google.com/youtube/answer/14328491",
    },
    {
        "platform": "youtube",
        "topic": "advertiser_friendly_content",
        "url": "https://support.google.com/youtube/answer/6162278",
    },
    {
        "platform": "tiktok",
        "topic": "ai_generated_content_and_realistic_media_disclosure",
        "url": "https://support.tiktok.com/en/using-tiktok/creating-videos/ai-generated-content",
    },
    {
        "platform": "tiktok",
        "topic": "community_guidelines",
        "url": "https://www.tiktok.com/community-guidelines/en/",
    },
]

BLOCKING_FLAGS = (
    "known_unauthorized_assets",
    "nonconsensual_likeness",
    "deceptive_impersonation",
    "prohibited_content",
    "fake_engagement_or_platform_evasion",
    "child_safety_violation",
    "fraud_or_scam",
    "private_personal_data_exposure",
)

RISK_ACTIONS = {
    "health_or_medical_claims": "Require source-backed review by a qualified human; do not present diagnosis or treatment as fact without reliable evidence.",
    "financial_or_investment_claims": "Require source-backed review; avoid guaranteed returns, individualized financial advice, or unsupported performance claims.",
    "current_events_or_news": "Verify dates, primary sources, context, and regional relevance before approval.",
    "third_party_clips_or_music": "Verify asset-level rights and platform-specific music permissions; permission alone does not resolve reused-content monetization review.",
    "reused_or_compiled_content": "Document substantial original commentary, analysis, or educational/entertainment value.",
    "repetitive_or_mass_produced": "Check channel-level repetition and meaningful variation; templated mass production may be ineligible for monetization.",
    "sponsored_or_affiliate_content": "Confirm clear commercial disclosure and applicable platform branded-content settings.",
    "minors_appear": "Require child-safety and privacy review; verify permissions and avoid exploitative or identifying details.",
    "regulated_goods_or_services": "Check regional restrictions, age gating, and platform-specific regulated-goods rules.",
    "sensitive_personal_data": "Remove unnecessary personal data and verify lawful basis and consent before use.",
}


def _nonblank(value):
    return isinstance(value, str) and bool(value.strip())


def _valid_url_list(value, field):
    if not isinstance(value, list) or len(value) > 30:
        raise ValueError(f"{field} must be a list of up to 30 URLs")
    cleaned = []
    for url in value:
        if not isinstance(url, str) or not url.startswith("https://"):
            raise ValueError(f"{field} entries must be HTTPS URLs")
        cleaned.append(url.strip())
    return cleaned


def evaluate_content_policy(brief):
    if not isinstance(brief, dict):
        raise ValueError("brief must be an object")

    flags = brief.get("policy_flags") or {}
    if not isinstance(flags, dict) or any(
        key not in BLOCKING_FLAGS or not isinstance(value, bool)
        for key, value in flags.items()
    ):
        raise ValueError("policy_flags contains an unsupported flag or non-boolean value")
    blocked = [key for key in BLOCKING_FLAGS if flags.get(key) is True]

    rights = brief.get("rights") or {}
    if not isinstance(rights, dict):
        raise ValueError("rights must be an object")
    required_rights = ("visuals_cleared", "audio_cleared", "likeness_authorized")
    missing_rights = [f"rights.{key}" for key in required_rights if rights.get(key) is not True]
    denied_rights = [f"rights.{key}" for key in required_rights if rights.get(key) is False]
    blocked.extend(denied_rights)

    platforms = brief.get("platforms", list(PLATFORMS))
    if (not isinstance(platforms, list) or not platforms
            or any(item not in PLATFORMS for item in platforms)):
        raise ValueError("platforms must be a non-empty list of supported platforms")
    platforms = list(dict.fromkeys(platforms))

    synthetic = brief.get("synthetic_media_status", "unknown")
    allowed_synthetic = ("none", "ai_assisted_nonrealistic", "ai_generated",
                         "realistic_alteration", "unknown")
    if synthetic not in allowed_synthetic:
        raise ValueError("synthetic_media_status is invalid")

    disclosures = brief.get("platform_disclosures") or {}
    allowed_disclosures = {"youtube_altered_content", "tiktok_ai_generated_content"}
    if (not isinstance(disclosures, dict) or any(
        key not in allowed_disclosures or not isinstance(value, bool)
        for key, value in disclosures.items()
    )):
        raise ValueError("platform_disclosures contains an unsupported field or non-boolean value")

    required = list(missing_rights)
    approval_blockers = list(missing_rights)
    if synthetic == "unknown":
        required.append("synthetic_media_status")
        approval_blockers.append("synthetic_media_status")
    elif synthetic in ("ai_generated", "realistic_alteration"):
        disclosure_fields = {
            "youtube": "youtube_altered_content",
            "tiktok": "tiktok_ai_generated_content",
        }
        for platform in platforms:
            field = disclosure_fields[platform]
            key = f"platform_disclosures.{field}"
            if disclosures.get(field) is not True:
                required.append(key)
                approval_blockers.append(key)

    for key in BLOCKING_FLAGS:
        if flags.get(key) is True:
            blocked.append(key)

    risk_flags = brief.get("risk_flags") or {}
    if not isinstance(risk_flags, dict) or any(
        key not in RISK_ACTIONS or not isinstance(value, bool)
        for key, value in risk_flags.items()
    ):
        raise ValueError("risk_flags contains an unsupported flag or non-boolean value")
    risk_assessments = []
    for key, action in RISK_ACTIONS.items():
        if risk_flags.get(key) is True:
            risk_assessments.append({
                "risk": key,
                "severity": "elevated" if key in (
                    "health_or_medical_claims", "financial_or_investment_claims",
                    "minors_appear", "sensitive_personal_data"
                ) else "review",
                "required_action": action,
            })

    if not brief.get("factual_claims_verified") is True:
        required.append("factual_claims_verified")
    if not _nonblank(brief.get("originality_notes")):
        required.append("originality_notes")

    if risk_flags.get("health_or_medical_claims") or risk_flags.get("financial_or_investment_claims"):
        if not _nonblank(brief.get("claim_evidence_notes")):
            required.append("claim_evidence_notes")
    if risk_flags.get("current_events_or_news"):
        sources = _valid_url_list(brief.get("source_urls", []), "source_urls")
        if not sources:
            required.append("source_urls")
    else:
        sources = _valid_url_list(brief.get("source_urls", []), "source_urls")
    if risk_flags.get("reused_or_compiled_content") or risk_flags.get("repetitive_or_mass_produced"):
        if not _nonblank(brief.get("transformative_contribution")):
            required.append("transformative_contribution")
    if risk_flags.get("sponsored_or_affiliate_content") and brief.get("commercial_relationship_disclosed") is not True:
        required.append("commercial_relationship_disclosed")
    if risk_flags.get("minors_appear") and brief.get("child_safety_review_confirmed") is not True:
        required.append("child_safety_review_confirmed")

    blocked = sorted(set(blocked))
    required = sorted(set(required))
    approval_blockers = sorted(set(approval_blockers))
    status = "blocked" if blocked else ("review_required" if required else "ready_for_human_review")

    return {
        "policy_version": POLICY_VERSION,
        "policy_checked_on": POLICY_CHECKED_ON,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "platforms": platforms,
        "synthetic_media_status": synthetic,
        "platform_disclosures": {
            key: disclosures.get(key)
            for key in ("youtube_altered_content", "tiktok_ai_generated_content")
            if key in disclosures
        },
        "blocking_reasons": blocked,
        "required_confirmations": required,
        "approval_blockers": approval_blockers,
        "risk_assessments": risk_assessments,
        "evidence": {
            "claim_evidence_notes_present": _nonblank(brief.get("claim_evidence_notes")),
            "source_urls": sources,
            "transformative_contribution_present": _nonblank(brief.get("transformative_contribution")),
        },
        "policy_sources": POLICY_SOURCES,
        "limitations": [
            "Metadata-based preflight only; it does not inspect every video frame, audio segment, caption, thumbnail, or external asset.",
            "Operator declarations are not independently verified evidence.",
            "A ready result is not legal advice, platform approval, monetization eligibility, or a guarantee against enforcement.",
            "Policies and regional rules change; verify current official rules again at upload and publication time.",
        ],
    }
