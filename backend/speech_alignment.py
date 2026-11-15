"""Compare independently transcribed narration with the approved script text."""
import re
import unicodedata


def _tokens(value):
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.findall(r"[^\W_]+", normalized, flags=re.UNICODE)


def compare_transcript_to_script(script, transcript, max_word_error_rate=0.25):
    expected = _tokens(script)
    actual = _tokens(transcript)
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
