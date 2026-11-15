"""Read-only production quality and recorded-economics analytics.

Only durable queue, production, review, publication and ledger records are used.
No inferred revenue, currency conversion, or external provider refresh is performed.
"""
import sqlite3
from collections import defaultdict
from math import sqrt


REVENUE_TYPES = {"youtube_ads", "affiliate", "sponsor"}
COST_TYPES = {"production_cost", "platform_fee", "other_cost"}
SUCCESS_QUEUE = {"review_pending", "uploaded"}
FAILURE_QUEUE = {"failed_terminal", "cancelled"}
PUBLISHED = {"uploaded", "published", "success", "complete", "completed"}


def _correlation(pairs):
    if len(pairs) < 5:
        return {"value": None, "sample_count": len(pairs),
                "assessment": "insufficient_samples"}
    xs = [x for x, _ in pairs]
    ys = [y for _, y in pairs]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    denom = sqrt(sum(x*x for x in dx) * sum(y*y for y in dy))
    if denom == 0:
        return {"value": None, "sample_count": len(pairs),
                "assessment": "zero_variance"}
    return {"value": round(sum(x*y for x, y in zip(dx, dy)) / denom, 4),
            "sample_count": len(pairs), "assessment": "exploratory_only"}


def build_operational_economics(db_path, limit=500):
    """Aggregate a bounded recent cohort using a SQLite read-only connection."""
    limit = max(1, min(int(limit), 500))
    uri = "file:" + str(db_path).replace("?", "%3F") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        jobs = [dict(row) for row in conn.execute("""
            SELECT q.id AS job_id, q.status AS queue_status,
                   q.error_code, q.created_at, q.updated_at,
                   r.brand, r.status AS production_status,
                   r.current_stage, r.error AS production_error,
                   (SELECT decision FROM review_decisions d
                    WHERE d.job_id=q.id ORDER BY d.id DESC LIMIT 1) AS review_decision,
                   (SELECT status FROM youtube_uploads y
                    WHERE y.job_id=q.id) AS youtube_status,
                   (SELECT status FROM tiktok_publications t
                    WHERE t.job_id=q.id) AS tiktok_status
            FROM pipeline_jobs q
            LEFT JOIN production_runs r ON r.job_id=q.id
            WHERE q.job_type='short_video_production'
            ORDER BY q.updated_at DESC, q.created_at DESC
            LIMIT ?
        """, (limit,)).fetchall()]
        job_ids = [row["job_id"] for row in jobs]
        ledger = []
        if job_ids:
            marks = ",".join("?" for _ in job_ids)
            ledger = [dict(row) for row in conn.execute(
                "SELECT job_id,brand,entry_type,amount,currency FROM financial_ledger "
                "WHERE job_id IN (" + marks + ")", job_ids).fetchall()]
    finally:
        conn.close()

    financial = defaultdict(lambda: defaultdict(float))
    for row in ledger:
        if not row["job_id"]:
            continue
        key = (row["job_id"], row["currency"])
        financial[key][row["entry_type"]] += float(row["amount"])

    brands = defaultdict(lambda: {
        "jobs": 0, "failed": 0, "reviewed": 0, "approved": 0,
        "youtube_published": 0, "tiktok_published": 0,
        "stage_counts": defaultdict(int),
    })
    currency_totals = defaultdict(lambda: {
        "jobs_with_financial_records": 0, "revenue": 0.0, "costs": 0.0,
        "net": 0.0, "job_pairs": [],
    })
    per_job_financial = []
    queue_counts = defaultdict(int)
    stage_counts = defaultdict(lambda: {"jobs": 0, "failed": 0})
    failure_codes = defaultdict(int)

    for job in jobs:
        brand = job.get("brand") or "unknown"
        b = brands[brand]
        b["jobs"] += 1
        status = job["queue_status"]
        queue_counts[status] += 1
        failed = status in FAILURE_QUEUE or job.get("production_status") == "failed_terminal"
        if failed:
            b["failed"] += 1
            if job.get("error_code"):
                failure_codes[job["error_code"]] += 1
        if job.get("review_decision"):
            b["reviewed"] += 1
            if job["review_decision"] == "approved":
                b["approved"] += 1
        if (job.get("youtube_status") or "").lower() in PUBLISHED:
            b["youtube_published"] += 1
        if (job.get("tiktok_status") or "").lower() in PUBLISHED:
            b["tiktok_published"] += 1
        stage = job.get("current_stage") or "unknown"
        b["stage_counts"][stage] += 1
        stage_counts[stage]["jobs"] += 1
        if failed:
            stage_counts[stage]["failed"] += 1

        job_financial = defaultdict(float)
        for (jid, currency), values in financial.items():
            if jid != job["job_id"]:
                continue
            revenue = sum(values.get(kind, 0.0) for kind in REVENUE_TYPES)
            costs = sum(values.get(kind, 0.0) for kind in COST_TYPES)
            if revenue == 0 and costs == 0:
                continue
            pair = currency_totals[currency]
            pair["jobs_with_financial_records"] += 1
            pair["revenue"] += revenue
            pair["costs"] += costs
            pair["net"] += revenue - costs
            pair["job_pairs"].append((costs, revenue))
            per_job_financial.append({
                "job_id": job["job_id"], "brand": brand, "currency": currency,
                "recorded_revenue": round(revenue, 2),
                "recorded_costs": round(costs, 2),
                "recorded_net": round(revenue - costs, 2),
                "roi_percent": round((revenue - costs) / costs * 100, 2) if costs else None,
            })

    brand_rows = []
    for name, item in sorted(brands.items()):
        brand_rows.append({
            "brand": name, "jobs": item["jobs"], "failed": item["failed"],
            "failure_rate_percent": round(item["failed"] / item["jobs"] * 100, 2)
                if item["jobs"] else None,
            "reviewed": item["reviewed"], "approved": item["approved"],
            "approval_rate_percent": round(item["approved"] / item["reviewed"] * 100, 2)
                if item["reviewed"] else None,
            "youtube_published": item["youtube_published"],
            "tiktok_published": item["tiktok_published"],
            "stage_counts": dict(item["stage_counts"]),
        })

    currency_rows = []
    for currency, item in sorted(currency_totals.items()):
        currency_rows.append({
            "currency": currency,
            "jobs_with_financial_records": item["jobs_with_financial_records"],
            "recorded_revenue": round(item["revenue"], 2),
            "recorded_costs": round(item["costs"], 2),
            "recorded_net": round(item["net"], 2),
            "cost_revenue_correlation": _correlation(item["job_pairs"]),
            "interpretation": "Recorded ledger entries only; no currency conversion or inferred revenue.",
        })

    stage_rows = [{
        "stage": stage, "jobs": item["jobs"], "failed": item["failed"],
        "failure_rate_percent": round(item["failed"] / item["jobs"] * 100, 2)
            if item["jobs"] else None,
    } for stage, item in sorted(stage_counts.items())]

    return {
        "cohort_jobs": len(jobs), "cohort_limit": limit,
        "queue_status_counts": dict(queue_counts),
        "brands": brand_rows, "stages": stage_rows,
        "failure_codes": dict(failure_codes),
        "financial_by_currency": currency_rows,
        "job_financial_records": per_job_financial,
        "data_quality": {
            "jobs_missing_production_record": sum(1 for j in jobs if not j.get("brand")),
            "jobs_with_recorded_financials": len(per_job_financial),
            "revenue_is_recorded_input": True,
            "currency_conversion_applied": False,
            "sample_threshold_for_correlation": 5,
        },
        "limitations": [
            "Only the latest bounded cohort is included, not lifetime history.",
            "Failure is a terminal queue or production failure; pending work is not a failure.",
            "Publication counts reflect persisted platform status, not independently verified public reach.",
            "Financial analysis includes only ledger rows linked to job_id; brand-only entries are excluded.",
            "Cost/revenue correlation is exploratory and does not establish causation or profitability.",
            "Revenue, costs and ROI are not comparable across currencies.",
        ],
        "read_only": True, "actions_taken": [],
    }
