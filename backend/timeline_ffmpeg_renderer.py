"""Lease-cancellable FFmpeg renderer for the safe EDL v1 subset.

Inputs are resolved only through the workspace asset store. The renderer writes
one staged MP4 into the artifact store's private staging root; the worker then
performs lease-fenced adoption. It never publishes or uploads media.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
import uuid

from ffmpeg_audio_mix import build_audio_mix_argv
from ffprobe_validate import probe_media
from timeline_edl import validate_edl, EDLValidationError


class TimelineFFmpegError(RuntimeError):
    """A validated timeline could not be rendered safely."""


def _configured_binary(value, name, *, executable=True):
    path = Path(value)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise TimelineFFmpegError(f"{name} must be an absolute regular non-symlink file")
    if executable and os.name != "nt" and not os.access(path, os.X_OK):
        raise TimelineFFmpegError(f"{name} must be executable")
    return str(path.resolve(strict=True))


def _filter_path(value):
    """Escape a trusted local path for an FFmpeg filter option."""
    raw = Path(value).resolve(strict=True).as_posix()
    for char in ("\\", "'", ":", ",", "[", "]", ";"):
        raw = raw.replace(char, "\\" + char)
    return "'" + raw + "'"


def _probe_source(path, ffprobe_path, expected_kind, timeout_seconds):
    argv = [
        ffprobe_path, "-v", "error", "-show_entries",
        "format=duration:stream=codec_type", "-of", "json", str(path),
    ]
    try:
        result = subprocess.run(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, timeout=min(timeout_seconds, 30),
            check=False, shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TimelineFFmpegError("source media probe could not complete") from exc
    if result.returncode != 0 or len(result.stdout) > 256 * 1024:
        raise TimelineFFmpegError("source media failed ffprobe validation")
    try:
        data = json.loads(result.stdout.decode("utf-8"))
        duration = float(data["format"]["duration"])
        streams = data["streams"]
    except (ValueError, UnicodeDecodeError, KeyError, TypeError, OverflowError) as exc:
        raise TimelineFFmpegError("source media returned invalid probe metadata") from exc
    if not math.isfinite(duration) or duration <= 0 or not isinstance(streams, list):
        raise TimelineFFmpegError("source media duration or stream metadata is invalid")
    if not any(isinstance(item, dict) and item.get("codec_type") == expected_kind
               for item in streams):
        raise TimelineFFmpegError(f"source media has no {expected_kind} stream")
    return duration


def build_timeline_ffmpeg_argv(edl, staged_assets, output_path, *,
                               ffmpeg_path, font_path=None, audio_mix_path=None,
                               title_files=None):
    """Build a deterministic 1080x1920 H.264 command for normalized EDL clips."""
    normalized = validate_edl(edl)
    videos = [clip for clip in normalized["clips"] if clip["type"] == "video"]
    titles = [clip for clip in normalized["clips"] if clip["type"] == "title"]
    total_ms = max(clip["end_ms"] for clip in normalized["clips"])
    if not videos:
        raise TimelineFFmpegError("at least one video clip is required")
    if len(videos) > 20:
        raise TimelineFFmpegError("video clip count exceeds the supported limit")
    if titles and font_path is None:
        raise TimelineFFmpegError("a configured font file is required for title clips")

    argv = [ffmpeg_path, "-nostdin", "-hide_banner", "-y", "-filter_complex_threads", "1"]
    input_indexes = {}
    for clip in videos:
        asset_path = staged_assets.get(clip["asset_id"])
        if not asset_path:
            raise TimelineFFmpegError("video clip asset was not staged")
        key = clip["asset_id"]
        if key not in input_indexes:
            input_indexes[key] = len(input_indexes)
            argv.extend(["-i", str(asset_path)])
    if audio_mix_path is not None:
        audio_index = len(input_indexes)
        argv.extend(["-i", str(audio_mix_path)])
    else:
        audio_index = None

    filters = [
        f"color=c=black:s=1080x1920:r=30:d={total_ms / 1000:.3f}[base0]"
    ]
    current = "base0"
    for index, clip in enumerate(videos):
        source_duration = (clip["source_out_ms"] - clip["source_in_ms"]) / 1000
        start = clip["source_in_ms"] / 1000
        begin = clip["start_ms"] / 1000
        end = clip["end_ms"] / 1000
        asset_index = input_indexes[clip["asset_id"]]
        label = f"video{index}"
        next_label = f"base{index + 1}"
        filters.append(
            f"[{asset_index}:v:0]trim=start={start:.3f}:duration={source_duration:.3f},"
            f"setpts=PTS-STARTPTS,scale=1080:1920:force_original_aspect_ratio=increase,"
            f"crop=1080:1920,fps=30,setsar=1,format=rgba[{label}]"
        )
        filters.append(
            f"[{current}][{label}]overlay=0:0:eof_action=pass:shortest=0:"
            f"enable='between(t,{begin:.3f},{end:.3f})'[{next_label}]"
        )
        current = next_label

    if titles:
        font = _filter_path(font_path)
        for index, clip in enumerate(titles):
            text_path = (title_files or {}).get(clip["id"])
            if not text_path:
                raise TimelineFFmpegError("title text must be staged as a UTF-8 text file")
            text_file = _filter_path(text_path)
            begin, end = clip["start_ms"] / 1000, clip["end_ms"] / 1000
            next_label = f"title{index}"
            filters.append(
                f"[{current}]drawtext=fontfile={font}:textfile={text_file}:"
                f"expansion=none:fontsize=58:fontcolor=white:borderw=3:bordercolor=black:"
                f"x=(w-text_w)/2:y=h*0.78:"
                f"enable='between(t,{begin:.3f},{end:.3f})'[{next_label}]"
            )
            current = next_label

    argv.extend(["-filter_complex", ";".join(filters), "-map", f"[{current}]"])
    if audio_index is not None:
        argv.extend(["-map", f"{audio_index}:a:0", "-c:a", "aac", "-b:a", "192k"])
    else:
        argv.append("-an")
    argv.extend([
        "-t", f"{total_ms / 1000:.3f}", "-c:v", "libx264",
        "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-r", "30", "-movflags", "+faststart", str(output_path),
    ])
    return argv


def _run_cancellable(argv, output_path, stop_event, timeout_seconds, max_output_bytes):
    if not isinstance(argv, (list, tuple)) or not argv or any(
        not isinstance(arg, str) or not arg or "\\x00" in arg for arg in argv
    ):
        raise TimelineFFmpegError("FFmpeg command must be a non-empty argument array")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 3600:
        raise TimelineFFmpegError("render timeout must be between 1 and 3600 seconds")
    if isinstance(max_output_bytes, bool) or not isinstance(max_output_bytes, int) or not 1024 <= max_output_bytes <= 2 * 1024**3:
        raise TimelineFFmpegError("render output limit must be between 1 KiB and 2 GiB")
    options = {
        "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL, "shell": False,
    }
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    try:
        process = subprocess.Popen(list(argv), **options)
    except OSError as exc:
        raise TimelineFFmpegError("FFmpeg process could not be started") from exc
    started = time.monotonic()
    try:
        while process.poll() is None:
            if stop_event is not None and stop_event.is_set():
                raise TimelineFFmpegError("render cancelled because its worker lease was lost")
            if time.monotonic() - started > timeout_seconds:
                raise TimelineFFmpegError("FFmpeg render exceeded its execution time limit")
            if output_path.exists() and output_path.stat().st_size > max_output_bytes:
                raise TimelineFFmpegError("FFmpeg render exceeded its output size limit")
            time.sleep(0.05)
        if process.returncode != 0:
            raise TimelineFFmpegError(f"FFmpeg exited with status {process.returncode}")
        if not output_path.is_file() or output_path.is_symlink():
            raise TimelineFFmpegError("FFmpeg did not create a regular output file")
        if not 0 < output_path.stat().st_size <= max_output_bytes:
            raise TimelineFFmpegError("FFmpeg output size is outside configured limits")
    except Exception:
        if process.poll() is None:
            try:
                if os.name == "nt":
                    process.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    if os.name == "nt":
                        process.kill()
                    else:
                        os.killpg(process.pid, signal.SIGKILL)
                except OSError:
                    process.kill()
                process.wait()
        raise


class TimelineFFmpegRenderer:
    """Callable worker renderer backed by clean workspace assets and pinned tools."""

    def __init__(self, asset_store, staging_root, ffmpeg_path, ffprobe_path, *,
                 font_path=None, timeout_seconds=900,
                 max_output_bytes=512 * 1024 * 1024,
                 max_input_bytes=2 * 1024 * 1024 * 1024):
        self.assets = asset_store
        self.staging_root = Path(staging_root).resolve()
        self.staging_root.mkdir(parents=True, exist_ok=True)
        if self.staging_root.is_symlink() or not self.staging_root.is_dir():
            raise ValueError("staging root must be a private regular directory")
        self.ffmpeg_path = _configured_binary(ffmpeg_path, "FFmpeg")
        self.ffprobe_path = _configured_binary(ffprobe_path, "ffprobe")
        self.font_path = _configured_binary(font_path, "font", executable=False) if font_path else None
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes
        self.max_input_bytes = max_input_bytes

    def __call__(self, payload, *, stop_event):
        if not isinstance(payload, dict):
            raise TimelineFFmpegError("render job payload must be an object")
        workspace_id = payload.get("workspace_id")
        principal_id = payload.get("principal_id")
        if not isinstance(workspace_id, str) or not workspace_id or not isinstance(principal_id, str) or not principal_id:
            raise TimelineFFmpegError("render job is missing its workspace owner context")
        try:
            edl = validate_edl(payload.get("edl"))
        except EDLValidationError as exc:
            raise TimelineFFmpegError("render job EDL is invalid") from exc
        workdir = Path(tempfile.mkdtemp(prefix=".timeline-work-", dir=self.staging_root))
        staged_assets = {}
        audio_tracks = []
        source_probes = {}
        output_path = self.staging_root / ("rart_" + uuid.uuid4().hex + ".mp4")
        total_bytes = 0
        try:
            if stop_event is not None and stop_event.is_set():
                raise TimelineFFmpegError("render cancelled before asset staging")
            for clip in edl["clips"]:
                if clip["type"] == "title":
                    continue
                asset_id = clip["asset_id"]
                expected_kind = "audio" if clip["type"] == "audio" else "video"
                if asset_id not in staged_assets:
                    target = workdir / (asset_id + ".media")
                    with self.assets.open_clean_asset(workspace_id, principal_id, asset_id) as source:
                        with target.open("xb") as output:
                            while True:
                                if stop_event is not None and stop_event.is_set():
                                    raise TimelineFFmpegError("render cancelled while staging source media")
                                chunk = source.read(1024 * 1024)
                                if not chunk:
                                    break
                                total_bytes += len(chunk)
                                if total_bytes > self.max_input_bytes:
                                    raise TimelineFFmpegError("render input bytes exceed configured limit")
                                output.write(chunk)
                            output.flush()
                            os.fsync(output.fileno())
                    staged_assets[asset_id] = target
                probe_key = (asset_id, expected_kind)
                if probe_key not in source_probes:
                    source_probes[probe_key] = _probe_source(
                        staged_assets[asset_id], self.ffprobe_path,
                        expected_kind, self.timeout_seconds,
                    )
                if clip["source_out_ms"] > source_probes[probe_key] * 1000 + 1:
                    raise TimelineFFmpegError("EDL source trim exceeds probed media duration")
                if clip["type"] == "audio":
                    audio_tracks.append({
                        "path": str(staged_assets[asset_id]),
                        "start_ms": round(clip["start_ms"]),
                        "duration_ms": round(clip["end_ms"] - clip["start_ms"]),
                        "gain": clip["gain"],
                        "fade_in_ms": clip["fade_in_ms"],
                        "fade_out_ms": clip["fade_out_ms"],
                    })

            title_files = {}
            for index, clip in enumerate(edl["clips"]):
                if clip["type"] != "title":
                    continue
                text_file = workdir / f"title-{index}.txt"
                text_file.write_text(clip["text"], encoding="utf-8")
                title_files[clip["id"]] = text_file
            total_duration = max(int(clip["end_ms"]) for clip in edl["clips"])
            audio_mix_path = None
            if audio_tracks:
                audio_mix_path = workdir / "audio-mix.m4a"
                audio_argv = build_audio_mix_argv(
                    audio_tracks, str(audio_mix_path),
                    ffmpeg_path=self.ffmpeg_path,
                    output_duration_ms=total_duration,
                )
                _run_cancellable(
                    audio_argv, audio_mix_path, stop_event,
                    self.timeout_seconds, self.max_output_bytes,
                )
            argv = build_timeline_ffmpeg_argv(
                edl, staged_assets, output_path,
                ffmpeg_path=self.ffmpeg_path, font_path=self.font_path,
                audio_mix_path=audio_mix_path, title_files=title_files,
            )
            _run_cancellable(
                argv, output_path, stop_event,
                self.timeout_seconds, self.max_output_bytes,
            )
            probe = probe_media(
                output_path, self.ffprobe_path,
                max_duration_ms=total_duration,
                max_bytes=self.max_output_bytes,
                timeout_seconds=min(self.timeout_seconds, 60),
                require_audio=bool(audio_tracks),
            )
            return {"staged_path": str(output_path), "probe": probe}
        except Exception:
            output_path.unlink(missing_ok=True)
            raise
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
