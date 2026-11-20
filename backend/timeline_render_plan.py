"""Build a restricted FFmpeg argv for the first video-only EDL render subset.

This module does not execute FFmpeg, resolve browser paths, or authorize assets.
Callers must supply server-resolved asset paths after workspace ownership checks,
and execute the returned argv inside an isolated, resource-limited worker.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Mapping

from timeline_edl import EDLValidationError, validate_edl


class RenderPlanError(ValueError):
    """Raised when a validated EDL cannot be safely planned for this renderer."""


def _reject_symlink_components(path: Path) -> None:
    absolute = Path(os.path.abspath(path))
    for candidate in (absolute, *absolute.parents):
        if candidate.is_symlink():
            raise RenderPlanError("render paths must not contain symlink components")


def _trusted_regular_file(value: object) -> Path:
    if not isinstance(value, (str, os.PathLike)):
        raise RenderPlanError("asset path must be supplied by the trusted asset registry")
    candidate = Path(value)
    if not candidate.is_absolute():
        raise RenderPlanError("asset paths must be absolute server-side paths")
    _reject_symlink_components(candidate)
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise RenderPlanError("registered source asset is unavailable") from exc
    if not resolved.is_file():
        raise RenderPlanError("registered source asset must be a regular file")
    return resolved


def build_ffmpeg_argv(
    edl: object,
    asset_paths: Mapping[str, str | os.PathLike],
    output_path: str | os.PathLike,
    output_root: str | os.PathLike,
    *,
    ffmpeg_path: str = "ffmpeg",
) -> list[str]:
    """Return argv for a bounded, silent, portrait MP4 render (no shell involved).

    Supported in this increment: one or more video clips, concatenated in EDL
    order, with source trims and normalized 1080x1920/30fps video. Title clips,
    audio mixing, and effects fail closed until their dedicated safe subsets
    are implemented. The caller remains responsible for OS/container limits,
    timeout, process-tree cancellation, output validation, and atomic adoption.
    """
    try:
        normalized = validate_edl(edl)
    except EDLValidationError:
        raise
    clips = normalized["clips"]
    if any(clip["type"] != "video" for clip in clips):
        raise RenderPlanError("title clips are not supported by the initial renderer")
    if not isinstance(asset_paths, Mapping):
        raise RenderPlanError("asset paths must be a server-resolved mapping")
    required_ids = {clip["asset_id"] for clip in clips}
    if set(asset_paths) != required_ids:
        raise RenderPlanError("asset registry resolution is incomplete or contains unrelated assets")
    if not isinstance(ffmpeg_path, str) or not ffmpeg_path or "\x00" in ffmpeg_path:
        raise RenderPlanError("invalid configured FFmpeg executable")

    sources = {asset_id: _trusted_regular_file(asset_paths[asset_id]) for asset_id in required_ids}

    root = Path(output_root)
    if not root.is_absolute():
        raise RenderPlanError("output root must be an absolute worker-owned directory")
    _reject_symlink_components(root)
    try:
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        raise RenderPlanError("worker output root is unavailable") from exc
    if not resolved_root.is_dir():
        raise RenderPlanError("worker output root must be a directory")

    target = Path(output_path)
    if not target.is_absolute():
        raise RenderPlanError("output path must be absolute")
    _reject_symlink_components(target)
    try:
        parent = target.parent.resolve(strict=True)
    except OSError as exc:
        raise RenderPlanError("output directory is unavailable") from exc
    try:
        parent.relative_to(resolved_root)
    except ValueError as exc:
        raise RenderPlanError("output path must remain inside the worker output root") from exc
    if target.suffix.lower() != ".mp4" or target.exists():
        raise RenderPlanError("output must be a new .mp4 file")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", target.name):
        raise RenderPlanError("output filename contains unsupported characters")

    argv = [ffmpeg_path, "-hide_banner", "-nostdin", "-v", "error"]
    filter_parts = []
    for index, clip in enumerate(clips):
        source = sources[clip["asset_id"]]
        argv.extend(["-protocol_whitelist", "file,pipe", "-i", str(source)])
        start = clip["source_in_ms"] / 1000
        end = clip["source_out_ms"] / 1000
        filter_parts.append(
            f"[{index}:v:0]trim=start={start:.3f}:end={end:.3f},"
            "setpts=PTS-STARTPTS,"
            "scale=1080:1920:force_original_aspect_ratio=decrease,"
            "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,"
            "setsar=1,fps=30,format=yuv420p"
            f"[v{index}]"
        )
    concat_inputs = "".join(f"[v{index}]" for index in range(len(clips)))
    filter_parts.append(f"{concat_inputs}concat=n={len(clips)}:v=1:a=0[outv]")
    argv.extend([
        "-filter_complex", ";".join(filter_parts),
        "-map", "[outv]", "-an",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-movflags", "+faststart", "-f", "mp4", str(target),
    ])
    return argv
