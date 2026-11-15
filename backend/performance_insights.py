"""Evidence-bound performance analysis; no synthetic metrics or predictive claims."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone


def _elapsed_hours(start, end):
    """Return positive elapsed hours for two timestamps (naive values are assumed UTC)."""
    try:
        first = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        last = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
        if first.tzinfo is None:
            first = first.replace(tzinfo=timezone.utc)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        seconds = (last - first).total_seconds()
        return round(seconds / 3600.0, 4) if seconds > 0 else None
    except (TypeError, ValueError):
        return None


class PerformanceAnalyzer:
    def __init__(self, db_path="data/nexus.sqlite3"):
        self.db_path = str(db_path)

    @contextmanager
    def db(self):
        c = sqlite3.connect(self.db_path, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA busy_timeout=30000")
        try:
            yield c
        finally:
            c.close()

    def analyze(self, brand=None):
        with self.db() as c:
            where = "WHERE r.status IN ('uploaded','approved')"
            args = []
            if brand:
                where += " AND r.brand=?"
                args.append(brand)
            videos = c.execute("""
                SELECT r.job_id,r.brand,r.region,r.topic,u.video_id,
                       s.view_count,s.like_count,s.comment_count,s.collected_at
                FROM production_runs r
                JOIN youtube_uploads u ON u.job_id=r.job_id AND u.status='uploaded'
                LEFT JOIN youtube_video_snapshots s ON s.video_id=u.video_id
            """ + where + " ORDER BY r.brand,r.region,r.job_id,s.collected_at", args).fetchall()

            ledger_where = "WHERE 1=1"
            ledger_args = []
            if brand:
                ledger_where += " AND brand=?"
                ledger_args.append(brand)
            ledger = c.execute("""
                SELECT brand,currency,entry_type,SUM(amount) amount,COUNT(*) entries
                FROM financial_ledger
            """ + ledger_where + " GROUP BY brand,currency,entry_type ORDER BY brand,currency,entry_type",
                ledger_args).fetchall()

        groups = {}
        for row in videos:
            key = row["job_id"]
            item = groups.setdefault(key, {
                "job_id": key, "brand": row["brand"], "region": row["region"],
                "topic": row["topic"], "video_id": row["video_id"], "snapshots": []
            })
            if row["collected_at"] is not None:
                item["snapshots"].append({
                    "views": row["view_count"], "likes": row["like_count"],
                    "comments": row["comment_count"], "collected_at": row["collected_at"]
                })

        by_brand = {}
        by_region = {}
        video_results = []
        for video in groups.values():
            brand_row = by_brand.setdefault(video["brand"], {
                "brand": video["brand"], "videos": 0, "measured_videos": 0,
                "unmeasured_videos": 0, "view_delta": 0, "like_delta": 0,
                "comment_delta": 0, "recommendations": []
            })
            region_key = (video["brand"], video["region"])
            region_row = by_region.setdefault(region_key, {
                "brand": video["brand"], "region": video["region"],
                "videos": 0, "measured_videos": 0, "unmeasured_videos": 0,
                "view_delta": 0, "like_delta": 0, "comment_delta": 0
            })
            brand_row["videos"] += 1
            region_row["videos"] += 1
            snaps = video["snapshots"]
            result = {
                "job_id": video["job_id"], "brand": video["brand"],
                "region": video["region"], "topic": video["topic"],
                "video_id": video["video_id"], "snapshot_count": len(snaps),
                "measurement_status": "insufficient_snapshots"
            }
            if len(snaps) >= 2:
                first, last = snaps[0], snaps[-1]
                deltas = {}
                for source, target in (("views", "view_delta"),
                                       ("likes", "like_delta"),
                                       ("comments", "comment_delta")):
                    a, b = first[source], last[source]
                    deltas[target] = (b - a) if a is not None and b is not None else None
                result.update(deltas)
                result["first_snapshot_at"] = first["collected_at"]
                result["last_snapshot_at"] = last["collected_at"]
                result["elapsed_hours"] = _elapsed_hours(
                    first["collected_at"], last["collected_at"]
                )
                if deltas["view_delta"] is not None and deltas["view_delta"] >= 0:
                    result["measurement_status"] = "measured"
                    brand_row["measured_videos"] += 1
                    region_row["measured_videos"] += 1
                    brand_row["view_delta"] += deltas["view_delta"]
                    region_row["view_delta"] += deltas["view_delta"]
                    for field in ("like_delta", "comment_delta"):
                        if deltas[field] is not None and deltas[field] >= 0:
                            brand_row[field] += deltas[field]
                            region_row[field] += deltas[field]
                        elif deltas[field] is not None:
                            # Counter resets are missing evidence, not negative engagement.
                            deltas[field] = None
                            result[field] = None
                    result["views_per_hour"] = (
                        round(deltas["view_delta"] / result["elapsed_hours"], 2)
                        if result["elapsed_hours"] is not None else None
                    )
                    interaction_delta = (
                        deltas["like_delta"] + deltas["comment_delta"]
                        if deltas["like_delta"] is not None and deltas["comment_delta"] is not None
                        else None
                    )
                    result["interaction_delta"] = interaction_delta
                    result["interactions_per_1000_view_delta"] = (
                        round(interaction_delta * 1000 / deltas["view_delta"], 2)
                        if interaction_delta is not None and deltas["view_delta"] > 0
                        else None
                    )
                else:
                    result["measurement_status"] = "counter_reset_or_invalid"
                    result["views_per_hour"] = None
                    result["interaction_delta"] = None
                    result["interactions_per_1000_view_delta"] = None
                    brand_row["unmeasured_videos"] += 1
                    region_row["unmeasured_videos"] += 1
            else:
                brand_row["unmeasured_videos"] += 1
                region_row["unmeasured_videos"] += 1
            video_results.append(result)

        for item in by_brand.values():
            if item["measured_videos"] == 0:
                item["recommendations"].append({
                    "type": "insufficient_evidence",
                    "basis": "no_valid_comparable_view_snapshots",
                    "action": "Collect at least two valid YouTube counter snapshots per video before ranking performance"
                })
            elif item["unmeasured_videos"]:
                item["recommendations"].append({
                    "type": "measurement_coverage",
                    "basis": "some_videos_lack_valid_comparable_snapshots",
                    "action": "Collect missing snapshots and verify counter resets before comparing all videos"
                })
            if item["view_delta"] < 0:
                item["recommendations"].append({
                    "type": "review_topic_and_packaging",
                    "basis": "negative_observed_view_delta",
                    "action": "Review topic selection, title and opening hook; test one controlled change"
                })
            elif item["view_delta"] > 0:
                item["recommendations"].append({
                    "type": "retain_and_test",
                    "basis": "positive_observed_view_delta",
                    "action": "Retain the observed format as a hypothesis and test one controlled variation"
                })
            item["view_delta_is_snapshot_difference"] = True

        financial = {}
        for row in ledger:
            key = (row["brand"], row["currency"])
            item = financial.setdefault(key, {
                "brand": row["brand"], "currency": row["currency"],
                "revenue": 0.0, "costs": 0.0, "net": 0.0, "entries": 0
            })
            amount = float(row["amount"])
            item["entries"] += int(row["entries"])
            if row["entry_type"] in ("youtube_ads", "affiliate", "sponsor"):
                item["revenue"] += amount
            else:
                item["costs"] += amount
        for item in financial.values():
            item["revenue"] = round(item["revenue"], 2)
            item["costs"] = round(item["costs"], 2)
            item["net"] = round(item["revenue"] - item["costs"], 2)

        return {
            "method": "rule_based_source_evidence_only",
            "brands": list(by_brand.values()),
            "regions": list(by_region.values()),
            "videos": video_results,
            "financial": list(financial.values()),
            "limitations": [
                "View deltas are differences between stored snapshots, not real-time platform analytics.",
                "Views per hour is normalized between stored snapshots, not a platform-provided velocity metric.",
                "Interactions per 1000 view delta uses like and comment counter differences only; it is not audience-retention or satisfaction data.",
                "Negative view-counter differences are treated as resets or invalid measurements and excluded from aggregate growth; negative interaction deltas are omitted.",
                "Audience retention, average view duration, viewed-versus-swiped-away and subscriber conversion require eligible YouTube Analytics data and are not inferred from Data API counters.",
                "Recommendations are operational heuristics, not causal claims or forecasts.",
                "Financial totals include only recorded ledger entries.",
                "Financials are separated by brand and currency; no implicit foreign-exchange conversion is applied."
            ]
        }
