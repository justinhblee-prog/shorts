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


def rank_trend_candidates(trends, brands, competitor_store=None, limit=30, now=None):
    """Rank collected trends for editorial review; never fabricate demand or revenue."""
    now = now or datetime.now(timezone.utc)
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
    competitor_channels = competitor_store.list_channels(limit=10) if competitor_store and trends else []
    if not include_all_regions:
        competitor_channels = [
            channel for channel in competitor_channels
            if str(channel.get("country") or "").upper() in regions_needed
        ]
    videos_by_channel = {
        channel.get("channel_id"): competitor_store.list_videos(channel.get("channel_id"), limit=30)
        for channel in competitor_channels
    } if competitor_store else {}

    ranked = []
    for trend in trends:
        title = str(trend.get("title") or "").strip()
        if not title:
            continue
        trend_tokens = _tokens(title + " " + str(trend.get("summary") or ""))
        age = _age_hours(trend.get("published_at") or trend.get("collected_at"), now)
        freshness = 0.0 if age is None else round(40 * max(0.0, 1.0 - min(age, 168.0) / 168.0), 2)
        candidates = []
        region_eligible = 0
        for brand, config, tokens in brand_rows:
            region = str(trend.get("region") or "").upper()
            if region and region != "GLOBAL" and region not in config.get("regions", []):
                continue
            region_eligible += 1
            overlap = len(tokens & trend_tokens) / len(trend_tokens) if trend_tokens else 0.0
            fit = round(40 * min(1.0, overlap * 2.0), 2)
            if fit <= 0:
                continue
            candidates.append({
                "brand": brand.get("slug"), "brand_name": brand.get("name"),
                "fit_score": fit, "supported_languages": config.get("languages", [])
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
        # The remaining 20 points are deliberately unallocated: competitor samples
        # are selected-channel observations, not a comparable market-demand measure.
        score = round(freshness + (best["fit_score"] if best else 0), 2)
        ranked.append({
            "trend": trend, "recommendation_score": score,
            "freshness_score": freshness, "brand_candidates": candidates[:3],
            "best_brand": best, "competitor_context": competitor_context,
            "score_type": "editorial_signal_not_profitability",
            "evidence_gaps": evidence_gaps
        })
    ranked.sort(key=lambda x: (-x["recommendation_score"],
                               x["trend"].get("published_at") or x["trend"].get("collected_at") or ""))
    return ranked[:max(1, min(int(limit), 100))]
