"""Heuristic script similarity checks; this is not a platform policy verdict."""
import re


def _tokens(text):
    return re.findall(r"[^\W_]+", str(text or "").casefold(), flags=re.UNICODE)


def _shingles(tokens, size=5):
    if len(tokens) < size:
        return {tuple(tokens)} if tokens else set()
    return {tuple(tokens[index:index + size])
            for index in range(len(tokens) - size + 1)}


def compare_script_text(candidate, previous, shingle_size=5):
    candidate_tokens = _tokens(candidate)
    previous_tokens = _tokens(previous)
    if len(candidate_tokens) < 20 or len(previous_tokens) < 20:
        return {
            "comparable": False,
            "similarity": None,
            "exact_match": False,
            "reason": "minimum_20_tokens_required_for_comparison",
            "method": "normalized_token_5gram_jaccard_v1",
        }
    exact = candidate_tokens == previous_tokens
    left = _shingles(candidate_tokens, shingle_size)
    right = _shingles(previous_tokens, shingle_size)
    union = left | right
    similarity = len(left & right) / len(union) if union else 0.0
    return {
        "comparable": True,
        "similarity": round(similarity, 4),
        "exact_match": exact,
        "reason": None,
        "method": f"normalized_token_{shingle_size}gram_jaccard_v1",
    }


def build_script_originality_report(candidate, previous_scripts, threshold=0.82):
    if not 0.5 <= float(threshold) <= 1.0:
        raise ValueError("similarity threshold must be between 0.5 and 1.0")
    matches = []
    comparable_count = 0
    for item in previous_scripts:
        result = compare_script_text(candidate, item.get("script", ""))
        if not result["comparable"]:
            continue
        comparable_count += 1
        matches.append({
            "job_id": item.get("job_id"),
            "brand": item.get("brand"),
            "region": item.get("region"),
            "topic": item.get("topic"),
            **result,
        })
    matches.sort(key=lambda item: (item["similarity"], item["exact_match"]), reverse=True)
    similar = [item for item in matches if item["exact_match"] or item["similarity"] >= threshold]
    status = (
        "similar_content_found" if similar else
        "checked_no_similar_content" if comparable_count else
        "no_comparable_history"
    )
    return {
        "version": "script_originality_v1",
        "status": status,
        "method": "normalized token 5-gram Jaccard similarity; exact token-sequence match is also detected",
        "threshold": float(threshold),
        "history_candidates": len(previous_scripts),
        "comparable_candidates": comparable_count,
        "max_similarity": matches[0]["similarity"] if matches else None,
        "similar_matches": similar[:10],
        "warning": (
            "Similarity is a heuristic for reviewer attention, not a copyright finding or "
            "a platform reused-content policy determination. Topic overlap and common phrases "
            "can produce false positives; substantial paraphrasing can produce false negatives."
        ),
    }
