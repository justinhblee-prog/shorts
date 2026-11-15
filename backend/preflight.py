"""Configuration-only readiness report; never exposes secret values."""
import os
from pathlib import Path

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
        "tiktok_oauth": [
            "TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET",
            "TIKTOK_REDIRECT_URI", "TIKTOK_TOKEN_ENCRYPTION_KEY",
        ],
    }
    checks = {}
    missing = []
    for group, keys in requirements.items():
        absent = [key for key in keys if not str(source.get(key, "")).strip()]
        checks[group] = {"configured": not absent, "missing": absent}
        if group != "tiktok_oauth" or not str(source.get("TIKTOK_ACCESS_TOKEN", "")).strip():
            missing.extend(absent)
    static_tiktok = bool(str(source.get("TIKTOK_ACCESS_TOKEN", "")).strip())
    oauth_tiktok = checks["tiktok_oauth"]["configured"]
    checks["tiktok_publish"] = {
        "configured": static_tiktok or oauth_tiktok,
        "mode": "static_env" if static_tiktok else ("oauth" if oauth_tiktok else "unconfigured"),
        "missing": [] if static_tiktok or oauth_tiktok else [
            "TIKTOK_ACCESS_TOKEN or complete TikTok OAuth credentials/encryption key"
        ],
    }
    missing.extend(checks["tiktok_publish"]["missing"])
    media_dir = Path(source.get("NEXUS_MEDIA_DIR", "data/media"))
    ancestor = media_dir
    while not ancestor.exists() and ancestor != ancestor.parent:
        ancestor = ancestor.parent
    writable = (not media_dir.exists() or media_dir.is_dir()) and ancestor.is_dir() and os.access(str(ancestor), os.W_OK)
    checks["media_directory"] = {"configured": writable,
        "missing": [] if writable else ["NEXUS_MEDIA_DIR (directory/parent must be writable)"]}
    generation = all(checks[k]["configured"] for k in
                     ("script_generation","voice_generation","video_rendering"))
    staging = checks["artifact_staging"]["configured"] and checks["media_directory"]["configured"]
    upload = checks["youtube_upload"]["configured"]
    tiktok_upload = checks["tiktok_publish"]["configured"]
    operation = checks["operator_auth"]["configured"]
    return {
        "checks": checks,
        "capabilities": {
            "protected_operations": operation,
            "ai_generation_configured": generation,
            "artifact_staging_configured": staging,
            "youtube_upload_configured": upload,
            "tiktok_private_publish_configured": operation and tiktok_upload,
            "end_to_end_configured": operation and generation and staging and upload
                and checks["youtube_data_api"]["configured"],
        },
        "missing": sorted(set(missing + checks["media_directory"]["missing"])),
        "live_connectivity_verified": False,
        "note": "Configuration presence only; this endpoint does not call external providers or prove OAuth, quota, rendering, upload or billing works."
    }
