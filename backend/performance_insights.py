"""Evidence-bound performance analysis; no synthetic metrics or predictive claims."""
import json
import math
import re
import sqlite3
import statistics
from youtube_analytics import YouTubeAnalyticsStore
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
        # Avoid unstable hourly rates from near-simultaneous snapshots.
        return round(seconds / 3600.0, 6) if seconds >= 60 else None
    except (TypeError, ValueError):
        return None


def _publication_age_bucket(uploaded_at, measured_at):
    hours = _elapsed_hours(uploaded_at, measured_at)
    if hours is None:
        return "unknown"
    if hours < 24:
        return "under_24h"
    if hours < 24 * 7:
        return "1_7d"
    if hours < 24 * 30:
        return "7_30d"
    return "over_30d"


def _duration_bucket(value):
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return "unknown"
    if seconds <= 0:
        return "unknown"
    if seconds < 20:
        return "under_20s"
    if seconds < 40:
        return "20_40s"
    if seconds < 60:
        return "40_60s"
    return "over_60s"


def _topic_signature(value):
    tokens = set(re.findall(r"[a-z0-9가-힣]{2,}", str(value or "").lower()))
    tokens -= {"the", "and", "for", "with", "why", "how", "what", "this", "that"}
    return " ".join(sorted(tokens)) if tokens else "unknown"


def _render_format(metadata):
    value = str(metadata.get("format") or "").strip().lower()
    if value in ("vertical_short", "vertical", "9:16"):
        return "vertical_short"
    if value in ("horizontal", "16:9"):
        return "horizontal_16_9"
    if value in ("square", "1:1"):
        return "square"
    ratio = str(metadata.get("aspect_ratio") or "").strip()
    if ratio == "9:16":
        return "vertical_short"
    if ratio == "16:9":
        return "horizontal_16_9"
    if ratio == "1:1":
        return "square"
    # All production jobs in this pipeline request 9:16; distinguish requested
    # format from verified rendered dimensions when the provider omits metadata.
    return "vertical_short_requested"


def _retention_diagnostics(curve):
    """Summarize observed adjacent retention changes without inferring causes."""
    points = []
    for point in curve if isinstance(curve, list) else []:
        if not isinstance(point, dict):
            continue
        position = point.get("elapsed_video_time_ratio")
        audience = point.get("audience_watch_ratio")
        try:
            position = float(position)
            audience = float(audience)
        except (TypeError, ValueError):
            continue
        if not (0 <= position <= 1 and 0 <= audience <= 1):
            continue
        if not (math.isfinite(position) and math.isfinite(audience)):
            continue
        points.append((position, audience))
    points.sort(key=lambda item: item[0])
    if not points:
        return {
            "status": "unavailable",
            "point_count": 0,
            "early_retention": None,
            "end_retention": None,
            "largest_dropoff": None,
        }

    early = next((audience for position, audience in points if position <= 0.1), None)
    largest = None
    for (start_position, start_value), (end_position, end_value) in zip(points, points[1:]):
        drop = start_value - end_value
        if drop > 0 and (largest is None or drop > largest["drop"]):
            largest = {
                "start_video_ratio": start_position,
                "end_video_ratio": end_position,
                "drop": drop,
            }
    if largest:
        largest = {
            "start_video_ratio": largest["start_video_ratio"],
            "end_video_ratio": largest["end_video_ratio"],
            "drop_percentage_points": round(largest["drop"] * 100, 2),
        }
    return {
        "status": "available",
        "point_count": len(points),
        "early_retention": round(early, 4) if early is not None else None,
        "end_retention": round(points[-1][1], 4),
        "largest_dropoff": largest,
    }



class PerformanceAnalyzer:
    def __init__(self, db_path="data/nexus.sqlite3"):
        self.db_path = str(db_path)
        self.analytics_store = YouTubeAnalyticsStore(self.db_path)

    @contextmanager
    def db(self):
        c = sqlite3.connect(self.db_path, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA busy_timeout=30000")
        try:
            yield c
        finally:
            c.close()

    def _analyze_tiktok(self, brand=None):
        with self.db() as connection:
            where = "WHERE p.status='publish_complete'"
            args = []
            if brand:
                where += " AND r.brand=?"
                args.append(brand)
            rows = connection.execute("""
                SELECT r.job_id,r.brand,r.region,r.topic,p.video_id,
                       COALESCE(published.published_at,p.updated_at) AS published_at,
                       a.metadata_json AS rendering_metadata_json,
                       s.view_count,s.like_count,s.comment_count,s.share_count,s.collected_at
                FROM production_runs r
                JOIN tiktok_publications p ON p.job_id=r.job_id
                LEFT JOIN (
                    SELECT job_id,MIN(created_at) AS published_at
                    FROM tiktok_publication_events
                    WHERE event_type='status_refreshed'
                      AND UPPER(outcome)='PUBLISH_COMPLETE'
                    GROUP BY job_id
                ) published ON published.job_id=p.job_id
                LEFT JOIN production_artifacts a
                  ON a.job_id=r.job_id AND a.stage='rendering' AND a.artifact_type='video'
                LEFT JOIN tiktok_video_metric_snapshots s ON s.video_id=p.video_id
            """ + where + " ORDER BY r.brand,r.region,r.job_id,s.collected_at", args).fetchall()
            ledger_where = "WHERE 1=1"
            ledger_args = []
            if brand:
                ledger_where += " AND brand=?"
                ledger_args.append(brand)
            ledger = connection.execute("""
                SELECT brand,currency,entry_type,SUM(amount) amount,COUNT(*) entries
                FROM financial_ledger
            """ + ledger_where + " GROUP BY brand,currency,entry_type ORDER BY brand,currency,entry_type",
                ledger_args).fetchall()

        grouped = {}
        for row in rows:
            key = row["job_id"]
            item = grouped.setdefault(key, {
                "job_id":key,"brand":row["brand"],"region":row["region"],
                "topic":row["topic"],"video_id":row["video_id"],
                "uploaded_at":row["published_at"],
                "rendering_metadata_json":row["rendering_metadata_json"],
                "snapshots":[],
            })
            if row["collected_at"] is not None:
                item["snapshots"].append({
                    "views":row["view_count"],"likes":row["like_count"],
                    "comments":row["comment_count"],"shares":row["share_count"],
                    "collected_at":row["collected_at"],
                })

        by_brand = {}
        by_region = {}
        video_results = []
        for video in grouped.values():
            brand_row = by_brand.setdefault(video["brand"], {
                "brand":video["brand"],"videos":0,"measured_videos":0,
                "unmeasured_videos":0,"view_delta":0,"like_delta":0,
                "comment_delta":0,"share_delta":0,"recommendations":[],
                "_views_per_hour_samples":[],"_interaction_rate_samples":[],
            })
            region_key=(video["brand"],video["region"])
            region_row=by_region.setdefault(region_key,{
                "brand":video["brand"],"region":video["region"],"videos":0,
                "measured_videos":0,"unmeasured_videos":0,"view_delta":0,
                "like_delta":0,"comment_delta":0,"share_delta":0,
            })
            brand_row["videos"]+=1
            region_row["videos"]+=1
            try:
                render_metadata=json.loads(video["rendering_metadata_json"] or "{}")
                if not isinstance(render_metadata,dict):
                    render_metadata={}
            except (TypeError,ValueError):
                render_metadata={}
            duration=render_metadata.get("duration_seconds")
            if duration is None and isinstance(render_metadata.get("media_inspection"),dict):
                duration=render_metadata["media_inspection"].get("duration_seconds")
            result={
                "platform":"tiktok","job_id":video["job_id"],"brand":video["brand"],
                "region":video["region"],"topic":video["topic"],
                "topic_signature":_topic_signature(video["topic"]),
                "video_id":video["video_id"],"uploaded_at":video["uploaded_at"],
                "duration_seconds":duration,"duration_bucket":_duration_bucket(duration),
                "format":_render_format(render_metadata),
                "snapshot_count":len(video["snapshots"]),
                "publication_age_bucket":"unknown",
                "measurement_status":"insufficient_snapshots",
                "views_per_hour":None,"interactions_per_1000_view_delta":None,
            }
            snapshots=video["snapshots"]
            if len(snapshots)>=2:
                first,last=snapshots[0],snapshots[-1]
                elapsed=_elapsed_hours(first["collected_at"],last["collected_at"])
                result["first_snapshot_at"]=first["collected_at"]
                result["last_snapshot_at"]=last["collected_at"]
                result["elapsed_hours"]=elapsed
                result["publication_age_bucket"]=_publication_age_bucket(
                    video["uploaded_at"],last["collected_at"]
                )
                deltas={}
                for source,target in (("views","view_delta"),("likes","like_delta"),
                                      ("comments","comment_delta"),("shares","share_delta")):
                    left,right=first[source],last[source]
                    deltas[target]=(right-left) if left is not None and right is not None else None
                    if deltas[target] is not None and deltas[target]<0:
                        deltas[target]=None
                result.update(deltas)
                if deltas["view_delta"] is not None and elapsed is not None:
                    result["measurement_status"]="measured"
                    result["views_per_hour"]=round(deltas["view_delta"]/elapsed,2)
                    brand_row["measured_videos"]+=1
                    region_row["measured_videos"]+=1
                    for field in ("view_delta","like_delta","comment_delta","share_delta"):
                        if deltas[field] is not None:
                            brand_row[field]+=deltas[field]
                            region_row[field]+=deltas[field]
                    interaction_values=[deltas[x] for x in ("like_delta","comment_delta","share_delta")]
                    interaction_delta=sum(interaction_values) if all(x is not None for x in interaction_values) else None
                    result["interaction_delta"]=interaction_delta
                    result["interactions_per_1000_view_delta"]=(
                        round(interaction_delta*1000/deltas["view_delta"],2)
                        if interaction_delta is not None and deltas["view_delta"]>0 else None
                    )
                    brand_row["_views_per_hour_samples"].append(result["views_per_hour"])
                    if result["interactions_per_1000_view_delta"] is not None:
                        brand_row["_interaction_rate_samples"].append(
                            result["interactions_per_1000_view_delta"]
                        )
                else:
                    result["measurement_status"]="counter_reset_or_invalid"
                    brand_row["unmeasured_videos"]+=1
                    region_row["unmeasured_videos"]+=1
            else:
                brand_row["unmeasured_videos"]+=1
                region_row["unmeasured_videos"]+=1
            video_results.append(result)

        for item in by_brand.values():
            rates=item.pop("_views_per_hour_samples")
            interactions=item.pop("_interaction_rate_samples")
            item["rate_sample_count"]=len(rates)
            item["median_views_per_hour"]=round(statistics.median(rates),2) if rates else None
            item["interaction_rate_sample_count"]=len(interactions)
            item["median_interactions_per_1000_view_delta"]=(
                round(statistics.median(interactions),2) if interactions else None
            )
            item["performance_evidence_status"]="limited" if len(rates)<3 else "sample_available"
            if not item["measured_videos"]:
                item["recommendations"].append({
                    "type":"insufficient_evidence","basis":"no_valid_comparable_tiktok_snapshots",
                    "action":"Collect at least two valid TikTok metric snapshots per published video before comparing performance"
                })
            elif item["unmeasured_videos"]:
                item["recommendations"].append({
                    "type":"measurement_coverage","basis":"some_tiktok_videos_lack_valid_snapshots",
                    "action":"Collect missing TikTok snapshots and verify counter resets before comparing all videos"
                })
            item["view_delta_is_snapshot_difference"]=True

        cohort_groups={}
        for video in video_results:
            if video.get("measurement_status")!="measured":
                continue
            rate=video.get("views_per_hour")
            if not isinstance(rate,(int,float)) or rate<0:
                continue
            key=(video["brand"],video["region"],video["publication_age_bucket"],
                 video["duration_bucket"],video["format"],video["topic_signature"])
            cohort=cohort_groups.setdefault(key,{
                "platform":"tiktok","brand":key[0],"region":key[1],
                "publication_age_bucket":key[2],"duration_bucket":key[3],
                "format":key[4],"topic_signature":key[5],
                "_views_per_hour":[],"_interaction_rates":[],
            })
            cohort["_views_per_hour"].append(float(rate))
            interaction=video.get("interactions_per_1000_view_delta")
            if isinstance(interaction,(int,float)) and interaction>=0:
                cohort["_interaction_rates"].append(float(interaction))
        cohorts=[]
        for cohort in cohort_groups.values():
            rates=cohort.pop("_views_per_hour")
            interactions=cohort.pop("_interaction_rates")
            cohort.update({
                "sample_count":len(rates),
                "median_views_per_hour":round(statistics.median(rates),2),
                "interaction_rate_sample_count":len(interactions),
                "median_interactions_per_1000_view_delta":(
                    round(statistics.median(interactions),2) if interactions else None
                ),
                "evidence_status":"limited" if len(rates)<3 else "observed",
                "ranking_score_adjustment":0,
                "usage":"display_only_pending_held_out_validation",
            })
            cohorts.append(cohort)
        cohorts.sort(key=lambda x:(x["brand"],x["region"],x["publication_age_bucket"],
                                   x["duration_bucket"],x["format"],x["topic_signature"]))
        financial={}
        for row in ledger:
            key=(row["brand"],row["currency"])
            item=financial.setdefault(key,{"brand":row["brand"],"currency":row["currency"],
                "revenue":0.0,"costs":0.0,"net":0.0,"entries":0})
            amount=float(row["amount"])
            item["entries"]+=int(row["entries"])
            if row["entry_type"] in ("youtube_ads","affiliate","sponsor"):
                item["revenue"]+=amount
            else:
                item["costs"]+=amount
            item["net"]=round(item["revenue"]-item["costs"],2)
        return {
            "platform":"tiktok","brands":list(by_brand.values()),
            "regions":list(by_region.values()),"videos":video_results,
            "cohorts":cohorts,"financial":list(financial.values()),
            "metric_boundary":{
                "source":"TikTok Display API v2",
                "available":["view_count","like_count","comment_count","share_count"],
                "unavailable":["audience_retention","watch_time","estimated_revenue"],
                "view_velocity":"difference between stored snapshots normalized by elapsed time; not a TikTok-provided recommendation score",
                "ranking_score_adjustment":0,
            },
        }

    def analyze(self, brand=None, platform="youtube"):
        if platform == "tiktok":
            return self._analyze_tiktok(brand)
        if platform != "youtube":
            raise ValueError("platform must be youtube or tiktok")
        with self.db() as c:
            where = "WHERE r.status IN ('uploaded','approved')"
            args = []
            if brand:
                where += " AND r.brand=?"
                args.append(brand)
            videos = c.execute("""
                SELECT r.job_id,r.brand,r.region,r.topic,u.video_id,u.uploaded_at,
                       a.metadata_json AS rendering_metadata_json,
                       s.view_count,s.like_count,s.comment_count,s.collected_at,
                       an.engaged_views AS analytics_engaged_views,
                       an.engaged_view_share AS analytics_engaged_view_share,
                       an.average_view_duration AS analytics_average_view_duration,
                       an.average_view_percentage AS analytics_average_view_percentage,
                       an.estimated_minutes_watched AS analytics_estimated_minutes_watched,
                       an.retention_json AS analytics_retention_json,
                       an.analytics_status,an.retention_status,
                       an.collected_at AS analytics_collected_at
                FROM production_runs r
                JOIN youtube_uploads u ON u.job_id=r.job_id AND u.status='uploaded'
                LEFT JOIN production_artifacts a
                  ON a.job_id=r.job_id AND a.stage='rendering' AND a.artifact_type='video'
                LEFT JOIN youtube_video_snapshots s ON s.video_id=u.video_id
                LEFT JOIN youtube_analytics_snapshots an ON an.video_id=u.video_id
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
                "topic": row["topic"], "video_id": row["video_id"],
                "uploaded_at": row["uploaded_at"],
                "rendering_metadata_json": row["rendering_metadata_json"],
                "analytics_engaged_views": row["analytics_engaged_views"],
                "analytics_engaged_view_share": row["analytics_engaged_view_share"],
                "analytics_average_view_duration": row["analytics_average_view_duration"],
                "analytics_average_view_percentage": row["analytics_average_view_percentage"],
                "analytics_estimated_minutes_watched": row["analytics_estimated_minutes_watched"],
                "analytics_retention_json": row["analytics_retention_json"],
                "analytics_status": row["analytics_status"],
                "retention_status": row["retention_status"],
                "analytics_collected_at": row["analytics_collected_at"],
                "snapshots": []
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
                "comment_delta": 0, "recommendations": [],
                "_views_per_hour_samples": [], "_interaction_rate_samples": [],
                "_average_view_duration_samples": [], "_average_view_percentage_samples": [],
                "_engaged_view_share_samples": []
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
            try:
                render_metadata = json.loads(video["rendering_metadata_json"] or "{}")
                if not isinstance(render_metadata, dict):
                    render_metadata = {}
            except (TypeError, ValueError):
                render_metadata = {}
            duration_seconds = render_metadata.get("duration_seconds")
            result = {
                "job_id": video["job_id"], "brand": video["brand"],
                "region": video["region"], "topic": video["topic"],
                "topic_signature": _topic_signature(video["topic"]),
                "video_id": video["video_id"], "uploaded_at": video["uploaded_at"],
                "duration_seconds": duration_seconds,
                "duration_bucket": _duration_bucket(duration_seconds),
                "format": _render_format(render_metadata),
                "snapshot_count": len(snaps),
                "publication_age_bucket": "unknown",
                "measurement_status": "insufficient_snapshots",
                "analytics_status": video.get("analytics_status") or "not_collected",
                "engaged_views": video.get("analytics_engaged_views"),
                "engaged_view_share": video.get("analytics_engaged_view_share"),
                "retention_status": video.get("retention_status") or "not_collected",
                "average_view_duration_seconds": video.get("analytics_average_view_duration"),
                "average_view_percentage": video.get("analytics_average_view_percentage"),
                "estimated_minutes_watched": video.get("analytics_estimated_minutes_watched"),
                "analytics_collected_at": video.get("analytics_collected_at"),
            }
            try:
                retention_curve = json.loads(video.get("analytics_retention_json") or "[]")
                result["audience_retention_curve"] = (
                    retention_curve if isinstance(retention_curve, list) else []
                )
            except (TypeError, ValueError):
                result["audience_retention_curve"] = []
            result["retention_diagnostics"] = _retention_diagnostics(
                result["audience_retention_curve"]
            )
            if result["publication_age_bucket"] == "unknown" and result.get("analytics_collected_at"):
                result["publication_age_bucket"] = _publication_age_bucket(
                    video["uploaded_at"], result["analytics_collected_at"]
                )
                result["publication_age_hours_at_last_snapshot"] = _elapsed_hours(
                    video["uploaded_at"], result["analytics_collected_at"]
                )
            if isinstance(result["engaged_view_share"], (int, float)):
                brand_row["_engaged_view_share_samples"].append(
                    float(result["engaged_view_share"])
                )
            if isinstance(result["average_view_duration_seconds"], (int, float)):
                brand_row["_average_view_duration_samples"].append(
                    float(result["average_view_duration_seconds"])
                )
            if isinstance(result["average_view_percentage"], (int, float)):
                brand_row["_average_view_percentage_samples"].append(
                    float(result["average_view_percentage"])
                )
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
                result["publication_age_bucket"] = _publication_age_bucket(
                    video["uploaded_at"], last["collected_at"]
                )
                result["publication_age_hours_at_last_snapshot"] = _elapsed_hours(
                    video["uploaded_at"], last["collected_at"]
                )
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
                    if result["views_per_hour"] is not None:
                        brand_row["_views_per_hour_samples"].append(result["views_per_hour"])
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
                    if result["interactions_per_1000_view_delta"] is not None:
                        brand_row["_interaction_rate_samples"].append(
                            result["interactions_per_1000_view_delta"]
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

        # Compare retention metrics only inside tightly matched, sufficiently
        # populated cohorts. These observations are explanatory, never ranking
        # score inputs; sparse cohorts remain explicitly limited.
        analytics_groups = {}
        for video in video_results:
            if video.get("analytics_status") != "available":
                continue
            if not any(isinstance(video.get(field), (int, float)) for field in (
                "average_view_percentage", "average_view_duration_seconds",
                "engaged_view_share",
            )):
                continue
            key = (
                str(video.get("brand") or "unknown"),
                str(video.get("region") or "unknown").upper(),
                video.get("publication_age_bucket", "unknown"),
                video.get("duration_bucket", "unknown"),
                video.get("format", "unknown"),
                video.get("topic_signature", "unknown"),
            )
            group = analytics_groups.setdefault(key, {
                "brand": key[0], "region": key[1],
                "publication_age_bucket": key[2], "duration_bucket": key[3],
                "format": key[4], "topic_signature": key[5],
                "videos": [],
            })
            group["videos"].append(video)

        analytics_cohorts = []
        for group in analytics_groups.values():
            metric_fields = (
                "average_view_percentage",
                "average_view_duration_seconds",
                "engaged_view_share",
            )
            metric_samples = {}
            for field in metric_fields:
                values = [
                    float(video[field]) for video in group["videos"]
                    if isinstance(video.get(field), (int, float))
                    and math.isfinite(float(video[field]))
                ]
                metric_samples[field] = values
            cohort_size = len(group["videos"])
            cohort = {
                key: value for key, value in group.items() if key != "videos"
            }
            cohort["video_count"] = cohort_size
            cohort["metrics"] = {}
            cohort["evidence_status"] = "limited" if cohort_size < 3 else "observed"
            cohort["ranking_score_adjustment"] = 0
            cohort["usage"] = "descriptive_only_pending_held_out_validation"
            for field, values in metric_samples.items():
                cohort["metrics"][field] = {
                    "sample_count": len(values),
                    "median": round(statistics.median(values), 4)
                    if values else None,
                }
            for video in group["videos"]:
                comparisons = {}
                for field, values in metric_samples.items():
                    sample_count = len(values)
                    median = statistics.median(values) if values else None
                    observed = video.get(field)
                    comparisons[field] = {
                        "status": "comparable" if sample_count >= 3 else "insufficient_sample",
                        "sample_count": sample_count,
                        "cohort_median": round(median, 4) if median is not None else None,
                        "difference_from_median": (
                            round(float(observed) - median, 4)
                            if sample_count >= 3 and isinstance(observed, (int, float))
                            else None
                        ),
                    }
                video["analytics_cohort_comparison"] = comparisons
                percentage_comparison = comparisons["average_view_percentage"]
                if percentage_comparison["status"] == "comparable":
                    difference = percentage_comparison["difference_from_median"]
                    if difference < 0:
                        video.setdefault("analytics_observations", []).append({
                            "type": "below_matched_cohort_retention",
                            "basis": "observed_average_view_percentage_below_cohort_median",
                            "difference_percentage_points": round(difference, 2),
                            "action": "Review the opening hook and pacing against matched videos; test one controlled edit",
                            "ranking_score_adjustment": 0,
                        })
                    elif difference > 0:
                        video.setdefault("analytics_observations", []).append({
                            "type": "above_matched_cohort_retention",
                            "basis": "observed_average_view_percentage_above_cohort_median",
                            "difference_percentage_points": round(difference, 2),
                            "action": "Preserve the current pacing as a hypothesis and test one controlled variation",
                            "ranking_score_adjustment": 0,
                        })
            analytics_cohorts.append(cohort)

        analytics_cohorts.sort(key=lambda item: (
            item["brand"], item["region"], item["publication_age_bucket"],
            item["duration_bucket"], item["format"], item["topic_signature"],
        ))

        for item in by_brand.values():
            rate_samples = item.pop("_views_per_hour_samples")
            interaction_samples = item.pop("_interaction_rate_samples")
            duration_samples = item.pop("_average_view_duration_samples")
            percentage_samples = item.pop("_average_view_percentage_samples")
            engaged_share_samples = item.pop("_engaged_view_share_samples")
            item["rate_sample_count"] = len(rate_samples)
            item["median_views_per_hour"] = (
                round(statistics.median(rate_samples), 2) if rate_samples else None
            )
            item["interaction_rate_sample_count"] = len(interaction_samples)
            item["median_interactions_per_1000_view_delta"] = (
                round(statistics.median(interaction_samples), 2)
                if interaction_samples else None
            )
            item["performance_evidence_status"] = (
                "limited" if len(rate_samples) < 3 else "sample_available"
            )
            item["analytics_measured_videos"] = max(
                len(duration_samples), len(percentage_samples), len(engaged_share_samples)
            )
            item["median_engaged_view_share"] = (
                round(statistics.median(engaged_share_samples), 4)
                if engaged_share_samples else None
            )
            item["median_average_view_duration_seconds"] = (
                round(statistics.median(duration_samples), 2) if duration_samples else None
            )
            item["median_average_view_percentage"] = (
                round(statistics.median(percentage_samples), 2) if percentage_samples else None
            )
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

        # Comparable cohorts are descriptive only. Sparse or mismatched samples
        # never alter trend recommendation scores.
        cohort_groups = {}
        for video in video_results:
            if video.get("measurement_status") != "measured":
                continue
            rate = video.get("views_per_hour")
            if not isinstance(rate, (int, float)) or rate < 0:
                continue
            key = (
                str(video.get("brand") or "unknown"),
                str(video.get("region") or "unknown").upper(),
                video.get("publication_age_bucket", "unknown"),
                video.get("duration_bucket", "unknown"),
                video.get("format", "unknown"),
                video.get("topic_signature", "unknown"),
            )
            cohort = cohort_groups.setdefault(key, {
                "brand": key[0],
                "region": key[1],
                "publication_age_bucket": key[2],
                "duration_bucket": key[3],
                "format": key[4],
                "topic_signature": key[5],
                "_views_per_hour": [],
                "_interaction_rates": [],
            })
            cohort["_views_per_hour"].append(float(rate))
            interaction_rate = video.get("interactions_per_1000_view_delta")
            if isinstance(interaction_rate, (int, float)) and interaction_rate >= 0:
                cohort["_interaction_rates"].append(float(interaction_rate))

        cohorts = []
        for cohort in cohort_groups.values():
            rates = cohort.pop("_views_per_hour")
            interaction_rates = cohort.pop("_interaction_rates")
            count = len(rates)
            cohort.update({
                "sample_count": count,
                "median_views_per_hour": round(statistics.median(rates), 2),
                "interaction_rate_sample_count": len(interaction_rates),
                "median_interactions_per_1000_view_delta": (
                    round(statistics.median(interaction_rates), 2)
                    if interaction_rates else None
                ),
                "evidence_status": "limited" if count < 3 else "observed",
                "ranking_score_adjustment": 0,
                "usage": "display_only_pending_held_out_validation",
            })
            cohorts.append(cohort)
        cohorts.sort(
            key=lambda item: (
                item["brand"], item["region"], item["publication_age_bucket"],
                item["duration_bucket"], item["format"], item["topic_signature"]
            )
        )

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
            "cohorts": cohorts,
            "analytics_cohorts": analytics_cohorts,
            "analytics_cohort_method": "Brand + region + publication-age bucket + render-duration bucket + format + exact normalized topic-token signature; median comparisons require at least three measured videos and never change ranking scores.",
            "cohort_method": "Brand + region + exact normalized topic-token signature + publication-age-at-last-snapshot + duration bucket + format; descriptive only.",
            "financial": list(financial.values()),
            "limitations": [
                "View deltas are differences between stored snapshots, not real-time platform analytics.",
                "Views per hour is normalized between stored snapshots, not a platform-provided velocity metric.",
                "Interactions per 1000 view delta uses like and comment counter differences only; it is not audience-retention or satisfaction data.",
                "Negative view-counter differences are treated as resets or invalid measurements and excluded from aggregate growth; negative interaction deltas are omitted.",
                "Average view duration, average view percentage and audience retention are sourced only from stored YouTube Analytics API reports; missing or ineligible reports remain unavailable and are never inferred from Data API counters.",
                "Comparable cohorts use exact normalized topic-token signatures, region, age at the last stored snapshot, render duration and format; lexical signatures are not semantic topic classification.",
                "Cohorts with fewer than three measured videos are marked limited; no cohort metric changes recommendation ranking until held-out evaluation validates an adjustment.",
                "Format defaults to vertical_short_requested when the renderer does not return verifiable format metadata; this is a requested format, not proof of rendered dimensions.",
                "Recommendations are operational heuristics, not causal claims or forecasts.",
                "Financial totals include only recorded ledger entries.",
                "Financials are separated by brand and currency; no implicit foreign-exchange conversion is applied."
            ]
        }
