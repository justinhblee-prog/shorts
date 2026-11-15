"""Fail-closed inspection of staged video bytes using ffprobe.

Provider metadata is never treated as proof that the downloaded media is playable.
"""
import json
import math
import os
import shutil
import subprocess
from pathlib import Path


class MediaInspectionError(RuntimeError):
    pass


def inspect_media_file(path, ffprobe_path=None, runner=None, timeout=30):
    target = Path(path)
    if not target.is_file() or target.is_symlink():
        raise MediaInspectionError("Staged media file is missing or is not a regular file")
    size = target.stat().st_size
    if size <= 0:
        raise MediaInspectionError("Staged media file is empty")

    executable = ffprobe_path or os.getenv("FFPROBE_PATH") or shutil.which("ffprobe")
    if not executable or (
        runner is None and not Path(str(executable)).is_file()
        and shutil.which(str(executable)) is None
    ):
        raise MediaInspectionError(
            "ffprobe is unavailable; install FFmpeg before staging or uploading media"
        )

    invoke = runner or subprocess.run
    try:
        result = invoke(
            [executable, "-v", "error", "-show_entries",
             "format=format_name,duration:stream=codec_type,codec_name,width,height",
             "-of", "json", str(target)],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MediaInspectionError(
            "ffprobe could not inspect staged media: " + type(exc).__name__
        ) from exc
    if result.returncode != 0:
        raise MediaInspectionError("ffprobe rejected the staged media as unreadable")
    try:
        payload = json.loads(result.stdout)
    except (TypeError, ValueError) as exc:
        raise MediaInspectionError("ffprobe returned invalid inspection data") from exc
    if not isinstance(payload, dict):
        raise MediaInspectionError("ffprobe returned an invalid media document")

    fmt = payload.get("format") if isinstance(payload.get("format"), dict) else {}
    streams = payload.get("streams")
    if not isinstance(streams, list):
        raise MediaInspectionError("Media stream information is missing")
    video = [s for s in streams if isinstance(s, dict) and s.get("codec_type") == "video"]
    audio = [s for s in streams if isinstance(s, dict) and s.get("codec_type") == "audio"]
    if not video:
        raise MediaInspectionError("Media contains no video stream")
    if not audio:
        raise MediaInspectionError("Media contains no audio stream")

    primary = video[0]
    try:
        width, height = int(primary.get("width")), int(primary.get("height"))
        duration = float(fmt.get("duration"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise MediaInspectionError("Video dimensions or duration are missing/invalid") from exc
    if width <= 0 or height <= 0 or not math.isfinite(duration) or duration <= 0:
        raise MediaInspectionError("Video dimensions or duration are invalid")
    ratio = width / height
    if abs(ratio - (9.0 / 16.0)) > 0.04:
        raise MediaInspectionError("Video bytes are not in vertical 9:16 format")
    if duration > 180:
        raise MediaInspectionError("Video duration exceeds the 180-second Shorts limit")
    if duration < 1:
        raise MediaInspectionError("Video duration is too short to be a valid production")

    subtitle_streams = [
        s for s in streams if isinstance(s, dict) and s.get("codec_type") == "subtitle"
    ]
    return {
        "status": "passed",
        "verification": "ffprobe_media_bytes",
        "size_bytes": size,
        "container": fmt.get("format_name"),
        "duration_seconds": duration,
        "width": width,
        "height": height,
        "aspect_ratio": f"{width}:{height}",
        "video_codec": primary.get("codec_name"),
        "audio_codec": audio[0].get("codec_name"),
        "audio_track_present": True,
        "subtitle_stream_count": len(subtitle_streams),
        "subtitle_stream_present": bool(subtitle_streams),
        "note": "Subtitle streams are detected; burned-in subtitles require visual review.",
    }
