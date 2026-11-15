"""Per-operator review credentials with a legacy shared-token migration path."""
from __future__ import annotations
import json
import os
import secrets

class ReviewCredentialConfigurationError(ValueError):
    """Raised when operator credential configuration is unsafe or malformed."""

def _load_credentials(raw: str) -> dict[str, str]:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ReviewCredentialConfigurationError("NEXUS_REVIEW_CREDENTIALS_JSON must be a JSON object") from exc
    if not isinstance(value, dict) or not value:
        raise ReviewCredentialConfigurationError("NEXUS_REVIEW_CREDENTIALS_JSON must contain at least one reviewer")
    credentials: dict[str, str] = {}
    token_owners: set[str] = set()
    for reviewer_id, token in value.items():
        if (not isinstance(reviewer_id, str) or not reviewer_id.strip() or len(reviewer_id) > 128
                or any(ord(ch) < 32 or ord(ch) == 127 for ch in reviewer_id)):
            raise ReviewCredentialConfigurationError("Reviewer IDs must be 1-128 printable characters")
        if not isinstance(token, str) or len(token) < 32 or len(token) > 512:
            raise ReviewCredentialConfigurationError("Each reviewer token must contain 32-512 characters")
        if token in token_owners:
            raise ReviewCredentialConfigurationError("Each reviewer must have a unique token")
        token_owners.add(token)
        credentials[reviewer_id] = token
    return credentials

def resolve_review_principal(provided: str | None, *, credentials_json: str | None = None,
                             legacy_token: str | None = None) -> str | None:
    """Resolve a token to its configured reviewer identity; never trust body identity.

    Individual credentials fully replace the legacy shared token. The legacy
    path exists only for controlled migration and maps to fixed identity
    legacy-operator.
    """
    if not provided:
        return None
    if credentials_json is None:
        credentials_json = os.getenv("NEXUS_REVIEW_CREDENTIALS_JSON", "")
    if credentials_json.strip():
        credentials = _load_credentials(credentials_json)
        matched: list[str] = []
        for reviewer_id, expected in credentials.items():
            if secrets.compare_digest(str(provided), expected):
                matched.append(reviewer_id)
        return matched[0] if len(matched) == 1 else None
    if legacy_token is None:
        legacy_token = os.getenv("NEXUS_REVIEW_TOKEN")
    if legacy_token and secrets.compare_digest(str(provided), str(legacy_token)):
        return "legacy-operator"
    return None
