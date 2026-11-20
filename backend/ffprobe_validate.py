"""Bounded, shell-free ffprobe validation for staged local media outputs."""
from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path


class FFprobeValidationError(ValueError):
    """Raised when ffprobe cannot establish a safe, bounded media output."""



def probe_source_media(path, ffprobe_path, *, max_duration_ms=3_600_000,
                       max_bytes=2_000_000_000, timeout_seconds=15):
    """Validate an uploaded local source containing at least one audio/video stream."""
    media = Path(path)
    binary = Path(ffprobe_path)
    if not media.is_absolute() or media.is_symlink() or not media.is_file():
        raise FFprobeValidationError("source media must be an absolute regular non-symlink file")
    if not binary.is_absolute() or binary.is_symlink() or not binary.is_file():
        raise FFprobeValidationError("ffprobe binary must be an absolute regular non-symlink file")
    if (isinstance(max_duration_ms, bool) or not isinstance(max_duration_ms, int)
            or not 1 <= max_duration_ms <= 3_600_000):
        raise FFprobeValidationError("max_duration_ms must be between 1 and 3600000")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise FFprobeValidationError("max_bytes must be a positive integer")
    if (isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or not 1 <= timeout_seconds <= 60):
        raise FFprobeValidationError("timeout_seconds must be between 1 and 60")
    actual_size = media.stat().st_size
    if actual_size < 1 or actual_size > max_bytes:
        raise FFprobeValidationError("source media size is outside configured limits")
    argv = [
        str(binary), "-v", "error", "-protocol_whitelist", "file,pipe",
        "-show_entries",
        "format=duration,size:stream=codec_type,codec_name,width,height,sample_rate,channels",
        "-of", "json", str(media),
    ]
    try:
        completed = subprocess.run(
            argv, shell=False, check=False, capture_output=True,
            text=True, timeout=float(timeout_seconds),
        )
    except subprocess.TimeoutExpired as exc:
        raise FFprobeValidationError("source ffprobe exceeded its execution timeout") from exc
    except OSError as exc:
        raise FFprobeValidationError("source ffprobe could not be started") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or "ffprobe failed")[:1000]
        raise FFprobeValidationError(detail)
    try:
        result = json.loads(completed.stdout)
    except (TypeError, ValueError) as exc:
        raise FFprobeValidationError("source ffprobe returned invalid JSON") from exc
    if not isinstance(result, dict) or not isinstance(result.get("format"), dict):
        raise FFprobeValidationError("source ffprobe output is missing format metadata")
    streams = result.get("streams")
    if not isinstance(streams, list) or len(streams) > 16:
        raise FFprobeValidationError("source ffprobe returned an invalid stream list")
    video = [item for item in streams if isinstance(item, dict) and item.get("codec_type") == "video"]
    audio = [item for item in streams if isinstance(item, dict) and item.get("codec_type") == "audio"]
    if not video and not audio:
        raise FFprobeValidationError("source must contain an audio or video stream")
    try:
        duration = float(result["format"]["duration"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise FFprobeValidationError("source duration is missing or invalid") from exc
    if not math.isfinite(duration) or duration <= 0 or duration * 1000 > max_duration_ms:
        raise FFprobeValidationError("source duration is outside configured limits")
    reported_size = result["format"].get("size")
    if reported_size is not None:
        try:
            if int(reported_size) != actual_size:
                raise FFprobeValidationError("source ffprobe size does not match file size")
        except (TypeError, ValueError) as exc:
            if isinstance(exc, FFprobeValidationError):
                raise
            raise FFprobeValidationError("source ffprobe returned invalid size metadata") from exc

    video_streams = []
    for stream in video:
        width, height = stream.get("width"), stream.get("height")
        if (isinstance(width, bool) or not isinstance(width, int) or not 1 <= width <= 8192
                or isinstance(height, bool) or not isinstance(height, int) or not 1 <= height <= 8192):
            raise FFprobeValidationError("source video dimensions are outside configured limits")
        video_streams.append({
            "codec": stream.get("codec_name"), "width": width, "height": height,
        })
    audio_streams = []
    for stream in audio:
        try:
            sample_rate = int(stream.get("sample_rate"))
            channels = int(stream.get("channels"))
        except (TypeError, ValueError) as exc:
            raise FFprobeValidationError("source audio stream metadata is invalid") from exc
        if not 8000 <= sample_rate <= 192000 or not 1 <= channels <= 16:
            raise FFprobeValidationError("source audio metadata is outside configured limits")
        audio_streams.append({
            "codec": stream.get("codec_name"),
            "sample_rate": sample_rate, "channels": channels,
        })
    return {
        "duration_ms": round(duration * 1000),
        "byte_size": actual_size,
        "has_video": bool(video_streams),
        "has_audio": bool(audio_streams),
        "video_streams": video_streams,
        "audio_streams": audio_streams,
    }

def probe_media(path, ffprobe_path, *, max_duration_ms=3_600_000,
                max_bytes=2_000_000_000, timeout_seconds=15,
                require_audio=False):
    """Probe one local staged media file using an explicitly configured binary.

    The executable and media paths must be absolute regular non-symlink files.
    No shell, URL inputs, user-supplied arguments, or arbitrary ffprobe flags
    are accepted.
    """
    media = Path(path)
    binary = Path(ffprobe_path)
    if not media.is_absolute() or media.is_symlink() or not media.is_file():
        raise FFprobeValidationError("media must be an absolute regular non-symlink file")
    if not binary.is_absolute() or binary.is_symlink() or not binary.is_file():
        raise FFprobeValidationError("ffprobe binary must be an absolute regular non-symlink file")
    if (isinstance(max_duration_ms, bool) or not isinstance(max_duration_ms, int)
            or not 1 <= max_duration_ms <= 3_600_000):
        raise FFprobeValidationError("max_duration_ms must be between 1 and 3600000")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise FFprobeValidationError("max_bytes must be a positive integer")
    if (isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or not 1 <= timeout_seconds <= 60):
        raise FFprobeValidationError("timeout_seconds must be between 1 and 60")
    if not isinstance(require_audio, bool):
        raise FFprobeValidationError("require_audio must be boolean")

    actual_size = media.stat().st_size
    if actual_size < 1 or actual_size > max_bytes:
        raise FFprobeValidationError("media file size is outside configured limits")

    argv = [
        str(binary), "-v", "error",
        "-protocol_whitelist", "file,pipe", "-show_entries",
        "format=duration,size:stream=codec_type,codec_name,width,height,sample_rate,channels",
        "-of", "json", str(media),
    ]
    try:
        completed = subprocess.run(
            argv, shell=False, check=False, capture_output=True,
            text=True, timeout=float(timeout_seconds),
        )
    except subprocess.TimeoutExpired as exc:
        raise FFprobeValidationError("ffprobe exceeded its execution timeout") from exc
    except OSError as exc:
        raise FFprobeValidationError("ffprobe could not be started") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or "ffprobe failed")[:1000]
        raise FFprobeValidationError(detail)
    try:
        result = json.loads(completed.stdout)
    except (TypeError, ValueError) as exc:
        raise FFprobeValidationError("ffprobe returned invalid JSON") from exc
    if not isinstance(result, dict) or not isinstance(result.get("format"), dict):
        raise FFprobeValidationError("ffprobe output is missing format metadata")
    streams = result.get("streams")
    if not isinstance(streams, list) or len(streams) > 16:
        raise FFprobeValidationError("ffprobe returned an invalid stream list")

    try:
        duration_seconds = float(result["format"]["duration"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise FFprobeValidationError("media duration is missing or invalid") from exc
    if (not math.isfinite(duration_seconds) or duration_seconds <= 0
            or duration_seconds * 1000 > max_duration_ms):
        raise FFprobeValidationError("media duration is outside configured limits")

    video = [item for item in streams if isinstance(item, dict) and item.get("codec_type") == "video"]
    audio = [item for item in streams if isinstance(item, dict) and item.get("codec_type") == "audio"]
    if not video:
        raise FFprobeValidationError("render output must contain a video stream")
    if require_audio and not audio:
        raise FFprobeValidationError("render output must contain an audio stream")

    dimensions = []
    for stream in video:
        width, height = stream.get("width"), stream.get("height")
        if (isinstance(width, bool) or not isinstance(width, int) or not 1 <= width <= 8192
                or isinstance(height, bool) or not isinstance(height, int) or not 1 <= height <= 8192):
            raise FFprobeValidationError("video stream dimensions are outside configured limits")
        dimensions.append({"width": width, "height": height, "codec": stream.get("codec_name")})

    reported_size = result["format"].get("size")
    if reported_size is not None:
        try:
            if int(reported_size) != actual_size:
                raise FFprobeValidationError("ffprobe media size does not match staged file size")
        except (TypeError, ValueError) as exc:
            if isinstance(exc, FFprobeValidationError):
                raise
            raise FFprobeValidationError("ffprobe returned invalid file size metadata") from exc

    return {
        "duration_ms": round(duration_seconds * 1000),
        "byte_size": actual_size,
        "video_streams": dimensions,
        "audio_streams": len(audio),
        "audio_codecs": [item.get("codec_name") for item in audio],
    }
