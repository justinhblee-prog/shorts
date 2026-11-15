"""Configuration-only readiness report; never exposes secret values."""
import os
from pathlib import Path
from urllib.parse import urlsplit


PROVIDER_GROUPS = {
    "script_generation": ("SCRIPT_PROVIDER_URL", "SCRIPT_PROVIDER_TOKEN"),
    "voice_generation": ("VOICE_PROVIDER_URL", "VOICE_PROVIDER_TOKEN"),
    "video_rendering": ("RENDER_PROVIDER_URL", "RENDER_PROVIDER_TOKEN"),
}


def _provider_readiness(source, url_key, token_key):
    raw_url = str(source.get(url_key, "")).strip()
    token_present = bool(str(source.get(token_key, "")).strip())
    host = None
    endpoint_valid = False
    if raw_url:
        try:
            parsed = urlsplit(raw_url)
            host = (parsed.hostname or "").lower() or None
            loopback = host in ("localhost", "127.0.0.1", "::1")
            endpoint_valid = (
                (parsed.scheme == "https" or (parsed.scheme == "http" and loopback))
                and bool(host)
                and parsed.username is None
                and parsed.password is None
                and parsed.query == ""
                and parsed.fragment == ""
                and (parsed.port is None or 1 <= parsed.port <= 65535)
            )
        except ValueError:
            endpoint_valid = False
    configured = bool(raw_url and token_present and endpoint_valid)
    return {
        "configured": configured,
        "endpoint_valid": endpoint_valid,
        "endpoint_host": host,
        "credential_present": token_present,
        "integration_mode": "generic_json_http",
        "connectivity_verified": False,
        "live_call_verified": False,
        "verification_status": "configured_not_verified" if configured
            else "missing_or_invalid_configuration",
    }


def build_preflight(env=None):
    source = os.environ if env is None else env
    requirements = {
        "operator_auth": ["NEXUS_REVIEW_TOKEN"],
        "script_generation": ["SCRIPT_PROVIDER_URL", "SCRIPT_PROVIDER_TOKEN"],
        "voice_generation": ["VOICE_PROVIDER_URL", "VOICE_PROVIDER_TOKEN"],
        "video_rendering": ["RENDER_PROVIDER_URL", "RENDER_PROVIDER_TOKEN"],
        "artifact_staging": ["RENDER_ARTIFACT_HOSTS"],
        "youtube_upload": ["YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"],
        "youtube_data_api": ["YOUTUBE_DATA_API_KEY"],
    }
    checks = {}
    missing = []
    for group, keys in requirements.items():
        absent = [key for key in keys if not str(source.get(key, "")).strip()]
        checks[group] = {"configured": not absent, "missing": absent}
        missing.extend(absent)

    providers = {
        name: _provider_readiness(source, *keys)
        for name, keys in PROVIDER_GROUPS.items()
    }
    media_dir = Path(source.get("NEXUS_MEDIA_DIR", "data/media"))
    ancestor = media_dir
    while not ancestor.exists() and ancestor != ancestor.parent:
        ancestor = ancestor.parent
    writable = (not media_dir.exists() or media_dir.is_dir()) and ancestor.is_dir() and os.access(str(ancestor), os.W_OK)
    checks["media_directory"] = {"configured": writable,
        "missing": [] if writable else ["NEXUS_MEDIA_DIR (directory/parent must be writable)"]}
    generation = all(providers[k]["configured"] for k in PROVIDER_GROUPS)
    staging = checks["artifact_staging"]["configured"] and checks["media_directory"]["configured"]
    upload = checks["youtube_upload"]["configured"]
    operation = checks["operator_auth"]["configured"]
    return {
        "checks": checks,
        "providers": providers,
        "capabilities": {
            "protected_operations": operation,
            "ai_generation_configured": generation,
            "artifact_staging_configured": staging,
            "youtube_upload_configured": upload,
            "end_to_end_configured": operation and generation and staging and upload
                and checks["youtube_data_api"]["configured"],
        },
        "missing": sorted(set(missing + checks["media_directory"]["missing"])),
        "live_connectivity_verified": False,
        "live_provider_calls_verified": False,
        "note": (
            "Provider readiness validates URL shape and credential presence only. "
            "All three stages use the generic JSON-over-HTTP adapter; provider-specific "
            "compatibility, connectivity, live generation, OAuth, quota, upload and billing "
            "are not verified by this endpoint."
        )
    }
