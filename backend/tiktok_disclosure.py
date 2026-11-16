"""TikTok Content Posting API AI-generated-content disclosure mapping.

This module only maps an explicit production classification to the documented
Direct Post `is_aigc` request field. It does not publish content or grant
permission to post; the operator still owns the final disclosure decision.
"""


class TikTokDisclosureError(ValueError):
    """Raised when TikTok AIGC status cannot be safely classified."""


def build_tiktok_disclosure(synthetic_media_status):
    """Return the TikTok Direct Post disclosure field from a known media class."""
    mapping = {
        "none": False,
        "ai_assisted_nonrealistic": False,
        "ai_generated": True,
        "realistic_alteration": True,
    }
    if synthetic_media_status not in mapping:
        raise TikTokDisclosureError(
            "TikTok AI-generated-content status is unknown; classify the media before posting"
        )
    return {"is_aigc": mapping[synthetic_media_status]}
