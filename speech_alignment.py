"""Compare independently transcribed narration with the approved script text."""
import re
import unicodedata


def _tokens(value):
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.findall(r"[^\W_]+", normalized, flags=re.UNICODE)


def compare_transcript_to_script(script, transcript, max_word_error_rate=0.25):
    expected = _tokens(script)
    actual = _tokens(transcript)
    if len(expected) > 5000 or len(actual) > 5000:
        return {
            "status": "too_large_to_compare",
            "script_token_count": len(expected),
            "transcript_token_count": len(actual),
            "word_error_rate": None,
            "match_rate": None,
            "warning": "Transcript exceeds the 5,000-token safety limit for edit-distance comparison.",
        }
    if len(expected) < 5 or len(actual) < 5:
        return {
            "status": "insufficient_text",
            "script_token_count": len(expected),
            "transcript_token_count": len(actual),
            "word_error_rate": None,
            "match_rate": None,
            "warning": "At least five normalized tokens are required in both texts.",
        }

    # Levenshtein edit distance with O(min(n,m)) memory.
    previous = list(range(len(actual) + 1))
    for row, expected_token in enumerate(expected, start=1):
        current = [row]
        for column, actual_token in enumerate(actual, start=1):
            current.append(min(
                current[-1] + 1,
                previous[column] + 1,
                previous[column - 1] + (expected_token != actual_token),
            ))
        previous = current
    distance = previous[-1]
    wer = distance / len(expected)
    status = "aligned" if wer <= float(max_word_error_rate) else "material_mismatch"
    return {
        "status": status,
        "script_token_count": len(expected),
        "transcript_token_count": len(actual),
        "edit_distance": distance,
        "word_error_rate": round(wer, 4),
        "match_rate": round(max(0.0, 1.0 - wer), 4),
        "threshold_word_error_rate": float(max_word_error_rate),
        "method": "normalized_whitespace_token_levenshtein_v1",
        "warning": (
            "ASR can misrecognize names, numbers, accents, languages and technical terms. "
            "This alignment score is a review signal, not proof of factual correctness, "
            "pronunciation quality, or subtitle accuracy."
        ),
    }


def _subtitle_payload_to_text(value):
    text = str(value or "")
    # Remove SRT cue numbers only when followed by a timecode, preserving
    # standalone spoken numbers such as years or quantities.
    text = re.sub(
        r"^[ \t]*\d+[ \t]*\r?\n(?=[ \t]*\d{2}:\d{2}:\d{2}[,.]\d{3}[ \t]+-->)",
        "", text, flags=re.MULTILINE,
    )
    text = re.sub(
        r"^[ \t]*\d{2}:\d{2}:\d{2}[,.]\d{3}[ \t]+-->[ \t]+"
        r"\d{2}:\d{2}:\d{2}[,.]\d{3}.*$",
        "", text, flags=re.MULTILINE,
    )
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\{\\an\d+\}", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def analyze_srt_timing(subtitle_text, max_cues=10000):
    text = str(subtitle_text or "")
    pattern = re.compile(
        r"(?m)^[ \t]*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})[ \t]+-->[ \t]+"
        r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
    )
    matches = list(pattern.finditer(text))
    if not matches:
        return {
            "status": "not_available", "cue_count": 0, "warnings": [],
            "reason": "No SRT timecodes were found in the extracted subtitle text.",
        }
    if len(matches) > max_cues:
        return {
            "status": "too_many_cues", "cue_count": len(matches), "warnings": [],
            "reason": f"Subtitle file exceeds the {max_cues}-cue timing analysis limit.",
        }

    def seconds(hour, minute, second, millis):
        return (int(hour) * 3600 + int(minute) * 60
                + int(second) + int(millis) / 1000.0)

    cues = []
    invalid_count = 0
    for index, match in enumerate(matches):
        start = seconds(*match.groups()[:4])
        end = seconds(*match.groups()[4:])
        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        cue_text = text[match.end():next_start]
        cue_text = re.sub(r"(?m)^[ \t]*\d+[ \t]*$", "", cue_text)
        cue_text = re.sub(r"<[^>]+>", "", cue_text)
        cue_text = re.sub(r"\{\\an\d+\}", "", cue_text)
        char_count = len(re.sub(r"\s+", "", cue_text))
        if end <= start:
            invalid_count += 1
            continue
        duration = end - start
        cues.append({
            "start_seconds": start, "end_seconds": end,
            "duration_seconds": duration,
            "characters_per_second": round(char_count / duration, 2),
        })

    overlap_count = 0
    long_gap_count = 0
    short_cue_count = 0
    long_cue_count = 0
    fast_reading_count = 0
    out_of_order_count = 0
    for index, cue in enumerate(cues):
        if cue["duration_seconds"] < 0.5:
            short_cue_count += 1
        if cue["duration_seconds"] > 7.0:
            long_cue_count += 1
        if cue["characters_per_second"] > 20.0:
            fast_reading_count += 1
        if index:
            previous = cues[index - 1]
            if cue["start_seconds"] < previous["start_seconds"]:
                out_of_order_count += 1
            if cue["start_seconds"] < previous["end_seconds"] - 0.05:
                overlap_count += 1
            if cue["start_seconds"] - previous["end_seconds"] > 5.0:
                long_gap_count += 1

    warnings = []
    if invalid_count:
        warnings.append("subtitle_timing_contains_invalid_or_nonpositive_cues")
    if overlap_count:
        warnings.append("subtitle_cues_overlap")
    if long_gap_count:
        warnings.append("subtitle_timing_has_gaps_over_5_seconds")
    if short_cue_count:
        warnings.append("subtitle_cues_shorter_than_0_5_seconds")
    if long_cue_count:
        warnings.append("subtitle_cues_longer_than_7_seconds")
    if fast_reading_count:
        warnings.append("subtitle_reading_speed_over_20_characters_per_second")
    if out_of_order_count:
        warnings.append("subtitle_cues_are_out_of_order")
    return {
        "status": "analyzed",
        "cue_count": len(matches),
        "valid_cue_count": len(cues),
        "invalid_cue_count": invalid_count,
        "overlap_count": overlap_count,
        "long_gap_count": long_gap_count,
        "short_cue_count": short_cue_count,
        "long_cue_count": long_cue_count,
        "fast_reading_count": fast_reading_count,
        "out_of_order_count": out_of_order_count,
        "thresholds": {
            "minimum_duration_seconds": 0.5,
            "maximum_duration_seconds": 7.0,
            "maximum_characters_per_second": 20.0,
            "long_gap_seconds": 5.0,
        },
        "warnings": warnings,
        "boundary": (
            "Timing and character-rate heuristics only. They do not measure actual reading "
            "difficulty, font size, contrast, safe-area placement, language-specific reading "
            "speed, or whether the captions match the video visually."
        ),
    }


def build_caption_alignment_report(script, subtitle_text, asr_transcript=None,
                                   max_word_error_rate=0.25):
    caption_text = _subtitle_payload_to_text(subtitle_text)
    asr_available = isinstance(asr_transcript, str) and bool(asr_transcript.strip())
    reference = asr_transcript if asr_available else script
    reference_kind = "independent_asr_transcript" if asr_available else "generated_script"
    result = compare_transcript_to_script(
        reference, caption_text, max_word_error_rate=max_word_error_rate
    )
    timing = analyze_srt_timing(subtitle_text)
    return {
        "version": "caption_alignment_v1",
        "reference": reference_kind,
        "subtitle_text_available": bool(caption_text),
        "subtitle_token_count": len(_tokens(caption_text)),
        "timing_analysis": timing,
        **result,
        "warning": (
            "Only an extractable text subtitle stream was compared. Burned-in captions, "
            "caption timing, on-screen placement, font size, contrast and legibility are "
            "not verified. ASR/script references can themselves contain errors."
        ),
    }


def build_speech_alignment_report(script, transcript, provider=None,
                                  max_word_error_rate=0.25):
    result = compare_transcript_to_script(
        script, transcript, max_word_error_rate=max_word_error_rate
    )
    return {
        "version": "speech_alignment_v1",
        "provider": provider,
        "transcript_available": bool(str(transcript or "").strip()),
        **result,
    }
