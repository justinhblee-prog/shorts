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
    allowed_root = {"schema", "version", "timebase", "clips", "audio_tracks", "project_duration_ms", "transitions", "gaps"}
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
            if any((ord(ch) < 32 and ch not in "\n\t") or ord(ch) == 127 for ch in title):
                raise EDLValidationError(f"{prefix}.text contains unsupported control characters")
            item["text"] = title.strip()
        normalized.append(item)

    if max(item["end_ms"] for item in normalized) > MAX_DURATION_MS:
        raise EDLValidationError("timeline exceeds maximum duration")

    video_clips = [item for item in normalized if item["type"] == "video"]
    transition_pairs = set()
    transitions = []
    if "transitions" in payload:
        raw_transitions = payload["transitions"]
        if not isinstance(raw_transitions, list) or len(raw_transitions) > max(0, len(video_clips) - 1):
            raise EDLValidationError("transitions must describe at most one transition per adjacent video pair")
        for index, raw in enumerate(raw_transitions):
            prefix = f"transitions[{index}]"
            expected_fields = {"from_clip_id", "to_clip_id", "type", "duration_ms"}
            if not isinstance(raw, dict) or set(raw) != expected_fields:
                raise EDLValidationError(f"{prefix} has unsupported or missing fields")
            from_id, to_id = raw["from_clip_id"], raw["to_clip_id"]
            if not isinstance(from_id, str) or not isinstance(to_id, str):
                raise EDLValidationError(f"{prefix} clip references must be strings")
            pair = (from_id, to_id)
            if pair in transition_pairs:
                raise EDLValidationError(f"{prefix} duplicates an adjacent clip transition")
            transition_pairs.add(pair)
            adjacent = any(
                video_clips[position]["id"] == from_id
                and video_clips[position + 1]["id"] == to_id
                for position in range(len(video_clips) - 1)
            )
            if not adjacent:
                raise EDLValidationError(f"{prefix} must reference adjacent video clips in timeline order")
            if raw["type"] != "crossfade":
                raise EDLValidationError(f"{prefix}.type must be crossfade")
            transition_duration = _number(raw["duration_ms"], f"{prefix}.duration_ms")
            from_clip = next(item for item in video_clips if item["id"] == from_id)
            to_clip = next(item for item in video_clips if item["id"] == to_id)
            from_length = from_clip["source_out_ms"] - from_clip["source_in_ms"]
            to_length = to_clip["source_out_ms"] - to_clip["source_in_ms"]
            if (not transition_duration.is_integer() or transition_duration < 100
                    or transition_duration > 5000
                    or transition_duration >= min(from_length, to_length)):
                raise EDLValidationError(f"{prefix}.duration_ms is outside safe clip overlap bounds")
            transitions.append({
                "from_clip_id": from_id, "to_clip_id": to_id,
                "type": "crossfade", "duration_ms": int(transition_duration),
            })

    gaps = []
    if "gaps" in payload:
        raw_gaps = payload["gaps"]
        if not isinstance(raw_gaps, list) or len(raw_gaps) > max(0, len(video_clips) - 1):
            raise EDLValidationError("gaps must describe at most one black gap per adjacent video pair")
        gap_pairs = set()
        for index, raw in enumerate(raw_gaps):
            prefix = f"gaps[{index}]"
            expected_fields = {"after_clip_id", "before_clip_id", "duration_ms"}
            if not isinstance(raw, dict) or set(raw) != expected_fields:
                raise EDLValidationError(f"{prefix} has unsupported or missing fields")
            after_id, before_id = raw["after_clip_id"], raw["before_clip_id"]
            if not isinstance(after_id, str) or not isinstance(before_id, str):
                raise EDLValidationError(f"{prefix} clip references must be strings")
            pair = (after_id, before_id)
            if pair in gap_pairs:
                raise EDLValidationError(f"{prefix} duplicates an adjacent black gap")
            gap_pairs.add(pair)
            adjacent = any(
                video_clips[position]["id"] == after_id
                and video_clips[position + 1]["id"] == before_id
                for position in range(len(video_clips) - 1)
            )
            if not adjacent:
                raise EDLValidationError(f"{prefix} must reference adjacent video clips in timeline order")
            gap_duration = _number(raw["duration_ms"], f"{prefix}.duration_ms")
            if not gap_duration.is_integer() or gap_duration < 100 or gap_duration > 10000:
                raise EDLValidationError(f"{prefix}.duration_ms must be a whole duration from 100 to 10000 ms")
            gaps.append({
                "after_clip_id": after_id, "before_clip_id": before_id,
                "duration_ms": int(gap_duration),
            })
        if gap_pairs.intersection(transition_pairs):
            raise EDLValidationError("an adjacent video pair cannot have both a crossfade and a black gap")

    project_duration = None
    if "project_duration_ms" in payload:
        project_duration = _number(payload["project_duration_ms"], "project_duration_ms")
        video_end = max(
            (item["end_ms"] for item in normalized if item["type"] == "video"),
            default=0,
        )
        if (not float(project_duration).is_integer() or project_duration < video_end
                or project_duration < 1 or project_duration > MAX_DURATION_MS):
            raise EDLValidationError("project_duration_ms must be a whole-millisecond duration covering the video timeline")

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
        if any(not float(value).is_integer() for value in (start, source_in, source_out, fade_in, fade_out)):
            raise EDLValidationError(f"{prefix} timing and fade values must be whole milliseconds")
        if (start < 0 or source_in < 0 or duration <= 0 or start + duration > MAX_DURATION_MS
                or not 0 <= gain <= 4 or not 0 <= fade_in <= 60000
                or not 0 <= fade_out <= 60000 or fade_in + fade_out > duration):
            raise EDLValidationError(f"{prefix} has invalid trim, gain or fade bounds")
        if project_duration is not None and start + duration > project_duration:
            raise EDLValidationError(f"{prefix} extends beyond project_duration_ms")
        audio_tracks.append({
            "id": track_id, "asset_id": asset_id, "start_ms": start,
            "source_in_ms": source_in, "source_out_ms": source_out,
            "gain": gain, "fade_in_ms": fade_in, "fade_out_ms": fade_out,
        })
    result = {
        "schema": SCHEMA, "version": VERSION, "timebase": "milliseconds",
        "clips": normalized, "audio_tracks": audio_tracks,
    }
    if project_duration is not None:
        result["project_duration_ms"] = int(project_duration)
    if "transitions" in payload:
        result["transitions"] = transitions
    if "gaps" in payload:
        result["gaps"] = gaps
    return result
