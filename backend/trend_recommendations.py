"""Evidence-bounded trend candidate ranking for brand production queues."""
import re
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
        # The remaining 20 points are deliberately unallocated: trend feeds do not
        # provide comparable search volume, audience demand, or monetization evidence.
        score = round(freshness + (best["fit_score"] if best else 0), 2)
        ranked.append({
            "trend": trend, "recommendation_score": score,
            "freshness_score": freshness, "brand_candidates": candidates[:3],
            "best_brand": best, "score_type": "editorial_signal_not_profitability",
            "evidence_gaps": ["search_volume_unavailable", "shorts_demand_unverified",
                              "revenue_and_cost_not_estimated"]
        })
    ranked.sort(key=lambda x: (-x["recommendation_score"],
                               x["trend"].get("published_at") or x["trend"].get("collected_at") or ""))
    return ranked[:max(1, min(int(limit), 100))]
