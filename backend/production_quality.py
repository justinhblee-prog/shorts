"""Deterministic metadata-level production QA; never claims to inspect media bytes."""

import math
from urllib.parse import urlsplit


def _positive_number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _is_http_source(value):
    if not isinstance(value, str) or not value.strip() or any(ch.isspace() for ch in value.strip()):
        return False
    try:
        parsed = urlsplit(value.strip())
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except ValueError:
        return False


def _is_vertical_aspect(value):
    try:
        text = str(value).strip()
        if ":" in text:
            numerator, denominator = text.split(":", 1)
            ratio = float(numerator) / float(denominator)
        else:
            ratio = float(text)
    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
        return False
    return math.isfinite(ratio) and abs(ratio - (9.0 / 16.0)) <= 0.01


def evaluate_production_quality(script_text, script_metadata, voice_metadata,
                               render_metadata, brief):
    script_metadata = script_metadata if isinstance(script_metadata, dict) else {}
    voice_metadata = voice_metadata if isinstance(voice_metadata, dict) else {}
    render_metadata = render_metadata if isinstance(render_metadata, dict) else {}
    brief = brief if isinstance(brief, dict) else {}
    blockers = []
    warnings = []
    checks = []

    words = len(str(script_text or "").split())
    if words < 20:
        warnings.append("script_word_count_below_20")
    elif words > 220:
        warnings.append("script_word_count_above_220")
    checks.append({
        "name": "script_length",
        "status": "warning" if words < 20 or words > 220 else "passed",
        "word_count": words,
        "basis": "Whitespace-delimited word count; editorial suitability still requires human review.",
    })

    if brief.get("trend_context"):
        sources = script_metadata.get("source_urls")
        if not isinstance(sources, list) or not sources:
            warnings.append("trend_source_citations_not_returned_by_script_provider")
        elif not any(_is_http_source(source) for source in sources):
            warnings.append("trend_source_citations_invalid_or_empty")
    if script_metadata.get("factual_claims_verified") is not True:
        warnings.append("script_provider_did_not_attest_fact_check")
    checks.append({
        "name": "source_and_fact_check_metadata",
        "status": "warning" if (
            "trend_source_citations_not_returned_by_script_provider" in warnings
            or "script_provider_did_not_attest_fact_check" in warnings
        ) else "provider_attested",
        "provider_attestation_only": True,
    })

    voice_duration = _positive_number(voice_metadata.get("duration_seconds"))
    if voice_duration is None:
        warnings.append("voice_duration_metadata_missing_or_invalid")
    checks.append({
        "name": "voice_metadata",
        "status": "warning" if voice_duration is None else "provider_metadata_present",
        "duration_seconds": voice_duration,
    })

    render_duration = _positive_number(render_metadata.get("duration_seconds"))
    if render_duration is None:
        warnings.append("render_duration_metadata_missing_or_invalid")
    elif render_duration > 180:
        blockers.append("render_duration_exceeds_180_seconds")
    elif render_duration < 5:
        warnings.append("render_duration_below_5_seconds")

    aspect = str(render_metadata.get("aspect_ratio") or "").strip()
    render_format = str(render_metadata.get("format") or "").strip().lower()
    width = _positive_number(render_metadata.get("width"))
    height = _positive_number(render_metadata.get("height"))
    known_nonvertical = render_format in (
        "horizontal", "horizontal_16_9", "landscape", "landscape_16_9",
        "square", "16:9", "1:1",
    )
    if aspect and not _is_vertical_aspect(aspect):
        known_nonvertical = True
    if width and height:
        measured_ratio = width / height
        if abs(measured_ratio - (9.0 / 16.0)) > 0.04:
            known_nonvertical = True
    if known_nonvertical:
        blockers.append("render_format_is_not_vertical_9_16")
    elif not aspect and not (width and height) and render_format not in (
        "vertical", "vertical_short", "9:16"
    ):
        warnings.append("render_aspect_ratio_not_reported")

    if render_metadata.get("audio_track_present") is False:
        blockers.append("rendered_video_reports_no_audio_track")
    elif render_metadata.get("audio_track_present") is not True:
        warnings.append("render_audio_track_presence_not_reported")

    if render_metadata.get("subtitles_enabled") is False:
        warnings.append("rendered_subtitles_reported_disabled")
    elif render_metadata.get("subtitles_enabled") is not True:
        warnings.append("render_subtitle_presence_not_reported")

    if voice_duration and render_duration:
        difference = abs(voice_duration - render_duration)
        if difference > max(5.0, render_duration * 0.20):
            warnings.append("voice_and_video_durations_differ_materially")

    checks.append({
        "name": "render_metadata",
        "status": "blocked" if any(reason in blockers for reason in (
            "render_duration_exceeds_180_seconds",
            "render_format_is_not_vertical_9_16",
            "rendered_video_reports_no_audio_track",
        )) else "warning" if any(reason in warnings for reason in (
            "render_duration_metadata_missing_or_invalid",
            "render_aspect_ratio_not_reported",
            "render_audio_track_presence_not_reported",
            "render_subtitle_presence_not_reported",
            "rendered_subtitles_reported_disabled",
            "voice_and_video_durations_differ_materially",
            "render_duration_below_5_seconds",
        )) else "provider_metadata_present",
        "duration_seconds": render_duration,
        "aspect_ratio": aspect or None,
        "width": width,
        "height": height,
        "audio_track_present": render_metadata.get("audio_track_present"),
        "subtitles_enabled": render_metadata.get("subtitles_enabled"),
    })

    status = "blocked" if blockers else "review_required" if warnings else "ready_for_human_review"
    return {
        "version": "production_quality_metadata_v1",
        "status": status,
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "checks": checks,
        "script_word_count": words,
        "verification_boundary": (
            "This gate evaluates provider-returned metadata and basic script length only. "
            "It does not download or inspect audio/video bytes, verify captions, prove factual "
            "accuracy, confirm rights, assess visual quality, or establish platform compliance. "
            "Human review remains mandatory."
        ),
        "score_adjustment": 0,
        "automatic_publication": False,
    }
