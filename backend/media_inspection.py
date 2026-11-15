"""Inspect staged media bytes with ffprobe; metadata from render providers is not trusted."""
import json
import os
import subprocess
from pathlib import Path


class MediaInspectionError(RuntimeError):
    pass


class MediaInspector:
    def __init__(self, ffprobe_path=None, timeout_seconds=30, runner=None):
        self.ffprobe_path = ffprobe_path or os.getenv("FFPROBE_PATH", "ffprobe")
        self.timeout_seconds = max(1, min(int(timeout_seconds), 120))
        self.runner = runner or subprocess.run

    def inspect(self, media_path):
        path = Path(media_path).resolve()
        if not path.is_file() or path.is_symlink():
            raise MediaInspectionError("Staged media file is missing or is not a regular file")
        try:
            result = self.runner(
                [
                    self.ffprobe_path, "-v", "error",
                    "-show_entries",
                    "format=format_name,duration,size:"
                    "stream=index,codec_type,codec_name,width,height,avg_frame_rate,"
                    "sample_rate,channels",
                    "-of", "json", str(path),
                ],
                capture_output=True, text=True, timeout=self.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise MediaInspectionError("ffprobe is not installed; install the ffmpeg package") from exc
        except subprocess.TimeoutExpired as exc:
            raise MediaInspectionError("ffprobe exceeded its inspection timeout") from exc
        except OSError as exc:
            raise MediaInspectionError("ffprobe could not be executed") from exc
        if result.returncode != 0:
            detail = (result.stderr or "").strip()[:500]
            raise MediaInspectionError("ffprobe rejected the media file" + (": " + detail if detail else ""))
        try:
            payload = json.loads(result.stdout)
        except (TypeError, ValueError) as exc:
            raise MediaInspectionError("ffprobe returned invalid JSON") from exc
        streams = payload.get("streams")
        fmt = payload.get("format")
        if not isinstance(streams, list) or not isinstance(fmt, dict):
            raise MediaInspectionError("ffprobe output is missing format or stream data")
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        if video is None:
            raise MediaInspectionError("Media file contains no video stream")
        width, height = video.get("width"), video.get("height")
        try:
            width, height = int(width), int(height)
            duration = float(fmt.get("duration"))
            size = int(fmt.get("size"))
        except (TypeError, ValueError) as exc:
            raise MediaInspectionError("Media file has invalid dimensions, duration, or size") from exc
        if width <= 0 or height <= 0 or duration <= 0 or size <= 0:
            raise MediaInspectionError("Media file has non-positive dimensions, duration, or size")
        format_names = [x.strip().lower() for x in str(fmt.get("format_name", "")).split(",")]
        if not any(x in ("mp4", "mov", "m4a", "3gp", "3g2", "mj2") for x in format_names):
            raise MediaInspectionError("Media container is not a supported MP4-family format")
        return {
            "status": "inspected",
            "inspection_method": "ffprobe_file_bytes",
            "format_names": format_names,
            "duration_seconds": duration,
            "size_bytes": size,
            "width": width,
            "height": height,
            "aspect_ratio": round(width / height, 5),
            "video_codec": video.get("codec_name"),
            "audio_track_present": audio is not None,
            "audio_codec": audio.get("codec_name") if audio else None,
            "audio_sample_rate": audio.get("sample_rate") if audio else None,
            "audio_channels": audio.get("channels") if audio else None,
            "subtitle_stream_present": any(s.get("codec_type") == "subtitle" for s in streams),
            "subtitle_note": (
                "Subtitle stream presence is detectable; burned-in subtitle correctness "
                "and legibility are not verified."
            ),
        }
