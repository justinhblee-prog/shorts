"""Lease-cancellable, argv-only EDL v1 renderer for private local media assets.

The renderer supports ordered video clips joined by hard cuts, declared
crossfades or explicit black intervals, an optional trailing black duration,
bounded timed title overlays, and up to eight bounded audio tracks. Every
join is checked against its declared timeline interval before FFmpeg runs.
Title text is staged as UTF-8 text files and rendered with a trusted configured
font. All source media is resolved by a trusted workspace asset callback;
arbitrary paths and URLs never come from the EDL.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from ffmpeg_audio_mix import build_audio_mix_argv
from ffprobe_validate import FFprobeValidationError, probe_media, probe_source_media
from timeline_edl import validate_edl


class TimelineRenderError(RuntimeError):
    """The EDL could not be rendered safely."""


class RenderCancelled(TimelineRenderError):
    """The worker lease was lost or the render was cancelled."""


def run_bounded_process(argv, *, timeout_seconds, stop_event=None):
    """Run a fixed argv without a shell, bounded by time and lease cancellation."""
    if not isinstance(argv, list) or not argv or not all(isinstance(x, str) for x in argv):
        raise TimelineRenderError("process argv must be a non-empty string list")
    if any("\x00" in item for item in argv):
        raise TimelineRenderError("process argv contains a null byte")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not 1 <= timeout_seconds <= 3600:
        raise TimelineRenderError("process timeout must be between 1 and 3600 seconds")

    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    with tempfile.TemporaryFile() as stderr_file:
        try:
            process = subprocess.Popen(
                argv, shell=False, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=stderr_file,
                creationflags=flags, start_new_session=(os.name != "nt"),
            )
        except OSError as exc:
            raise TimelineRenderError("media process could not be started") from exc

        started = time.monotonic()
        cancelled = False
        timed_out = False
        while process.poll() is None:
            if stop_event is not None and stop_event.is_set():
                cancelled = True
                break
            if time.monotonic() - started > float(timeout_seconds):
                timed_out = True
                break
            time.sleep(0.05)

        if cancelled or timed_out:
            try:
                if os.name == "nt":
                    process.kill()
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
                    pass
                process.wait()
        return_code = process.wait()
        stderr_file.seek(0, os.SEEK_END)
        length = stderr_file.tell()
        stderr_file.seek(max(0, length - 4096))
        detail = stderr_file.read(4096).decode("utf-8", errors="replace")
        if cancelled:
            raise RenderCancelled("render process stopped after worker lease loss")
        if timed_out:
            raise TimelineRenderError("media process exceeded its execution timeout")
        if return_code != 0:
            raise TimelineRenderError(("media process failed: " + detail)[-4200:])
        return {"returncode": return_code}


def workspace_asset_resolver(asset_store):
    """Build a resolver that verifies clean asset bytes and returns path + digest."""
    def resolve(workspace_id, principal_id, asset_id):
        metadata = asset_store.get_asset(workspace_id, principal_id, asset_id)
        if metadata["scan_status"] != "clean":
            raise TimelineRenderError("asset is quarantined or rejected")
        with asset_store.open_clean_asset(workspace_id, principal_id, asset_id) as handle:
            return {"path": handle.name, "sha256": metadata["sha256"]}
    return resolve


def _filter_path(value):
    """Escape a trusted local path for an FFmpeg filter option."""
    raw = Path(value).resolve(strict=True).as_posix()
    for char in ("\\", "'", ":", ",", "[", "]", ";"):
        raw = raw.replace(char, "\\" + char)
    return "'" + raw + "'"

class TimelineFFmpegRenderer:
    def __init__(self, staging_root, asset_resolver, ffmpeg_path, ffprobe_path,
                 *, width=1080, height=1920, fps=30,
                 max_input_bytes=2_000_000_000, max_output_bytes=2_000_000_000,
                 timeout_seconds=900, process_runner=None, font_path=None):
        self.staging_root = Path(staging_root).resolve()
        self.staging_root.mkdir(parents=True, exist_ok=True)
        self.asset_resolver = asset_resolver
        self.ffmpeg_path = self._binary(ffmpeg_path, "FFmpeg")
        self.ffprobe_path = self._binary(ffprobe_path, "ffprobe")
        self.font_path = self._binary(font_path, "font") if font_path is not None else None
        if not callable(asset_resolver):
            raise TypeError("asset_resolver callback is required")
        for value, name in ((width, "width"), (height, "height")):
            if isinstance(value, bool) or not isinstance(value, int) or not 16 <= value <= 8192 or value % 2:
                raise ValueError(f"{name} must be an even integer from 16 to 8192")
        if isinstance(fps, bool) or not isinstance(fps, int) or not 1 <= fps <= 60:
            raise ValueError("fps must be an integer from 1 to 60")
        if isinstance(max_input_bytes, bool) or not isinstance(max_input_bytes, int) or max_input_bytes < 1:
            raise ValueError("max_input_bytes must be a positive integer")
        if isinstance(max_output_bytes, bool) or not isinstance(max_output_bytes, int) or max_output_bytes < 1:
            raise ValueError("max_output_bytes must be a positive integer")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not 1 <= timeout_seconds <= 3600:
            raise ValueError("timeout_seconds must be between 1 and 3600")
        self.width = width
        self.height = height
        self.fps = fps
        self.max_input_bytes = max_input_bytes
        self.max_output_bytes = max_output_bytes
        self.timeout_seconds = float(timeout_seconds)
        self.process_runner = process_runner or run_bounded_process

    @staticmethod
    def _binary(value, label):
        path = Path(value)
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise ValueError(f"{label} binary must be an absolute regular non-symlink file")
        return str(path.resolve(strict=True))

    @staticmethod
    def _seconds(milliseconds):
        return f"{float(milliseconds) / 1000:.3f}"

    def _stage_asset(self, workspace_id, principal_id, asset_id, work_dir, index, byte_limit):
        resolved = self.asset_resolver(workspace_id, principal_id, asset_id)
        if isinstance(resolved, dict):
            source = Path(resolved.get("path", ""))
            expected = resolved.get("sha256")
        else:
            source = Path(resolved)
            expected = None
        if not source.is_absolute() or source.is_symlink() or not source.is_file():
            raise TimelineRenderError("asset resolver returned an unsafe local file")
        source = source.resolve(strict=True)
        staged = work_dir / f"input_{index:02d}.blob"
        digest = hashlib.sha256()
        size = 0
        with source.open("rb") as src, staged.open("xb") as dst:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > byte_limit:
                    raise TimelineRenderError("aggregate source assets exceed configured byte limit")
                digest.update(chunk)
                dst.write(chunk)
            dst.flush()
            os.fsync(dst.fileno())
        if size < 1 or (expected is not None and digest.hexdigest() != expected):
            staged.unlink(missing_ok=True)
            raise TimelineRenderError("source asset checksum does not match trusted metadata")
        return staged, size

    def _run(self, argv, stop_event):
        result = self.process_runner(
            argv, timeout_seconds=self.timeout_seconds, stop_event=stop_event
        )
        if result is False:
            raise TimelineRenderError("media process runner reported failure")

    def __call__(self, payload, *, stop_event, workspace_id, principal_id=None):
        if not isinstance(payload, dict) or not isinstance(payload.get("edl"), dict):
            raise TimelineRenderError("render job payload is missing its immutable EDL")
        if not isinstance(workspace_id, str) or not workspace_id:
            raise TimelineRenderError("workspace identity is required")
        principal_id = principal_id or payload.get("creator_principal_id")
        if not isinstance(principal_id, str) or not principal_id:
            raise TimelineRenderError("asset owner principal is required")

        edl = validate_edl(payload["edl"])
        snapshot_sha256 = payload.get("snapshot_sha256")
        if not isinstance(snapshot_sha256, str) or len(snapshot_sha256) != 64:
            raise TimelineRenderError("render job snapshot digest is missing or invalid")
        # Preserve the original EDL v1 digest for queued jobs created before
        # optional audio_tracks became part of the normalized snapshot payload.
        digest_payload = edl
        if "audio_tracks" not in payload["edl"] or "transitions" not in payload["edl"]:
            digest_payload = dict(edl)
            if "audio_tracks" not in payload["edl"]:
                digest_payload.pop("audio_tracks", None)
            if "transitions" not in payload["edl"]:
                digest_payload.pop("transitions", None)
        canonical = json.dumps(
            digest_payload, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        if hashlib.sha256(canonical).hexdigest() != snapshot_sha256:
            raise TimelineRenderError("render job EDL does not match its immutable snapshot digest")
        clips = sorted(edl["clips"], key=lambda item: (item["start_ms"], item["id"]))
        video_clips = [clip for clip in clips if clip["type"] == "video"]
        title_clips = [clip for clip in clips if clip["type"] == "title"]
        if not video_clips:
            raise TimelineRenderError("timeline must contain at least one video clip")
        if title_clips and self.font_path is None:
            raise TimelineRenderError("a configured font file is required for title overlays")
        transitions = edl.get("transitions", [])
        gaps = edl.get("gaps", [])
        transition_by_pair = {
            (item["from_clip_id"], item["to_clip_id"]): item
            for item in transitions
        }
        gap_by_pair = {
            (item["after_clip_id"], item["before_clip_id"]): item
            for item in gaps
        }
        cursor = 0.0
        for index, clip in enumerate(video_clips):
            pair = (video_clips[index - 1]["id"], clip["id"]) if index else None
            transition = transition_by_pair.get(pair) if pair else None
            gap = gap_by_pair.get(pair) if pair else None
            overlap_ms = float(transition["duration_ms"]) if transition else 0.0
            gap_ms = float(gap["duration_ms"]) if gap else 0.0
            expected_start = cursor - overlap_ms + gap_ms
            if abs(float(clip["start_ms"]) - expected_start) > 1.0:
                raise TimelineRenderError(
                    "video clips must be sequential; undeclared gaps or overlaps require an explicit crossfade or black-gap interval"
                )
            if transition and overlap_ms >= min(
                float(video_clips[index - 1]["end_ms"] - video_clips[index - 1]["start_ms"]),
                float(clip["end_ms"] - clip["start_ms"]),
            ):
                raise TimelineRenderError("crossfade duration must be shorter than both adjacent clips")
            cursor = float(clip["end_ms"])
        video_duration_ms = int(round(cursor))
        duration_ms = int(edl.get("project_duration_ms", video_duration_ms))
        if duration_ms < video_duration_ms:
            raise TimelineRenderError("project duration cannot be shorter than the video timeline")
        if duration_ms < 1 or duration_ms > 3_600_000:
            raise TimelineRenderError("timeline duration is outside configured limits")
        if any(float(clip["end_ms"]) > duration_ms for clip in title_clips):
            raise TimelineRenderError("title overlay extends beyond the project duration")

        job_dir = Path(tempfile.mkdtemp(prefix=".render-", dir=str(self.staging_root)))
        final_path = self.staging_root / ("render_" + uuid.uuid4().hex + ".mp4")
        video_path = job_dir / "video_only.mp4"
        audio_path = job_dir / "audio_mix.m4a"
        keep_final = False
        try:
            staged_video = []
            total_input_bytes = 0
            argv = [
                self.ffmpeg_path, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                "-filter_threads", "2",
            ]
            source_metadata = {}
            for index, clip in enumerate(video_clips):
                if stop_event is not None and stop_event.is_set():
                    raise RenderCancelled("render cancelled before video encoding")
                staged, size = self._stage_asset(
                    workspace_id, principal_id, clip["asset_id"], job_dir, index,
                    self.max_input_bytes - total_input_bytes,
                )
                total_input_bytes += size
                staged_video.append(staged)
                if clip["asset_id"] not in source_metadata:
                    try:
                        source_metadata[clip["asset_id"]] = probe_source_media(
                            staged, self.ffprobe_path, max_bytes=self.max_input_bytes,
                            timeout_seconds=min(self.timeout_seconds, 60),
                        )
                    except FFprobeValidationError as exc:
                        raise TimelineRenderError("video source failed bounded ffprobe validation") from exc
                source = source_metadata[clip["asset_id"]]
                if not source["has_video"]:
                    raise TimelineRenderError("video source has no video stream")
                if clip["source_out_ms"] > source["duration_ms"] + 1:
                    raise TimelineRenderError("video source trim exceeds probed media duration")
                argv.extend(["-protocol_whitelist", "file,pipe", "-i", str(staged)])

            filters = []
            labels = []
            for index, clip in enumerate(video_clips):
                label = f"v{index}"
                filters.append(
                    f"[{index}:v:0]trim=start={self._seconds(clip['source_in_ms'])}:"
                    f"end={self._seconds(clip['source_out_ms'])},"
                    "setpts=PTS-STARTPTS,"
                    f"scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,"
                    f"pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2,"
                    f"setsar=1,fps={self.fps},format=yuv420p[{label}]"
                )
                labels.append(f"[{label}]")
            if transitions or gaps:
                output_label = labels[0][1:-1]
                accumulated_ms = float(video_clips[0]["end_ms"] - video_clips[0]["start_ms"])
                for index in range(1, len(video_clips)):
                    pair = (video_clips[index - 1]["id"], video_clips[index]["id"])
                    transition = transition_by_pair.get(pair)
                    gap = gap_by_pair.get(pair)
                    next_label = f"vtransition{index}"
                    if transition:
                        overlap_ms = float(transition["duration_ms"])
                        offset_ms = accumulated_ms - overlap_ms
                        filters.append(
                            f"[{output_label}][{labels[index][1:-1]}]"
                            f"xfade=transition=fade:duration={self._seconds(overlap_ms)}:"
                            f"offset={self._seconds(offset_ms)}[{next_label}]"
                        )
                        accumulated_ms += float(video_clips[index]["end_ms"] - video_clips[index]["start_ms"]) - overlap_ms
                    elif gap:
                        gap_ms = float(gap["duration_ms"])
                        gap_label = f"vblack{index}"
                        joined_label = f"vblackjoin{index}"
                        filters.append(
                            f"color=c=black:s={self.width}x{self.height}:r={self.fps}:"
                            f"d={self._seconds(gap_ms)},format=yuv420p[{gap_label}]"
                        )
                        filters.append(
                            f"[{output_label}][{gap_label}]concat=n=2:v=1:a=0[{joined_label}]"
                        )
                        filters.append(
                            f"[{joined_label}][{labels[index][1:-1]}]concat=n=2:v=1:a=0[{next_label}]"
                        )
                        accumulated_ms += gap_ms + float(video_clips[index]["end_ms"] - video_clips[index]["start_ms"])
                    else:
                        filters.append(
                            f"[{output_label}][{labels[index][1:-1]}]concat=n=2:v=1:a=0[{next_label}]"
                        )
                        accumulated_ms += float(video_clips[index]["end_ms"] - video_clips[index]["start_ms"])
                    output_label = next_label
            else:
                filters.append(
                    "".join(labels) + f"concat=n={len(labels)}:v=1:a=0[vout]"
                )
                output_label = "vout"
            trailing_gap_ms = duration_ms - video_duration_ms
            if trailing_gap_ms > 0:
                padded_label = "vpad"
                filters.append(
                    f"[{output_label}]tpad=stop_mode=add:stop_duration={self._seconds(trailing_gap_ms)}:color=black[{padded_label}]"
                )
                output_label = padded_label
            if title_clips:
                font_file = _filter_path(self.font_path)
                for index, clip in enumerate(title_clips):
                    if stop_event is not None and stop_event.is_set():
                        raise RenderCancelled("render cancelled while staging title overlays")
                    text_path = job_dir / f"title_{index:02d}.txt"
                    text_path.write_text(clip["text"], encoding="utf-8")
                    text_file = _filter_path(str(text_path))
                    next_label = f"title{index}"
                    begin = self._seconds(clip["start_ms"])
                    end = self._seconds(clip["end_ms"])
                    filters.append(
                        f"[{output_label}]drawtext=fontfile={font_file}:textfile={text_file}:"
                        "expansion=none:fontsize=58:fontcolor=white:borderw=3:bordercolor=black:"
                        f"x=(w-text_w)/2:y=h*0.78:enable='between(t,{begin},{end})'[{next_label}]"
                    )
                    output_label = next_label
            argv.extend([
                "-filter_complex", ";".join(filters), "-map", f"[{output_label}]", "-an",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-threads", "2",
                "-r", str(self.fps), "-pix_fmt", "yuv420p",
                "-t", self._seconds(duration_ms), "-movflags", "+faststart",
                "-fs", str(self.max_output_bytes), str(video_path),
            ])
            self._run(argv, stop_event)

            audio_tracks = edl["audio_tracks"]
            if audio_tracks:
                prepared_audio = []
                for index, track in enumerate(audio_tracks, start=len(staged_video)):
                    if track["start_ms"] + track["source_out_ms"] - track["source_in_ms"] > duration_ms:
                        raise TimelineRenderError("audio track extends beyond the video timeline")
                    staged, size = self._stage_asset(
                        workspace_id, principal_id, track["asset_id"], job_dir, index,
                        self.max_input_bytes - total_input_bytes,
                    )
                    total_input_bytes += size
                    if track["asset_id"] not in source_metadata:
                        try:
                            source_metadata[track["asset_id"]] = probe_source_media(
                                staged, self.ffprobe_path, max_bytes=self.max_input_bytes,
                                timeout_seconds=min(self.timeout_seconds, 60),
                            )
                        except FFprobeValidationError as exc:
                            raise TimelineRenderError("audio source failed bounded ffprobe validation") from exc
                    source = source_metadata[track["asset_id"]]
                    if not source["has_audio"]:
                        raise TimelineRenderError("audio source has no audio stream")
                    if track["source_out_ms"] > source["duration_ms"] + 1:
                        raise TimelineRenderError("audio source trim exceeds probed media duration")
                    prepared_audio.append({
                        "path": str(staged), "start_ms": int(track["start_ms"]),
                        "source_in_ms": int(track["source_in_ms"]),
                        "duration_ms": int(track["source_out_ms"] - track["source_in_ms"]),
                        "gain": track["gain"], "fade_in_ms": int(track["fade_in_ms"]),
                        "fade_out_ms": int(track["fade_out_ms"]),
                    })
                audio_argv = build_audio_mix_argv(
                    prepared_audio, str(audio_path), ffmpeg_path=self.ffmpeg_path,
                    output_duration_ms=duration_ms,
                    max_output_bytes=self.max_output_bytes,
                )
                self._run(audio_argv, stop_event)
                mux_argv = [
                    self.ffmpeg_path, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                    "-protocol_whitelist", "file,pipe", "-i", str(video_path),
                    "-protocol_whitelist", "file,pipe", "-i", str(audio_path),
                    "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "copy",
                    "-t", self._seconds(duration_ms), "-movflags", "+faststart",
                    "-fs", str(self.max_output_bytes), str(final_path),
                ]
                self._run(mux_argv, stop_event)
            else:
                os.replace(video_path, final_path)

            if stop_event is not None and stop_event.is_set():
                raise RenderCancelled("render cancelled before output validation")
            size = final_path.stat().st_size
            if size < 1 or size > self.max_output_bytes:
                raise TimelineRenderError("rendered output size is outside configured limits")
            probe = probe_media(
                final_path, self.ffprobe_path,
                max_duration_ms=min(duration_ms + 1000, 3_600_000),
                max_bytes=self.max_output_bytes, require_audio=bool(audio_tracks),
            )
            if abs(probe["duration_ms"] - duration_ms) > 1500:
                raise TimelineRenderError("rendered output duration does not match the EDL")
            keep_final = True
            return {
                "staged_path": str(final_path),
                "byte_size": size,
                "duration_ms": probe["duration_ms"],
                "video_streams": probe["video_streams"],
                "audio_streams": probe["audio_streams"],
            }
        except Exception:
            final_path.unlink(missing_ok=True)
            raise
        finally:
            shutil.rmtree(job_dir, ignore_errors=True)
            if not keep_final:
                final_path.unlink(missing_ok=True)
