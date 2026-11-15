"""Evidence-bounded trend candidate ranking for brand production queues."""
import re
import statistics
from datetime import datetime, timezone


def _tokens(value):
    return {x for x in re.findall(r"[a-z0-9가-힣]{2,}", str(value or "").lower())
            if x not in {"the","and","for","with","why","how","what","this","that","your","from","into"}}


def _age_hours(value, now):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0.0, (now - parsed.astimezone(timezone.utc)).total_seconds() / 3600)
    except (TypeError, ValueError, OverflowError):
        return None


def _competitor_context(topic, region, channels, videos_by_channel):
    """Summarize stored public competitor samples without treating them as market demand."""
    topic_tokens = _tokens(topic)
    selected = [
        channel for channel in channels
        if not region or str(region).upper() == "GLOBAL"
        or str(channel.get("country") or "").upper() == str(region).upper()
    ]
    observed = []
    matched = []
    for channel in selected:
        for video in videos_by_channel.get(channel.get("channel_id"), []):
            views = video.get("view_count")
            if not isinstance(views, int) or views < 0:
                continue
            observed.append(video)
            title_tokens = _tokens(video.get("title"))
            overlap = len(topic_tokens & title_tokens) / len(topic_tokens) if topic_tokens else 0.0
            if overlap >= 0.25:
                matched.append({**video, "topic_overlap": round(overlap, 3)})
    matched_views = [item["view_count"] for item in matched]
    return {
        "selected_channels": len(selected),
        "observed_videos": len(observed),
        "topic_matched_videos": len(matched),
        "median_matched_views": int(statistics.median(matched_views)) if matched_views else None,
        "matched_examples": [
            {"title": item.get("title"), "views": item.get("view_count"),
             "channel_id": item.get("channel_id"), "published_at": item.get("published_at"),
             "topic_overlap": item["topic_overlap"]}
            for item in sorted(matched, key=lambda item: item.get("view_count", 0), reverse=True)[:5]
        ],
        "method": "Stored recent public competitor video titles; token overlap >= 25%; median is observed view counters only.",
        "limitations": "Only up to 10 recently collected channels and their stored recent videos; not market-wide demand, saturation, view velocity or revenue."
    }


def _brand_fit_score(trend_tokens, brand, config):
    """Weighted lexical fit with explicit exclusions; never infer demand or audience size."""
    groups = [
        (config.get("keywords", []), 3.0),
        (config.get("vertical", ""), 3.0),
        (brand.get("name", ""), 1.0),
        (config.get("positioning", ""), 1.5),
        (config.get("audience", ""), 0.25),
    ]
    weights = {}
    for values, weight in groups:
        if isinstance(values, str):
            values = [values]
        for value in values if isinstance(values, list) else []:
            for token in _tokens(value):
                weights[token] = max(weights.get(token, 0.0), weight)
    excluded = set()
    for value in config.get("exclude_keywords", []) if isinstance(config.get("exclude_keywords", []), list) else []:
        excluded.update(_tokens(value))
    excluded_matches = sorted(trend_tokens & excluded)
    matched = sorted(trend_tokens & set(weights))
    total_weight = sum(weights.values())
    matched_weight = sum(weights[token] for token in matched)
    score = 0.0 if excluded_matches or not total_weight else round(40.0 * matched_weight / total_weight, 2)
    return score, matched, excluded_matches


def _topic_performance_context(trend_tokens, brand_name, region, videos):
    """Match measured historical production topics to this trend without causal claims."""
    matched = []
    region = str(region or "").upper()
    for video in videos or []:
        if video.get("brand") != brand_name:
            continue
        if region and region != "GLOBAL" and str(video.get("region") or "").upper() != region:
            continue
        if video.get("measurement_status") != "measured":
            continue
        rate = video.get("views_per_hour")
        if not isinstance(rate, (int, float)) or rate < 0:
            continue
        topic_tokens = _tokens(video.get("topic"))
        overlap = len(trend_tokens & topic_tokens) / len(trend_tokens) if trend_tokens else 0.0
        if overlap >= 0.25:
            matched.append({
                "views_per_hour": float(rate),
                "interaction_rate": video.get("interactions_per_1000_view_delta"),
                "topic": video.get("topic"),
                "region": video.get("region"),
                "overlap": round(overlap, 3)
            })
    rates = [item["views_per_hour"] for item in matched]
    interaction_rates = [
        item["interaction_rate"] for item in matched
        if isinstance(item["interaction_rate"], (int, float))
        and item["interaction_rate"] >= 0
    ]
    count = len(matched)
    return {
        "matched_video_count": count,
        "median_views_per_hour": round(statistics.median(rates), 2) if rates else None,
        "interaction_rate_sample_count": len(interaction_rates),
        "median_interactions_per_1000_view_delta": (
            round(statistics.median(interaction_rates), 2) if interaction_rates else None
        ),
        "evidence_status": "no_data" if count == 0 else "limited" if count < 3 else "observed",
        "match_method": "measured_production_topic_token_overlap_at_least_25_percent",
        "ranking_score_adjustment": 0,
        "reason": "Topic-matched historical measurements are shown for review only; they do not change ranking."
    }


def _comparable_cohort_context(trend_tokens, brand_name, region, cohorts):
    """Expose brand/region/topic-matched cohorts without using them in ranking."""
    region = str(region or "").upper()
    matches = []
    for cohort in cohorts or []:
        if cohort.get("brand") != brand_name:
            continue
        cohort_region = str(cohort.get("region") or "").upper()
        if region and region != "GLOBAL" and cohort_region != region:
            continue
        if cohort.get("format") not in ("vertical_short", "vertical_short_requested"):
            continue
        topic_tokens = _tokens(cohort.get("topic_signature"))
        overlap = (
            len(trend_tokens & topic_tokens) / len(trend_tokens)
            if trend_tokens else 0.0
        )
        if overlap < 0.25:
            continue
        matches.append({
            "region": cohort_region,
            "publication_age_bucket": cohort.get("publication_age_bucket"),
            "duration_bucket": cohort.get("duration_bucket"),
            "format": cohort.get("format"),
            "topic_signature": cohort.get("topic_signature"),
            "sample_count": int(cohort.get("sample_count") or 0),
            "median_views_per_hour": cohort.get("median_views_per_hour"),
            "interaction_rate_sample_count": int(
                cohort.get("interaction_rate_sample_count") or 0
            ),
            "median_interactions_per_1000_view_delta": cohort.get(
                "median_interactions_per_1000_view_delta"
            ),
            "evidence_status": cohort.get("evidence_status", "limited"),
            "topic_overlap": round(overlap, 3),
        })
    matches.sort(
        key=lambda item: (
            item["sample_count"], item["topic_overlap"],
            item["publication_age_bucket"] == "under_24h"
        ),
        reverse=True,
    )
    return {
        "matched_cohort_count": len(matches),
        "cohorts": matches[:5],
        "ranking_score_adjustment": 0,
        "method": "brand + region + lexical topic overlap; publication age and duration remain separate cohort dimensions",
        "reason": "Comparable cohorts are contextual evidence only and do not change recommendation ranking before held-out validation.",
    }


def _source_evidence_score(trend, age):
    """Score source provenance completeness, not source popularity or trustworthiness."""
    score = 0.0
    if str(trend.get("source") or "").strip():
        score += 3.0
    url = str(trend.get("url") or "").strip().lower()
    if url.startswith("https://"):
        score += 3.0
    if age is not None:
        score += 4.0
    return score


def _novelty_scores(trends):
    """Penalize near-duplicate topic candidates using Jaccard similarity."""
    token_sets = [
        _tokens(str(item.get("title") or "") + " " + str(item.get("summary") or ""))
        for item in trends
    ]
    scores = []
    for index, tokens in enumerate(token_sets):
        similarities = []
        for other_index, other in enumerate(token_sets):
            if index == other_index or not tokens or not other:
                continue
            similarities.append(len(tokens & other) / len(tokens | other))
        maximum = max(similarities, default=0.0)
        scores.append(round(10.0 * (1.0 - maximum), 2))
    return scores


def rank_trend_candidates(trends, brands, competitor_store=None, limit=30, now=None,
                          performance_by_brand=None, performance_videos=None,
                          performance_cohorts=None):
    """Rank collected trends for editorial review; never fabricate demand or revenue."""
    now = now or datetime.now(timezone.utc)
    performance_by_brand = performance_by_brand or {}
    performance_videos = performance_videos or []
    performance_cohorts = performance_cohorts or []
    brand_rows = []
    for brand in brands:
        if not brand.get("active", True):
            continue
        config = brand.get("config") or {}
        brand_tokens = _tokens(" ".join([
            brand.get("name", ""), config.get("positioning", ""),
            config.get("vertical", ""), config.get("audience", "")
        ]))
        brand_rows.append((brand, config, brand_tokens))

    regions_needed = {str(trend.get("region") or "").upper() for trend in trends}
    include_all_regions = not regions_needed or "" in regions_needed or "GLOBAL" in regions_needed
    competitor_channels = competitor_store.list_channels(limit=200) if competitor_store and trends else []
    if not include_all_regions:
        competitor_channels = [
            channel for channel in competitor_channels
            if str(channel.get("country") or "").upper() in regions_needed
        ]
    competitor_channels = competitor_channels[:10]
    videos_by_channel = {
        channel.get("channel_id"): competitor_store.list_videos(channel.get("channel_id"), limit=30)
        for channel in competitor_channels
    } if competitor_store else {}

    ranked = []
    novelty_by_index = _novelty_scores(trends)
    for trend_index, trend in enumerate(trends):
        title = str(trend.get("title") or "").strip()
        if not title:
            continue
        trend_tokens = _tokens(title + " " + str(trend.get("summary") or ""))
        # Collection time is not a proxy for publication time. If the source
        # timestamp is absent or invalid, freshness is unverified and receives 0.
        age = _age_hours(trend.get("published_at"), now)
        freshness = 0.0 if age is None else round(
            40 * max(0.0, 1.0 - min(age, 168.0) / 168.0), 2
        )
        candidates = []
        region_eligible = 0
        for brand, config, tokens in brand_rows:
            region = str(trend.get("region") or "").upper()
            allowed_regions = {
                str(value).upper() for value in config.get("regions", [])
            }
            if region and region != "GLOBAL" and allowed_regions and region not in allowed_regions:
                continue
            trend_language = str(trend.get("language") or "").strip().lower()
            allowed_languages = {
                str(value).strip().lower().split("-")[0]
                for value in config.get("languages", [])
                if str(value).strip()
            }
            if (trend_language and allowed_languages
                    and trend_language.split("-")[0] not in allowed_languages):
                continue
            region_eligible += 1
            fit, matched_terms, excluded_terms = _brand_fit_score(
                trend_tokens, brand, config
            )
            if fit <= 0:
                continue
            observed = performance_by_brand.get(brand.get("name"), {})
            rate_samples = int(observed.get("rate_sample_count") or 0)
            candidates.append({
                "brand": brand.get("slug"), "brand_name": brand.get("name"),
                "fit_score": fit, "matched_terms": matched_terms,
                "excluded_terms": excluded_terms,
                "match_method": "weighted_profile_term_coverage",
                "historical_performance": {
                    "measured_videos": int(observed.get("measured_videos") or 0),
                    "rate_sample_count": rate_samples,
                    "median_views_per_hour": observed.get("median_views_per_hour"),
                    "interaction_rate_sample_count": int(
                        observed.get("interaction_rate_sample_count") or 0
                    ),
                    "median_interactions_per_1000_view_delta": observed.get(
                        "median_interactions_per_1000_view_delta"
                    ),
                    "evidence_status": (
                        "no_data" if rate_samples == 0
                        else "limited" if rate_samples < 3 else "observed"
                    ),
                    "ranking_score_adjustment": 0,
                    "reason": "Historical brand-level signal is shown for review only; it is not yet topic-matched or used to alter ranking."
                },
                "topic_performance": _topic_performance_context(
                    trend_tokens, brand.get("name"), trend.get("region"), performance_videos
                ),
                "comparable_cohort_performance": _comparable_cohort_context(
                    trend_tokens, brand.get("name"), trend.get("region"), performance_cohorts
                ),
                "supported_languages": config.get("languages", []),
                "language_match": (
                    "unverified" if not trend_language
                    else "matched" if not allowed_languages
                    or trend_language.split("-")[0] in allowed_languages
                    else "unsupported"
                )
            })
        if region and region != "GLOBAL" and region_eligible == 0:
            continue
        candidates.sort(key=lambda x: (-x["fit_score"], x["brand"] or ""))
        best = candidates[0] if candidates else None
        trend_region = str(trend.get("region") or "").upper()
        selected_channels = [
            channel for channel in competitor_channels
            if not trend_region or trend_region == "GLOBAL"
            or str(channel.get("country") or "").upper() == trend_region
        ]
        if competitor_store:
            for channel in selected_channels:
                channel_id = channel.get("channel_id")
                if channel_id and channel_id not in videos_by_channel:
                    videos_by_channel[channel_id] = competitor_store.list_videos(
                        channel_id, limit=30
                    )
        competitor_context = _competitor_context(
            title + " " + str(trend.get("summary") or ""), trend.get("region"),
            selected_channels, videos_by_channel
        )
        evidence_gaps = ["search_volume_unavailable", "shorts_demand_unverified",
                         "revenue_and_cost_not_estimated"]
        if competitor_context["observed_videos"] == 0:
            evidence_gaps.append("competitor_video_sample_unavailable")
        elif competitor_context["topic_matched_videos"] == 0:
            evidence_gaps.append("no_topic_matched_competitor_videos")
        # The final 20 points measure provenance completeness and topic distinctiveness,
        # not market demand, views, or monetization.
        source_evidence = _source_evidence_score(trend, age)
        novelty = novelty_by_index[trend_index] if best else 0.0
        score = round(freshness + (best["fit_score"] if best else 0)
                      + source_evidence + novelty, 2)
        if source_evidence < 10:
            evidence_gaps.append("trend_source_provenance_incomplete")
        if age is None:
            evidence_gaps.append("trend_publication_timestamp_unavailable")
        ranked.append({
            "trend": trend, "recommendation_score": score,
            "freshness_score": freshness,
            "publication_age_hours": round(age, 2) if age is not None else None,
            "freshness_evidence": "publisher_timestamp" if age is not None else "unverified",
            "source_evidence_score": source_evidence,
            "topic_distinctiveness_score": novelty,
            "score_breakdown": {
                "freshness": freshness,
                "brand_fit": best["fit_score"] if best else 0,
                "source_provenance_completeness": source_evidence,
                "topic_distinctiveness": novelty,
            },
            "brand_candidates": candidates[:3],
            "best_brand": best, "competitor_context": competitor_context,
            "score_type": "editorial_signal_not_profitability",
            "evidence_gaps": evidence_gaps
        })
    ranked.sort(key=lambda x: (-x["recommendation_score"],
                               x["trend"].get("published_at") or x["trend"].get("collected_at") or ""))
    return ranked[:max(1, min(int(limit), 100))]
