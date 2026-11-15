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
    }
    checks = {}
    missing = []
    for group, keys in requirements.items():
        absent = [key for key in keys if not str(source.get(key, "")).strip()]
        checks[group] = {"configured": not absent, "missing": absent}
        missing.extend(absent)
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
    operation = checks["operator_auth"]["configured"]
    return {
        "checks": checks,
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
        "note": "Configuration presence only; this endpoint does not call external providers or prove OAuth, quota, rendering, upload or billing works."
    }
