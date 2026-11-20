"""Bounded FFmpeg process execution and verified atomic artifact adoption.

This module deliberately does not claim OS/container isolation. Production callers
must run it inside a dedicated worker with externally enforced CPU, memory, disk,
network and process-count limits.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
from typing import Sequence


class RenderExecutionError(RuntimeError):
    """A render failed validation or could not be safely adopted."""


def _regular_output_root(value: str | os.PathLike) -> Path:
    root = Path(value)
    if not root.is_absolute() or root.is_symlink():
        raise RenderExecutionError("output root must be an absolute non-symlink directory")
    try:
        resolved = root.resolve(strict=True)
    except OSError as exc:
        raise RenderExecutionError("output root is unavailable") from exc
    if not resolved.is_dir():
        raise RenderExecutionError("output root must be a directory")
    return resolved


def _terminate_process(process: subprocess.Popen, grace_seconds: float = 2.0) -> None:
    """Terminate the complete process group where the platform supports it."""
    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=grace_seconds)
    except (OSError, subprocess.TimeoutExpired):
        try:
            if os.name == "nt":
                process.kill()
            else:
                os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            process.kill()
        try:
            process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def _run_bounded(argv: Sequence[str], *, timeout_seconds: int,
                 max_output_bytes: int, output_path: Path) -> None:
    if not isinstance(argv, (list, tuple)) or not argv or any(
        not isinstance(item, str) or not item or "\x00" in item for item in argv
    ):
        raise RenderExecutionError("renderer command must be a non-empty argument array")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 3600:
        raise RenderExecutionError("render timeout must be between 1 and 3600 seconds")
    if isinstance(max_output_bytes, bool) or not isinstance(max_output_bytes, int) or not 1024 <= max_output_bytes <= 2 * 1024**3:
        raise RenderExecutionError("render output limit must be between 1 KiB and 2 GiB")
    kwargs = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
              "stderr": subprocess.PIPE, "shell": False}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    try:
        process = subprocess.Popen(list(argv), **kwargs)
    except OSError as exc:
        raise RenderExecutionError("FFmpeg executable could not be started") from exc
    started = time.monotonic()
    try:
        while process.poll() is None:
            if time.monotonic() - started > timeout_seconds:
                raise RenderExecutionError("FFmpeg render exceeded its time limit")
            if output_path.exists() and output_path.stat().st_size > max_output_bytes:
                raise RenderExecutionError("FFmpeg render exceeded its output-size limit")
            time.sleep(0.05)
        stderr = process.stderr.read(8192) if process.stderr else b""
        if process.returncode != 0:
            # Do not persist arbitrary FFmpeg stderr; it can contain source paths.
            raise RenderExecutionError(f"FFmpeg exited with status {process.returncode}")
        if not output_path.is_file() or output_path.is_symlink():
            raise RenderExecutionError("FFmpeg did not create a regular output file")
        if output_path.stat().st_size > max_output_bytes:
            raise RenderExecutionError("FFmpeg render exceeded its output-size limit")
    except Exception:
        if process.poll() is None:
            _terminate_process(process)
        raise
    finally:
        if process.stderr:
            process.stderr.close()


def _probe(ffprobe_path: str, media_path: Path, timeout_seconds: int) -> dict:
    if not isinstance(ffprobe_path, str) or not ffprobe_path or "\x00" in ffprobe_path:
        raise RenderExecutionError("configured ffprobe executable is invalid")
    argv = [ffprobe_path, "-v", "error", "-show_entries",
            "format=duration,format_name:stream=codec_type,codec_name,width,height",
            "-of", "json", str(media_path)]
    try:
        result = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=min(timeout_seconds, 30),
                                check=False, shell=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RenderExecutionError("ffprobe validation could not complete") from exc
    if result.returncode != 0 or len(result.stdout) > 1024 * 1024:
        raise RenderExecutionError("ffprobe rejected the rendered artifact")
    try:
        data = json.loads(result.stdout.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise RenderExecutionError("ffprobe returned invalid metadata") from exc
    streams = data.get("streams") if isinstance(data, dict) else None
    video = [s for s in streams or [] if isinstance(s, dict) and s.get("codec_type") == "video"]
    fmt = data.get("format") if isinstance(data, dict) else None
    if len(video) != 1 or not isinstance(fmt, dict):
        raise RenderExecutionError("rendered artifact must contain exactly one video stream")
    stream = video[0]
    try:
        duration = float(fmt.get("duration"))
    except (TypeError, ValueError):
        duration = 0
    if (stream.get("codec_name") != "h264" or stream.get("width") != 1080
            or stream.get("height") != 1920 or not (0 < duration <= 3600)):
        raise RenderExecutionError("rendered artifact does not match the required MP4 profile")
    return {"duration_seconds": duration, "codec": "h264",
            "width": 1080, "height": 1920, "format_name": str(fmt.get("format_name", ""))[:80]}


def execute_ffmpeg_render(argv: Sequence[str], output_root: str | os.PathLike,
                          final_name: str, *, ffprobe_path: str = "ffprobe",
                          timeout_seconds: int = 900,
                          max_output_bytes: int = 512 * 1024 * 1024) -> dict:
    """Execute a prebuilt argv, probe output, hash it and atomically adopt it.

    The argv must end in a path inside output_root. The final artifact name is
    generated/validated here; failed or partial output is always removed.
    """
    root = _regular_output_root(output_root)
    if (not isinstance(final_name, str) or not final_name.endswith(".mp4")
            or len(final_name) > 128
            or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for ch in final_name)):
        raise RenderExecutionError("final artifact name is invalid")
    destination = root / final_name
    if destination.exists() or destination.is_symlink():
        raise RenderExecutionError("final artifact already exists")
    fd, raw_temp = tempfile.mkstemp(prefix=".nexus-render-", suffix=".mp4", dir=root)
    os.close(fd)
    temporary = Path(raw_temp)
    temporary.unlink()
    command = list(argv) if isinstance(argv, (list, tuple)) else []
    if not command:
        raise RenderExecutionError("renderer command must be an argument array")
    try:
        requested_output = Path(command[-1])
        if not requested_output.is_absolute() or requested_output != temporary:
            raise RenderExecutionError("renderer output must target the worker-owned temporary path")
        _run_bounded(command, timeout_seconds=timeout_seconds,
                     max_output_bytes=max_output_bytes, output_path=temporary)
        probe = _probe(ffprobe_path, temporary, timeout_seconds)
        digest = hashlib.sha256()
        size = 0
        with temporary.open("rb") as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_output_bytes:
                    raise RenderExecutionError("render output exceeded its size limit during hashing")
                digest.update(chunk)
        if size == 0:
            raise RenderExecutionError("rendered artifact is empty")
        if destination.exists() or destination.is_symlink():
            raise RenderExecutionError("final artifact appeared before atomic adoption")
        os.replace(temporary, destination)
        return {"path": destination.name, "size_bytes": size,
                "sha256": digest.hexdigest(), "probe": probe,
                "status": "review_pending"}
    except RenderExecutionError:
        raise
    except OSError as exc:
        raise RenderExecutionError("render artifact could not be adopted") from exc
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
