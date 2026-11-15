"""Deterministic metadata-level production QA; never claims to inspect media bytes."""


def _positive_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def evaluate_production_quality(script_text, script_metadata, voice_metadata,
                               render_metadata, brief, media_inspection=None):
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
    if script_metadata.get("factual_claims_verified") is not True:
        warnings.append("script_provider_did_not_attest_fact_check")
    originality = script_metadata.get("originality_check")
    if isinstance(originality, dict) and originality.get("status") == "similar_content_found":
        warnings.append("script_similarity_to_prior_production_above_threshold")
    checks.append({
        "name": "source_and_fact_check_metadata",
        "status": "warning" if (
            "trend_source_citations_not_returned_by_script_provider" in warnings
            or "script_provider_did_not_attest_fact_check" in warnings
        ) else "provider_attested",
        "provider_attestation_only": True,
        "originality_status": originality.get("status") if isinstance(originality, dict) else None,
        "similarity_threshold": originality.get("threshold") if isinstance(originality, dict) else None,
        "similar_matches": originality.get("similar_matches", []) if isinstance(originality, dict) else [],
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
    known_nonvertical = render_format in ("horizontal", "horizontal_16_9", "square", "16:9", "1:1")
    if aspect and aspect != "9:16":
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

    media_inspection = media_inspection if isinstance(media_inspection, dict) else None
    if media_inspection is None:
        warnings.append("actual_media_bytes_not_inspected")
        checks.append({
            "name": "media_bytes",
            "status": "not_inspected",
            "reason": "Renderer URL has not been staged and inspected with ffprobe.",
        })
    else:
        media_blockers = []
        actual_duration = _positive_number(media_inspection.get("duration_seconds"))
        actual_width = _positive_number(media_inspection.get("width"))
        actual_height = _positive_number(media_inspection.get("height"))
        actual_audio = media_inspection.get("audio_track_present")
        actual_ratio = (
            actual_width / actual_height if actual_width and actual_height else None
        )
        if media_inspection.get("status") != "inspected":
            media_blockers.append("actual_media_inspection_did_not_complete")
        if actual_ratio is not None and abs(actual_ratio - (9.0 / 16.0)) > 0.04:
            media_blockers.append("actual_media_dimensions_are_not_vertical_9_16")
        if actual_audio is False:
            media_blockers.append("actual_media_contains_no_audio_track")
        if actual_duration is not None and actual_duration > 180:
            media_blockers.append("actual_media_duration_exceeds_180_seconds")
        if actual_duration is None or actual_width is None or actual_height is None:
            media_blockers.append("actual_media_probe_missing_required_stream_metadata")
        blockers.extend(media_blockers)
        signal_report = media_inspection.get("signal_analysis") or {}
        signal_warnings = signal_report.get("signal_warnings") or []
        if isinstance(signal_warnings, list):
            warnings.extend(str(item) for item in signal_warnings)
        checks.append({
            "name": "media_bytes",
            "status": "blocked" if media_blockers else "inspected",
            "inspection_method": media_inspection.get("inspection_method"),
            "duration_seconds": actual_duration,
            "width": actual_width,
            "height": actual_height,
            "aspect_ratio": actual_ratio,
            "audio_track_present": actual_audio,
            "video_codec": media_inspection.get("video_codec"),
            "audio_codec": media_inspection.get("audio_codec"),
            "subtitle_stream_present": media_inspection.get("subtitle_stream_present"),
            "subtitle_note": media_inspection.get("subtitle_note"),
            "signal_analysis_status": signal_report.get("status"),
            "black_frame_segments": signal_report.get("black_segments", []),
            "audio_silence_segments": signal_report.get("silence_segments", []),
            "signal_warnings": signal_warnings,
            "signal_analysis_boundary": signal_report.get("signal_analysis_boundary"),
            "blockers": media_blockers,
        })
        warnings = [
            item for item in warnings
            if item != "actual_media_bytes_not_inspected"
        ]
    status = "blocked" if blockers else "review_required" if warnings else "ready_for_human_review"
    return {
        "version": "production_quality_media_v2",
        "status": status,
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "checks": checks,
        "script_word_count": words,
        "verification_boundary": (
            "When configured, staged video bytes are inspected with ffprobe for container, "
            "duration, dimensions, codecs and audio/subtitle streams. This does not verify "
            "burned-in caption text or legibility, visual quality, factual accuracy, rights, "
            "music licensing, platform compliance or monetization eligibility. Provider "
            "attestations are not independent verification. Human review remains mandatory."
        ),
        "score_adjustment": 0,
        "automatic_publication": False,
    }
