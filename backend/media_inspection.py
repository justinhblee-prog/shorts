"""Inspect staged media bytes with ffprobe; metadata from render providers is not trusted."""
import json
import os
import re
import subprocess
from pathlib import Path


class MediaInspectionError(RuntimeError):
    pass


class MediaInspector:
    def __init__(self, ffprobe_path=None, ffmpeg_path=None, timeout_seconds=30,
                 signal_timeout_seconds=90, runner=None, analyze_signals=True):
        self.ffprobe_path = ffprobe_path or os.getenv("FFPROBE_PATH", "ffprobe")
        self.ffmpeg_path = ffmpeg_path or os.getenv("FFMPEG_PATH", "ffmpeg")
        self.timeout_seconds = max(1, min(int(timeout_seconds), 120))
        self.signal_timeout_seconds = max(1, min(int(signal_timeout_seconds), 300))
        self.runner = runner or subprocess.run
        self.analyze_signals = bool(analyze_signals)

    def _run_signal_filter(self, media_path, filter_name, stream_type):
        command = [
            self.ffmpeg_path, "-hide_banner", "-nostats", "-nostdin", "-v", "info",
            "-protocol_whitelist", "file,pipe", "-i", str(media_path),
            "-map", f"0:{stream_type}:0", "-filter:a" if stream_type == "a" else "-filter:v",
            filter_name, "-f", "null", "-",
        ]
        try:
            result = self.runner(
                command, capture_output=True, text=True,
                timeout=self.signal_timeout_seconds, check=False,
            )
        except FileNotFoundError as exc:
            raise MediaInspectionError("ffmpeg is not installed; install the ffmpeg package") from exc
        except subprocess.TimeoutExpired as exc:
            raise MediaInspectionError("ffmpeg signal analysis exceeded its timeout") from exc
        except OSError as exc:
            raise MediaInspectionError("ffmpeg signal analysis could not be executed") from exc
        if result.returncode != 0:
            detail = (result.stderr or "").strip()[-500:]
            raise MediaInspectionError("ffmpeg could not decode the media stream" +
                                       (": " + detail if detail else ""))
        return result.stderr or ""

    def _analyze_signals(self, media_path, duration, has_audio):
        video_log = self._run_signal_filter(
            media_path, "blackdetect=d=1.0:pix_th=0.10", "v"
        )
        black_segments = []
        for match in re.finditer(
            r"black_start:([0-9.]+).*?black_end:([0-9.]+).*?black_duration:([0-9.]+)",
            video_log,
        ):
            black_segments.append({
                "start_seconds": float(match.group(1)),
                "end_seconds": float(match.group(2)),
                "duration_seconds": float(match.group(3)),
            })
        silence_segments = []
        if has_audio:
            audio_log = self._run_signal_filter(
                media_path, "silencedetect=noise=-45dB:d=1.0", "a"
            )
            starts = [float(x) for x in re.findall(r"silence_start: ([0-9.]+)", audio_log)]
            ends = [
                (float(m.group(1)), float(m.group(2)))
                for m in re.finditer(
                    r"silence_end: ([0-9.]+) \| silence_duration: ([0-9.]+)",
                    audio_log,
                )
            ]
            for index, (end, gap) in enumerate(ends):
                start = starts[index] if index < len(starts) else max(0.0, end - gap)
                silence_segments.append({
                    "start_seconds": start, "end_seconds": end,
                    "duration_seconds": gap,
                })
            if len(starts) > len(ends):
                start = starts[-1]
                if duration > start:
                    silence_segments.append({
                        "start_seconds": start, "end_seconds": duration,
                        "duration_seconds": duration - start,
                        "extends_to_end": True,
                    })
        warnings = []
        if any(segment["duration_seconds"] >= 2.0 for segment in black_segments):
            warnings.append("black_frame_segment_at_least_2_seconds_detected")
        if any(segment["duration_seconds"] >= 2.0 for segment in silence_segments):
            warnings.append("audio_silence_segment_at_least_2_seconds_detected")
        if silence_segments and silence_segments[0]["start_seconds"] <= 0.25 and silence_segments[0]["duration_seconds"] >= 1.5:
            warnings.append("audio_starts_with_extended_silence")
        if silence_segments and silence_segments[-1].get("extends_to_end") and silence_segments[-1]["duration_seconds"] >= 1.5:
            warnings.append("audio_ends_with_extended_silence")
        return {
            "status": "analyzed",
            "black_segments": black_segments,
            "silence_segments": silence_segments,
            "signal_warnings": warnings,
            "signal_analysis_boundary": (
                "Black-frame and low-volume silence heuristics only. Dark scenes may be "
                "intentional; pauses may be intentional. This is not semantic visual review, "
                "speech recognition, music-rights detection, loudness compliance or caption QA."
            ),
        }

    def inspect(self, media_path):
        supplied_path = Path(media_path)
        if supplied_path.is_symlink():
            raise MediaInspectionError("Staged media path must not be a symlink")
        path = supplied_path.resolve()
        if not path.is_file():
            raise MediaInspectionError("Staged media file is missing or is not a regular file")
        try:
            result = self.runner(
                [
                    self.ffprobe_path, "-nostdin", "-v", "error",
                    "-protocol_whitelist", "file,pipe",
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
        signal_report = (
            self._analyze_signals(path, duration, audio is not None)
            if self.analyze_signals else {"status": "not_run", "signal_warnings": []}
        )
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
            "signal_analysis": signal_report,
        }
