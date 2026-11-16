"""Configuration-only readiness report; never exposes secret values."""
import os
from pathlib import Path


def _group(source, required, optional=()):
    missing = [key for key in required if not str(source.get(key, "")).strip()]
    optional_missing = [
        key for key in optional if not str(source.get(key, "")).strip()
    ]
    return {
        "configured": not missing,
        "missing": missing,
        "optional_missing": optional_missing,
    }


def _valid_operator_token(value):
    return (
        isinstance(value, str)
        and 32 <= len(value) <= 512
        and value == value.strip()
        and value.isascii()
        and all(32 <= ord(character) <= 126 for character in value)
    )


def build_preflight(env=None, youtube_refresh_token_configured=None):
    source = os.environ if env is None else env
    legacy_value = str(source.get("NEXUS_REVIEW_TOKEN", ""))
    legacy_present = bool(legacy_value.strip())
    legacy_review_token = _valid_operator_token(legacy_value)
    reviewer_credentials = bool(str(source.get("NEXUS_REVIEW_CREDENTIALS_JSON", "")).strip())
    role_map_configured = bool(str(source.get("NEXUS_REVIEW_ROLE_MAP_JSON", "")).strip())
    role_map_required = reviewer_credentials
    checks = {
        "operator_auth": {
            "configured": legacy_review_token or reviewer_credentials,
            "missing": (
                [] if legacy_review_token or reviewer_credentials
                else [
                    "NEXUS_REVIEW_TOKEN (must be 32-512 printable ASCII characters)"
                    if legacy_present else "NEXUS_REVIEW_TOKEN",
                    "NEXUS_REVIEW_CREDENTIALS_JSON",
                ]
            ),
            "optional_missing": [],
        },
        "operator_rbac": {
            "configured": role_map_configured or not role_map_required,
            "missing": (
                [] if role_map_configured or not role_map_required
                else ["NEXUS_REVIEW_ROLE_MAP_JSON"]
            ),
            "optional_missing": (
                [] if role_map_configured or role_map_required
                else ["NEXUS_REVIEW_ROLE_MAP_JSON"]
            ),
            "optional": not role_map_required,
        },
        # Provider bearer tokens are optional: endpoint adapters support
        # unauthenticated providers as well as bearer-authenticated providers.
        "script_generation": _group(
            source, ["SCRIPT_PROVIDER_URL"], ["SCRIPT_PROVIDER_TOKEN"]
        ),
        "voice_generation": _group(
            source, ["VOICE_PROVIDER_URL"], ["VOICE_PROVIDER_TOKEN"]
        ),
        "video_rendering": _group(
            source, ["RENDER_PROVIDER_URL"], ["RENDER_PROVIDER_TOKEN"]
        ),
        "artifact_staging": _group(source, ["RENDER_ARTIFACT_HOSTS"]),
        "youtube_upload": _group(
            source, ["YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET"]
        ),
        "youtube_data_api": _group(source, ["YOUTUBE_DATA_API_KEY"]),
    }

    youtube_oauth = _group(
        source, [], ["YOUTUBE_REDIRECT_URI", "YOUTUBE_TOKEN_ENCRYPTION_KEY"]
    )
    youtube_oauth["configured"] = not youtube_oauth["optional_missing"]
    youtube_oauth["optional"] = True
    checks["youtube_oauth"] = youtube_oauth

    refresh_configured = (
        bool(str(source.get("YOUTUBE_REFRESH_TOKEN", "")).strip())
        if youtube_refresh_token_configured is None
        else bool(youtube_refresh_token_configured)
    )
    if not refresh_configured:
        checks["youtube_upload"]["configured"] = False
        checks["youtube_upload"]["missing"].append("YOUTUBE_REFRESH_TOKEN")
    checks["youtube_upload"]["optional_missing"] = (
        [] if refresh_configured else ["Connect YouTube OAuth to store an encrypted refresh token"]
    )

    media_dir = Path(source.get("NEXUS_MEDIA_DIR", "data/media"))
    ancestor = media_dir
    while not ancestor.exists() and ancestor != ancestor.parent:
        ancestor = ancestor.parent
    writable = (
        (not media_dir.exists() or media_dir.is_dir())
        and ancestor.is_dir()
        and os.access(str(ancestor), os.W_OK)
    )
    checks["media_directory"] = {
        "configured": writable,
        "missing": []
        if writable
        else ["NEXUS_MEDIA_DIR (directory/parent must be writable)"],
        "optional_missing": [],
    }

    tiktok_oauth_keys = [
        "TIKTOK_CLIENT_KEY",
        "TIKTOK_CLIENT_SECRET",
        "TIKTOK_REDIRECT_URI",
        "TIKTOK_TOKEN_ENCRYPTION_KEY",
    ]
    tiktok_oauth_missing = [
        key for key in tiktok_oauth_keys if not str(source.get(key, "")).strip()
    ]
    tiktok_oauth = not tiktok_oauth_missing
    # OAuth is an optional connection method when the supported static-token
    # fallback is configured. Keep its omissions visible but non-blocking.
    checks["tiktok_oauth"] = {
        "configured": tiktok_oauth,
        "missing": [],
        "optional_missing": tiktok_oauth_missing,
        "optional": True,
    }
    tiktok_static = bool(str(source.get("TIKTOK_ACCESS_TOKEN", "")).strip())
    tiktok_publish = tiktok_oauth or tiktok_static

    operation = checks["operator_auth"]["configured"]
    generation = all(
        checks[key]["configured"]
        for key in ("script_generation", "voice_generation", "video_rendering")
    )
    staging = (
        checks["artifact_staging"]["configured"]
        and checks["media_directory"]["configured"]
    )
    youtube_upload = checks["youtube_upload"]["configured"]
    youtube_metrics = checks["youtube_data_api"]["configured"]

    youtube_ready = operation and generation and staging and youtube_upload
    tiktok_ready = operation and generation and staging and tiktok_publish
    missing = []
    for value in checks.values():
        missing.extend(value["missing"])

    return {
        "checks": checks,
        "capabilities": {
            "protected_operations": operation,
            "operator_rbac_configured": checks["operator_rbac"]["configured"],
            "ai_generation_configured": generation,
            "artifact_staging_configured": staging,
            "youtube_upload_configured": youtube_upload,
            "youtube_oauth_configured": checks["youtube_oauth"]["configured"],
            "youtube_metrics_configured": youtube_metrics,
            "tiktok_oauth_configured": tiktok_oauth,
            "tiktok_publish_configured": tiktok_publish,
            "end_to_end_configured": youtube_ready and youtube_metrics,
        },
        "platforms": {
            "youtube": {
                "configuration_ready": youtube_ready,
                "metrics_configured": youtube_metrics,
                "live_connectivity_verified": False,
            },
            "tiktok": {
                "configuration_ready": tiktok_ready,
                "oauth_configured": tiktok_oauth,
                "static_token_fallback": tiktok_static,
                # OAuth scopes and account capabilities are only known after
                # authorization and creator-info verification.
                "metrics_configured": False,
                "live_connectivity_verified": False,
            },
        },
        "missing": sorted(set(missing)),
        "live_connectivity_verified": False,
        "note": (
            "Configuration presence only. Optional provider bearer tokens and TikTok "
            "OAuth setup when using the static-token fallback may be omitted. This endpoint "
            "does not call external providers or prove OAuth, account scopes, quota, rendering, "
            "upload or billing works."
        ),
    }
