"""Safe FFmpeg audio-bed mixing argv builder for server-owned staged inputs.

Paths must already have been resolved by the trusted asset layer. This module
constructs argv only; it never invokes a shell or accepts raw filter expressions.
"""
from __future__ import annotations

import math
from pathlib import Path


class AudioMixError(ValueError):
    pass


def _private_regular_file(value, field):
    path = Path(value)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise AudioMixError(f"{field} must be an absolute regular non-symlink file")
    return str(path.resolve(strict=True))


def build_audio_mix_argv(tracks, output_path, *, ffmpeg_path="ffmpeg",
                         output_duration_ms=None, sample_rate=48000):
    """Build a bounded, shell-free audio mix command for 1-8 trusted tracks.

    Track fields: path, start_ms, duration_ms, gain (linear 0..4), fade_in_ms,
    fade_out_ms. The caller must obtain each path from a clean workspace asset.
    """
    if not isinstance(tracks, list) or not 1 <= len(tracks) <= 8:
        raise AudioMixError("tracks must contain 1 to 8 entries")
    if not isinstance(ffmpeg_path, str) or not ffmpeg_path or "\x00" in ffmpeg_path:
        raise AudioMixError("FFmpeg executable is invalid")
    if isinstance(sample_rate, bool) or sample_rate not in (44100, 48000):
        raise AudioMixError("sample_rate must be 44100 or 48000")
    if output_duration_ms is not None and (
        isinstance(output_duration_ms, bool) or not isinstance(output_duration_ms, int)
        or not 1 <= output_duration_ms <= 3_600_000
    ):
        raise AudioMixError("output_duration_ms must be between 1 and 3600000")

    output = Path(output_path)
    if not output.is_absolute() or output.is_symlink() or output.suffix.lower() not in (".m4a", ".aac"):
        raise AudioMixError("output must be an absolute .m4a or .aac path")
    if not output.parent.is_dir():
        raise AudioMixError("output directory must already exist")

    argv = [ffmpeg_path, "-nostdin", "-hide_banner", "-y"]
    filters = []
    labels = []
    max_end = 0
    for index, track in enumerate(tracks):
        if not isinstance(track, dict) or set(track) - {
            "path", "start_ms", "source_in_ms", "duration_ms", "gain", "fade_in_ms", "fade_out_ms"
        }:
            raise AudioMixError("audio track contains unsupported fields")
        path = _private_regular_file(track.get("path"), "track path")
        start = track.get("start_ms", 0)
        source_in = track.get("source_in_ms", 0)
        duration = track.get("duration_ms")
        gain = track.get("gain", 1.0)
        fade_in = track.get("fade_in_ms", 0)
        fade_out = track.get("fade_out_ms", 0)
        for value, name, maximum in (
            (start, "start_ms", 3_600_000), (source_in, "source_in_ms", 3_600_000),
            (duration, "duration_ms", 3_600_000),
            (fade_in, "fade_in_ms", 60_000), (fade_out, "fade_out_ms", 60_000),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
                raise AudioMixError(f"{name} is outside its allowed range")
        if duration < 1 or fade_in + fade_out > duration:
            raise AudioMixError("audio duration and fades are inconsistent")
        if isinstance(gain, bool) or not isinstance(gain, (int, float)) or not math.isfinite(gain) or not 0 <= gain <= 4:
            raise AudioMixError("gain must be finite and between 0 and 4")
        argv.extend(["-protocol_whitelist", "file,pipe", "-i", path])
        label = f"a{index}"
        chain = (
            f"[{index}:a]atrim=start={source_in / 1000:.3f}:duration={duration / 1000:.3f},"
            f"asetpts=PTS-STARTPTS,volume={float(gain):.4f}"
        )
        if fade_in:
            chain += f",afade=t=in:st=0:d={fade_in / 1000:.3f}"
        if fade_out:
            chain += f",afade=t=out:st={(duration - fade_out) / 1000:.3f}:d={fade_out / 1000:.3f}"
        chain += f",adelay={start}|{start}"
        filters.append(chain + f"[{label}]")
        labels.append(f"[{label}]")
        max_end = max(max_end, start + duration)

    total_ms = output_duration_ms if output_duration_ms is not None else max_end
    if total_ms < 1:
        raise AudioMixError("mixed output duration is empty")
    filters.append(
        "".join(labels)
        + f"amix=inputs={len(labels)}:duration=longest:dropout_transition=0:normalize=0,"
        + "alimiter=limit=0.95[mixed]"
    )
    argv.extend([
        "-filter_complex", ";".join(filters), "-map", "[mixed]",
        "-t", f"{total_ms / 1000:.3f}", "-ar", str(sample_rate),
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        str(output),
    ])
    return argv
