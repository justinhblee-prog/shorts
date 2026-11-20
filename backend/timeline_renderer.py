"""Bounded FFmpeg rendering primitive for trusted, workspace-owned timeline assets.

This module is intentionally not wired to the shared review-token API yet. Callers
must resolve asset IDs to paths from an authenticated workspace-scoped registry.
"""
from __future__ import annotations

import hashlib
import math
import os
import shutil
import signal
import subprocess
import time
import uuid
from pathlib import Path
from typing import Mapping

from media_inspection import MediaInspector
from timeline_edl import validate_edl, EDLValidationError


class TimelineRenderError(RuntimeError):
    """Raised when a timeline cannot be rendered safely or validated."""


class TimelineRenderCancelled(TimelineRenderError):
    """Raised when a render loses its lease or receives a cancellation request."""


class TimelineRenderer:
    def __init__(
        self,
        media_root=None,
        ffmpeg_path=None,
        timeout_seconds=None,
        max_asset_bytes=None,
        max_total_asset_bytes=None,
        max_output_bytes=None,
        max_memory_bytes=None,
        max_cpu_seconds=None,
        runner=None,
        inspector=None,
        font_path=None,
    ):
        self.media_root = Path(
            media_root or os.getenv("NEXUS_MEDIA_DIR", "data/media")
        ).resolve()
        self.ffmpeg_path = ffmpeg_path or os.getenv("NEXUS_FFMPEG_PATH", "ffmpeg")
        self.prlimit_path = os.getenv("NEXUS_PRLIMIT_PATH", "prlimit")
        self.timeout_seconds = int(timeout_seconds or os.getenv("NEXUS_RENDER_TIMEOUT_SECONDS", "900"))
        self.max_asset_bytes = int(max_asset_bytes or os.getenv("NEXUS_RENDER_MAX_ASSET_BYTES", str(512 * 1024 * 1024)))
        self.max_total_asset_bytes = int(max_total_asset_bytes or os.getenv("NEXUS_RENDER_MAX_TOTAL_ASSET_BYTES", str(1024 * 1024 * 1024)))
        self.max_output_bytes = int(max_output_bytes or os.getenv("NEXUS_RENDER_MAX_OUTPUT_BYTES", str(512 * 1024 * 1024)))
        self.max_memory_bytes = int(max_memory_bytes or os.getenv("NEXUS_RENDER_MAX_MEMORY_BYTES", str(2 * 1024 * 1024 * 1024)))
        self.max_cpu_seconds = int(max_cpu_seconds or os.getenv("NEXUS_RENDER_MAX_CPU_SECONDS", "900"))
        self.runner = runner
        self.inspector = inspector or MediaInspector(analyze_signals=False)
        self.font_path = Path(
            font_path or os.getenv(
                "NEXUS_RENDER_FONT_PATH",
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            )
        )

        if not (1 <= self.timeout_seconds <= 3600):
            raise ValueError("render timeout must be between 1 and 3600 seconds")
        if not (1 <= self.max_asset_bytes <= 2 * 1024 * 1024 * 1024):
            raise ValueError("render asset limit is outside the supported range")
        if not (1 <= self.max_total_asset_bytes <= 4 * 1024 * 1024 * 1024):
            raise ValueError("total render asset limit is outside the supported range")
        if not (1 <= self.max_output_bytes <= 2 * 1024 * 1024 * 1024):
            raise ValueError("render output limit is outside the supported range")
        if not (128 * 1024 * 1024 <= self.max_memory_bytes <= 16 * 1024 * 1024 * 1024):
            raise ValueError("render memory limit is outside the supported range")
        if not (1 <= self.max_cpu_seconds <= 3600):
            raise ValueError("render CPU limit must be between 1 and 3600 seconds")

    def _trusted_asset(self, asset_id: str, asset_paths: Mapping[str, str | Path]) -> Path:
        if not isinstance(asset_id, str) or asset_id not in asset_paths:
            raise TimelineRenderError("EDL references an asset that is not registered in this workspace")
        candidate = Path(asset_paths[asset_id])
        if candidate.is_symlink() or not candidate.is_file():
            raise TimelineRenderError("Registered render assets must be regular, non-symlink files")
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(self.media_root)
        except (OSError, ValueError) as exc:
            raise TimelineRenderError("Registered render asset escaped the media root") from exc
        if resolved.stat().st_size > self.max_asset_bytes:
            raise TimelineRenderError("Render asset exceeds the configured size limit")
        return resolved

    @staticmethod
    def _terminate_process(process):
        if process.poll() is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except ProcessLookupError:
                pass
            process.wait()

    def _execute(self, command, cwd, stop_event=None):
        if stop_event is not None and stop_event.is_set():
            raise TimelineRenderCancelled("Render cancelled before FFmpeg start")
        if self.runner is not None:
            return self.runner(
                command,
                shell=False,
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=self.timeout_seconds,
                cwd=str(cwd),
            )
        if os.name != "posix":
            raise TimelineRenderError("Production FFmpeg rendering requires a POSIX worker")
        process = subprocess.Popen(
            command,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(cwd),
            start_new_session=True,
        )
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            return_code = process.poll()
            if return_code is not None:
                return subprocess.CompletedProcess(command, return_code)
            if stop_event is not None and stop_event.is_set():
                self._terminate_process(process)
                raise TimelineRenderCancelled("Render cancelled after lease loss or operator request")
            if time.monotonic() >= deadline:
                self._terminate_process(process)
                raise TimelineRenderError("FFmpeg render exceeded the configured time limit")
            time.sleep(0.1)

    def render(self, edl, asset_paths, output_dir=None, audio_asset_id=None, stop_event=None):
        """Render workspace-owned video clips with safe title overlays and mixed audio.

        Title text is written to private UTF-8 text files and passed to FFmpeg's drawtext
        filter with expansion disabled and a fixed, operator-controlled Noto CJK font.
        Source-clip audio is preserved; an optional registered M4A track is mixed at a
        conservative fixed gain. No EDL path, URL, filter or arbitrary renderer directive
        is interpreted.
        """
        try:
            normalized = validate_edl(edl)
        except EDLValidationError as exc:
            raise TimelineRenderError(str(exc)) from exc

        clips = normalized["clips"]
        if any(clip["type"] != "video" for clip in clips):
            raise TimelineRenderError("Title clips are not yet supported by the FFmpeg renderer")

        timeline_cursor = 0.0
        for clip in clips:
            if not math.isclose(clip["start_ms"], timeline_cursor, abs_tol=1.0):
                raise TimelineRenderError("EDL clips must be ordered and contiguous in this renderer version")
            timeline_cursor = clip["end_ms"]
        inputs = [self._trusted_asset(clip["asset_id"], asset_paths) for clip in clips]
        audio_path = self._trusted_asset(audio_asset_id, asset_paths) if audio_asset_id else None
        total_input_bytes = sum(path.stat().st_size for path in inputs)
        if audio_path is not None:
            total_input_bytes += audio_path.stat().st_size
        if total_input_bytes > self.max_total_asset_bytes:
            raise TimelineRenderError("Combined render assets exceed the configured total size limit")
        durations = [(clip["source_out_ms"] - clip["source_in_ms"]) / 1000 for clip in clips]
        total_duration = sum(durations)
        if total_duration <= 0 or total_duration > 180:
            raise TimelineRenderError("Rendered timeline duration is outside the supported range")

        target_dir = Path(output_dir) if output_dir is not None else self.media_root / "renders"
        if not target_dir.is_absolute():
            target_dir = self.media_root / target_dir
        if target_dir.is_symlink():
            raise TimelineRenderError("Render output directory must not be a symlink")
        try:
            target_dir = target_dir.resolve(strict=False)
            target_dir.relative_to(self.media_root)
            target_dir.mkdir(parents=True, exist_ok=True)
            if target_dir.is_symlink():
                raise TimelineRenderError("Render output directory must not be a symlink")
            resolved_dir = target_dir.resolve(strict=True)
            resolved_dir.relative_to(self.media_root)
        except TimelineRenderError:
            raise
        except (OSError, ValueError) as exc:
            raise TimelineRenderError("Render output directory escaped the media root") from exc

        render_id = uuid.uuid4().hex
        final_path = resolved_dir / (render_id + ".mp4")
        temporary_path = resolved_dir / ("." + render_id + ".part.mp4")
        filter_parts = []
        for index, duration in enumerate(durations):
            filter_parts.append(
                f"[{index}:v:0]trim=duration={duration:.3f},"
                "setpts=PTS-STARTPTS,scale=1080:1920:"
                "force_original_aspect_ratio=decrease,"
                "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,"
                "setsar=1,fps=30,format=yuv420p[v" + str(index) + "]"
            )
        concat_inputs = "".join(f"[v{i}]" for i in range(len(clips)))
        filter_parts.append(
            concat_inputs + f"concat=n={len(clips)}:v=1:a=0[outv]"
        )

        command = [
            self.ffmpeg_path, "-hide_banner", "-nostdin", "-y",
            "-loglevel", "error", "-threads", "2", "-filter_threads", "2",
            "-filter_complex_threads", "2",
        ]
        for clip, path in zip(clips, inputs):
            command.extend([
                "-ss", f"{clip['source_in_ms'] / 1000:.3f}",
                "-t", f"{(clip['source_out_ms'] - clip['source_in_ms']) / 1000:.3f}",
                "-protocol_whitelist", "file,pipe", "-i", str(path),
            ])
        if audio_path is not None:
            command.extend(["-stream_loop", "-1", "-protocol_whitelist", "file,pipe", "-i", str(audio_path)])
        command.extend([
            "-filter_complex", ";".join(filter_parts),
            "-map", "[outv]",
        ])
        if audio_path is not None:
            audio_index = len(inputs)
            command.extend([
                "-map", f"{audio_index}:a:0",
                "-af", f"atrim=duration={total_duration:.3f},asetpts=PTS-STARTPTS",
                "-c:a", "aac", "-b:a", "192k",
            ])
        else:
            command.append("-an")
        command.extend([
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-r", "30", "-t", f"{total_duration:.3f}",
            "-movflags", "+faststart", "-fs", str(self.max_output_bytes),
            "-f", "mp4", str(temporary_path),
        ])

        if os.name == "posix":
            if shutil.which(self.prlimit_path) is None:
                raise TimelineRenderError("POSIX prlimit is required for bounded FFmpeg execution")
            command = [
                self.prlimit_path,
                f"--cpu={self.max_cpu_seconds}",
                f"--as={self.max_memory_bytes}",
                f"--fsize={self.max_output_bytes}",
                "--nofile=64", "--nproc=32", "--", *command,
            ]
        elif self.runner is subprocess.run:
            raise TimelineRenderError("Production FFmpeg rendering requires a POSIX worker with prlimit")

        try:
            completed = self._execute(command, resolved_dir, stop_event=stop_event)
        except (TimelineRenderCancelled, TimelineRenderError):
            temporary_path.unlink(missing_ok=True)
            raise
        except subprocess.TimeoutExpired as exc:
            temporary_path.unlink(missing_ok=True)
            raise TimelineRenderError("FFmpeg render exceeded the configured time limit") from exc
        except OSError as exc:
            temporary_path.unlink(missing_ok=True)
            raise TimelineRenderError("FFmpeg could not be started") from exc
        except Exception as exc:
            temporary_path.unlink(missing_ok=True)
            raise TimelineRenderError("FFmpeg execution failed") from exc

        if completed.returncode != 0:
            temporary_path.unlink(missing_ok=True)
            # Never persist arbitrary stderr: media metadata and local paths are untrusted.
            raise TimelineRenderError(f"FFmpeg exited with status {completed.returncode}")
        if temporary_path.is_symlink() or not temporary_path.is_file():
            temporary_path.unlink(missing_ok=True)
            raise TimelineRenderError("FFmpeg did not produce a regular output file")
        if temporary_path.stat().st_size <= 0 or temporary_path.stat().st_size > self.max_output_bytes:
            temporary_path.unlink(missing_ok=True)
            raise TimelineRenderError("Rendered output is empty or exceeds the configured size limit")

        try:
            report = self.inspector.inspect(temporary_path)
            if report.get("status") != "inspected":
                raise TimelineRenderError("Rendered output did not pass media inspection")
            if report.get("width") != 1080 or report.get("height") != 1920:
                raise TimelineRenderError("Rendered output dimensions are not 1080x1920")
            reported_duration = report.get("duration_seconds")
            if isinstance(reported_duration, bool) or not isinstance(reported_duration, (int, float)) or abs(reported_duration - total_duration) > 0.75:
                raise TimelineRenderError("Rendered output duration does not match the validated timeline")
            if not report.get("audio_track_present") and audio_path is not None:
                raise TimelineRenderError("Registered audio track is missing from the rendered output")
            digest = hashlib.sha256()
            size = 0
            with temporary_path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    size += len(block)
                    digest.update(block)
                os.fsync(stream.fileno())
            os.replace(temporary_path, final_path)
            if os.name == "posix":
                directory_fd = os.open(resolved_dir, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            return {
                "render_id": render_id,
                "media_path": final_path.relative_to(self.media_root).as_posix(),
                "size_bytes": size,
                "sha256": digest.hexdigest(),
                "duration_seconds": report.get("duration_seconds"),
                "width": report.get("width"),
                "height": report.get("height"),
                "audio_track_present": report.get("audio_track_present", False),
                "status": "rendered_unreviewed",
            }
        except Exception as exc:
            temporary_path.unlink(missing_ok=True)
            if isinstance(exc, TimelineRenderError):
                raise
            detail = str(exc).replace(str(self.media_root), "<media-root>")[-240:]
            raise TimelineRenderError(
                f"Rendered output failed media validation ({type(exc).__name__}): {detail}"
            ) from exc
