"""Strict, side-effect-free validation for versioned NEXUS timeline EDL payloads.

This module deliberately does not resolve asset IDs, access storage, or enqueue work.
Those operations require an authenticated workspace identity and are not safe with
this repository's current shared review-token authentication model.
"""
from __future__ import annotations

import math
import re
from typing import Any


SCHEMA = "nexus-edit-decision-list"
VERSION = 1
MAX_CLIPS = 20
MAX_DURATION_MS = 60 * 60 * 1000
MAX_TITLE_LENGTH = 240
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class EDLValidationError(ValueError):
    """Raised when an EDL is malformed or exceeds the supported safe subset."""


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EDLValidationError(f"{field} must be a finite number")
    try:
        result = float(value)
    except (OverflowError, ValueError):
        raise EDLValidationError(f"{field} must be a finite number")
    if not math.isfinite(result):
        raise EDLValidationError(f"{field} must be a finite number")
    return result


def validate_edl(payload: Any) -> dict:
    """Validate and return a normalized copy of the supported EDL v1 subset.

    Supported payload shape: schema, version, timebase='milliseconds', clips[].
    Each clip has id, type ('video'|'title'), start_ms, end_ms, and for video
    clips an opaque asset_id plus source_in_ms/source_out_ms. Browser paths,
    URLs, filters, transitions and arbitrary renderer directives are rejected.
    """
    if not isinstance(payload, dict):
        raise EDLValidationError("EDL must be a JSON object")
    version = payload.get("version")
    if payload.get("schema") != SCHEMA or isinstance(version, bool) or not isinstance(version, int) or version != VERSION:
        raise EDLValidationError("unsupported EDL schema or version")
    if payload.get("timebase") != "milliseconds":
        raise EDLValidationError("timebase must be milliseconds")
    allowed_root = {"schema", "version", "timebase", "clips", "audio_tracks"}
    if set(payload) - allowed_root:
        raise EDLValidationError("EDL contains unsupported root fields")
    clips = payload.get("clips")
    if not isinstance(clips, list) or not clips or len(clips) > MAX_CLIPS:
        raise EDLValidationError(f"clips must contain 1 to {MAX_CLIPS} entries")

    normalized = []
    seen = set()
    for index, raw in enumerate(clips):
        prefix = f"clips[{index}]"
        if not isinstance(raw, dict):
            raise EDLValidationError(f"{prefix} must be an object")
        kind = raw.get("type")
        common = {"id", "type", "start_ms", "end_ms"}
        expected = common | ({"asset_id", "source_in_ms", "source_out_ms"}
                             if kind == "video" else {"text"} if kind == "title" else set())
        if kind not in ("video", "title") or set(raw) != expected:
            raise EDLValidationError(f"{prefix} has unsupported type or fields")
        clip_id = raw.get("id")
        if not isinstance(clip_id, str) or not _ID.fullmatch(clip_id) or clip_id in seen:
            raise EDLValidationError(f"{prefix}.id must be unique and valid")
        seen.add(clip_id)
        start = _number(raw["start_ms"], f"{prefix}.start_ms")
        end = _number(raw["end_ms"], f"{prefix}.end_ms")
        if start < 0 or end <= start or end > MAX_DURATION_MS:
            raise EDLValidationError(f"{prefix} has invalid timeline bounds")
        item = {"id": clip_id, "type": kind, "start_ms": start, "end_ms": end}
        if kind == "video":
            asset_id = raw["asset_id"]
            if not isinstance(asset_id, str) or not _ID.fullmatch(asset_id):
                raise EDLValidationError(f"{prefix}.asset_id must be an opaque identifier")
            source_in = _number(raw["source_in_ms"], f"{prefix}.source_in_ms")
            source_out = _number(raw["source_out_ms"], f"{prefix}.source_out_ms")
            if source_in < 0 or source_out <= source_in:
                raise EDLValidationError(f"{prefix} has invalid source trim bounds")
            if not math.isclose(end - start, source_out - source_in, abs_tol=1.0):
                raise EDLValidationError(f"{prefix} timeline and source durations differ")
            item.update(asset_id=asset_id, source_in_ms=source_in, source_out_ms=source_out)
        else:
            title = raw["text"]
            if not isinstance(title, str) or not title.strip() or len(title) > MAX_TITLE_LENGTH:
                raise EDLValidationError(f"{prefix}.text must contain 1 to {MAX_TITLE_LENGTH} characters")
            item["text"] = title.strip()
        normalized.append(item)

    if max(item["end_ms"] for item in normalized) > MAX_DURATION_MS:
        raise EDLValidationError("timeline exceeds maximum duration")

    raw_audio = payload.get("audio_tracks", [])
    if not isinstance(raw_audio, list) or len(raw_audio) > 8:
        raise EDLValidationError("audio_tracks must contain 0 to 8 entries")
    audio_tracks = []
    audio_ids = set()
    for index, raw in enumerate(raw_audio):
        prefix = f"audio_tracks[{index}]"
        allowed = {"id", "asset_id", "start_ms", "source_in_ms", "source_out_ms",
                   "gain", "fade_in_ms", "fade_out_ms"}
        required = {"id", "asset_id", "start_ms", "source_in_ms", "source_out_ms"}
        if not isinstance(raw, dict) or set(raw) - allowed or not required.issubset(raw):
            raise EDLValidationError(f"{prefix} has unsupported or missing fields")
        track_id = raw["id"]
        asset_id = raw["asset_id"]
        if not isinstance(track_id, str) or not _ID.fullmatch(track_id) or track_id in audio_ids:
            raise EDLValidationError(f"{prefix}.id must be unique and valid")
        if not isinstance(asset_id, str) or not _ID.fullmatch(asset_id):
            raise EDLValidationError(f"{prefix}.asset_id must be an opaque identifier")
        audio_ids.add(track_id)
        start = _number(raw["start_ms"], f"{prefix}.start_ms")
        source_in = _number(raw["source_in_ms"], f"{prefix}.source_in_ms")
        source_out = _number(raw["source_out_ms"], f"{prefix}.source_out_ms")
        gain = _number(raw.get("gain", 1.0), f"{prefix}.gain")
        fade_in = _number(raw.get("fade_in_ms", 0), f"{prefix}.fade_in_ms")
        fade_out = _number(raw.get("fade_out_ms", 0), f"{prefix}.fade_out_ms")
        duration = source_out - source_in
        if (start < 0 or source_in < 0 or duration <= 0 or start + duration > MAX_DURATION_MS
                or not 0 <= gain <= 4 or not 0 <= fade_in <= 60000
                or not 0 <= fade_out <= 60000 or fade_in + fade_out > duration):
            raise EDLValidationError(f"{prefix} has invalid trim, gain or fade bounds")
        audio_tracks.append({
            "id": track_id, "asset_id": asset_id, "start_ms": start,
            "source_in_ms": source_in, "source_out_ms": source_out,
            "gain": gain, "fade_in_ms": fade_in, "fade_out_ms": fade_out,
        })
    return {
        "schema": SCHEMA, "version": VERSION, "timebase": "milliseconds",
        "clips": normalized, "audio_tracks": audio_tracks,
    }
