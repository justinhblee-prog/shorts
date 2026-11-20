"""Bounded EDL v1 renderer using an allowlisted local FFmpeg executable.

This renderer intentionally supports the video-clip subset of EDL v1. Title
clips and timeline gaps/overlaps fail closed until their compositing semantics
are implemented. Asset paths and optional audio-bed paths must be resolved by
trusted workspace services; the EDL itself never supplies filesystem paths.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from ffmpeg_audio_mix import build_audio_mix_argv
from timeline_edl import validate_edl
from ffprobe_validate import has_audio_stream


class EDLRenderError(RuntimeError):
    """A bounded EDL render failed or was cancelled."""


def _regular_file(value, field):
    path = Path(value)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise EDLRenderError(f"{field} must be an absolute regular non-symlink file")
    return path.resolve(strict=True)


def _escape_filter_value(value):
    return (str(value).replace("\\", "\\\\").replace(":", "\\:")
            .replace("'", "\\'").replace(",", "\\,").replace(";", "\\;")
            .replace("[", "\\[").replace("]", "\\]"))


def build_video_argv(edl, asset_paths, output_path, *, ffmpeg_path,
                     width=1080, height=1920, fps=30, title_font_path=None):
    """Build a shell-free FFmpeg graph with black gaps and configured title cards."""
    normalized = validate_edl(edl)
    if not isinstance(asset_paths, dict):
        raise EDLRenderError("asset_paths must be resolved by the trusted asset layer")
    if not isinstance(ffmpeg_path, str) or not Path(ffmpeg_path).is_absolute():
        raise EDLRenderError("FFmpeg executable must be an absolute configured path")
    binary = _regular_file(ffmpeg_path, "FFmpeg executable")
    for value, name, allowed in (
        (width, "width", range(16, 4097)),
        (height, "height", range(16, 4097)),
        (fps, "fps", range(1, 61)),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value not in allowed:
            raise EDLRenderError(f"{name} is outside configured limits")
    ordered = sorted(normalized["clips"], key=lambda clip: (clip["start_ms"], clip["id"]))
    video_clips = [clip for clip in ordered if clip["type"] == "video"]
    title_clips = [clip for clip in ordered if clip["type"] == "title"]
    font = None
    if title_clips:
        if title_font_path is None:
            raise EDLRenderError("title clips require a configured trusted font file")
        font = _regular_file(title_font_path, "title font")
    elif title_font_path is not None:
        font = _regular_file(title_font_path, "title font")

    used_assets = {clip["asset_id"] for clip in video_clips}
    if set(asset_paths) != used_assets:
        raise EDLRenderError("asset resolver paths must exactly match referenced video assets")
    resolved = {}
    for asset_id, value in asset_paths.items():
        resolved[asset_id] = _regular_file(value, "resolved asset")

    output = Path(output_path)
    if not output.is_absolute() or output.is_symlink() or output.suffix.lower() != ".mp4":
        raise EDLRenderError("video output must be an absolute .mp4 path")
    if not output.parent.is_dir():
        raise EDLRenderError("video output directory must already exist")

    argv = [str(binary), "-nostdin", "-hide_banner", "-y", "-threads", "2"]
    video_indexes = {}
    for index, clip in enumerate(video_clips):
        video_indexes[clip["id"]] = index
        argv.extend(["-i", str(resolved[clip["asset_id"]])])

    filters = []
    labels = []
    timeline_cursor = 0.0
    synthetic_index = len(video_clips)
    max_end = max(clip["end_ms"] for clip in ordered)
    for segment_index, clip in enumerate(ordered):
        start_ms = clip["start_ms"]
        if start_ms < timeline_cursor - 1.0:
            raise EDLRenderError("overlapping timeline clips are not supported")
        gap_ms = start_ms - timeline_cursor
        if gap_ms > 1.0:
            gap_label = f"gap{segment_index}"
            argv.extend([
                "-f", "lavfi", "-t", f"{gap_ms / 1000.0:.3f}",
                "-i", f"color=c=black:s={width}x{height}:r={fps}",
            ])
            filters.append(
                f"[{synthetic_index}:v:0]setpts=PTS-STARTPTS,format=yuv420p[{gap_label}]"
            )
            labels.append(f"[{gap_label}]")
            synthetic_index += 1

        duration = (clip["end_ms"] - clip["start_ms"]) / 1000.0
        label = f"segment{segment_index}"
        if clip["type"] == "video":
            index = video_indexes[clip["id"]]
            source_duration = (clip["source_out_ms"] - clip["source_in_ms"]) / 1000.0
            source_start = clip["source_in_ms"] / 1000.0
            filters.append(
                f"[{index}:v:0]trim=start={source_start:.3f}:duration={source_duration:.3f},"
                f"setpts=PTS-STARTPTS,scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
                f"fps={fps},setsar=1,format=yuv420p[{label}]"
            )
        else:
            argv.extend([
                "-f", "lavfi", "-t", f"{duration:.3f}",
                "-i", f"color=c=black:s={width}x{height}:r={fps}",
            ])
            escaped_font = _escape_filter_value(font)
            escaped_text = _escape_filter_value(clip["text"].replace("\r", " ").replace("\n", " "))
            filters.append(
                f"[{synthetic_index}:v:0]drawtext=fontfile='{escaped_font}':"
                f"text='{escaped_text}':expansion=none:fontcolor=white:fontsize=72:"
                "x=(w-text_w)/2:y=(h-text_h)/2:box=1:boxcolor=black@0.55:"
                f"boxborderw=24,format=yuv420p[{label}]"
            )
            synthetic_index += 1
        labels.append(f"[{label}]")
        timeline_cursor = clip["end_ms"]

    filters.append("".join(labels) + f"concat=n={len(labels)}:v=1:a=0[outv]")
    argv.extend([
        "-filter_complex", ";".join(filters), "-map", "[outv]",
        "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-threads", "2", "-movflags", "+faststart",
        "-t", f"{max_end / 1000.0:.3f}", str(output),
    ])
    return argv, round(max_end)

class EDLFFmpegRenderer:
    """Callable renderer suitable for TimelineRenderWorker's renderer argument.

    asset_resolver(workspace_id, principal_id, asset_id) must return a verified private local
    path. audio_tracks_resolver(payload) may return trusted, already-resolved
    track specifications for build_audio_mix_argv; it is never read from EDL.
    """
    def __init__(self, staging_root, ffmpeg_path, asset_resolver, *,
                 audio_tracks_resolver=None, ffprobe_path=None, title_font_path=None, width=1080, height=1920, fps=30,
                 max_input_bytes=2_000_000_000, timeout_seconds=3600):
        root = Path(staging_root)
        root.mkdir(parents=True, exist_ok=True)
        if root.is_symlink() or not root.is_dir():
            raise ValueError("staging root must be a real directory")
        self.staging_root = root.resolve(strict=True)
        self.ffmpeg_path = str(_regular_file(ffmpeg_path, "FFmpeg executable"))
        if not callable(asset_resolver):
            raise TypeError("asset_resolver callback is required")
        if audio_tracks_resolver is not None and not callable(audio_tracks_resolver):
            raise TypeError("audio_tracks_resolver must be callable")
        if isinstance(max_input_bytes, bool) or not isinstance(max_input_bytes, int) or max_input_bytes < 1:
            raise ValueError("max_input_bytes must be positive")
        if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
                or not 1 <= timeout_seconds <= 3600):
            raise ValueError("timeout_seconds must be between 1 and 3600")
        self.asset_resolver = asset_resolver
        self.audio_tracks_resolver = audio_tracks_resolver
        self.ffprobe_path = str(_regular_file(ffprobe_path, "ffprobe executable")) if ffprobe_path is not None else None
        self.title_font_path = str(_regular_file(title_font_path, "title font")) if title_font_path is not None else None
        self.width, self.height, self.fps = width, height, fps
        self.max_input_bytes = max_input_bytes
        self.timeout_seconds = float(timeout_seconds)

    def _run(self, argv, stop_event, deadline, log_path):
        if stop_event.is_set():
            raise EDLRenderError("render lease was lost before FFmpeg launch")
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
        log_handle = open(log_path, "ab")
        popen_kwargs = {
            "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
            "stderr": log_handle, "shell": False, "close_fds": True,
            "creationflags": creationflags,
        }
        if os.name != "nt":
            popen_kwargs["start_new_session"] = True
        process = None
        try:
            process = subprocess.Popen(argv, **popen_kwargs)
            while process.poll() is None:
                if stop_event.is_set():
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                    raise EDLRenderError("render cancelled because the worker lease was lost")
                if time.monotonic() >= deadline:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                    raise EDLRenderError("FFmpeg exceeded the configured render timeout")
                time.sleep(0.1)
            if process.returncode != 0:
                raise EDLRenderError(f"FFmpeg exited with code {process.returncode}")
        except OSError as exc:
            raise EDLRenderError("configured FFmpeg executable could not be started") from exc
        finally:
            log_handle.close()
            if process is not None and process.poll() is None:
                process.kill()
                process.wait()

    def __call__(self, payload, stop_event):
        if stop_event.is_set():
            raise EDLRenderError("render lease was lost before FFmpeg launch")
        if not isinstance(payload, dict) or not isinstance(payload.get("edl"), dict):
            raise EDLRenderError("render queue payload is malformed")
        workspace_id = payload.get("workspace_id")
        if not isinstance(workspace_id, str) or not workspace_id:
            raise EDLRenderError("queue workspace identity is required for asset resolution")
        principal_id = payload.get("creator_principal_id")
        if not isinstance(principal_id, str) or not principal_id:
            raise EDLRenderError("snapshot creator identity is required for asset authorization")
        edl = validate_edl(payload["edl"])
        assets = {}
        for clip in edl["clips"]:
            if clip["type"] != "video":
                continue
            asset_id = clip["asset_id"]
            if asset_id not in assets:
                resolved = self.asset_resolver(workspace_id, principal_id, asset_id)
                path = _regular_file(resolved, "resolved clean workspace asset")
                if path.stat().st_size > self.max_input_bytes:
                    raise EDLRenderError("source asset exceeds configured input byte limit")
                assets[asset_id] = path
        if sum(path.stat().st_size for path in assets.values()) > self.max_input_bytes:
            raise EDLRenderError("aggregate source assets exceed configured input byte limit")

        work_dir = Path(tempfile.mkdtemp(prefix="render-", dir=str(self.staging_root)))
        final_output = self.staging_root / ("render-" + uuid.uuid4().hex + ".mp4")
        video_only = work_dir / "video.mp4"
        mixed_audio = work_dir / "mix.m4a"
        log_path = work_dir / "ffmpeg.log"
        deadline = time.monotonic() + self.timeout_seconds
        try:
            argv, duration_ms = build_video_argv(
                edl, assets, video_only, ffmpeg_path=self.ffmpeg_path,
                width=self.width, height=self.height, fps=self.fps,
                title_font_path=self.title_font_path,
            )
            self._run(argv, stop_event, deadline, log_path)
            if not video_only.is_file() or video_only.stat().st_size < 1:
                raise EDLRenderError("FFmpeg did not produce a non-empty video output")
            tracks = []
            if self.ffprobe_path is not None:
                audio_presence = {}
                for clip in edl["clips"]:
                    asset_id = clip["asset_id"]
                    if asset_id not in audio_presence:
                        audio_presence[asset_id] = has_audio_stream(
                            assets[asset_id], self.ffprobe_path
                        )
                    if audio_presence[asset_id]:
                        tracks.append({
                            "path": str(assets[asset_id]),
                            "source_in_ms": round(clip["source_in_ms"]),
                            "start_ms": round(clip["start_ms"]),
                            "duration_ms": round(clip["end_ms"] - clip["start_ms"]),
                            "gain": 1.0,
                        })
            if self.audio_tracks_resolver:
                additional_tracks = self.audio_tracks_resolver(payload)
                if not isinstance(additional_tracks, list):
                    raise EDLRenderError("audio resolver must return a list of trusted tracks")
                tracks.extend(additional_tracks)
            if len(tracks) > 8:
                raise EDLRenderError("combined source and bed audio is limited to eight tracks")
            for track in tracks:
                track_path = _regular_file(track.get("path") if isinstance(track, dict) else None,
                                           "resolved audio track")
                if track_path.stat().st_size > self.max_input_bytes:
                    raise EDLRenderError("audio track exceeds configured input byte limit")
            if tracks:
                mix_argv = build_audio_mix_argv(
                    tracks, mixed_audio, ffmpeg_path=self.ffmpeg_path,
                    output_duration_ms=duration_ms,
                )
                self._run(mix_argv, stop_event, deadline, log_path)
                if not mixed_audio.is_file() or mixed_audio.stat().st_size < 1:
                    raise EDLRenderError("FFmpeg did not produce a non-empty audio mix")
                mux_argv = [
                    self.ffmpeg_path, "-nostdin", "-hide_banner", "-y",
                    "-threads", "2", "-i", str(video_only), "-i", str(mixed_audio),
                    "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                    "-c:a", "copy", "-t", f"{duration_ms / 1000.0:.3f}",
                    "-movflags", "+faststart", str(final_output),
                ]
                self._run(mux_argv, stop_event, deadline, log_path)
            else:
                os.replace(video_only, final_output)
            if stop_event.is_set():
                raise EDLRenderError("render lease was lost before staged output handoff")
            if not final_output.is_file() or final_output.stat().st_size < 1:
                raise EDLRenderError("render output is missing or empty")
            return {"staged_path": str(final_output), "duration_ms": duration_ms}
        except Exception:
            final_output.unlink(missing_ok=True)
            raise
        finally:
            for child in work_dir.iterdir():
                child.unlink(missing_ok=True)
            work_dir.rmdir()
