"""Evidence-backed YouTube Analytics API collection.

Stores channel-authorized watch-time and audience-retention reports separately
from public YouTube Data API counter snapshots.
"""
import json
import math
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


def _now():
    return datetime.now(timezone.utc).isoformat()


def _as_number(value, allow_negative=False):
    try:
        number = float(value)
        if not math.isfinite(number):
            return None
        return number if allow_negative or number >= 0 else None
    except (TypeError, ValueError):
        return None


class YouTubeAnalyticsStore:
    def __init__(self, db_path="data/nexus.sqlite3"):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as connection:
            connection.executescript("""
            CREATE TABLE IF NOT EXISTS youtube_analytics_snapshots(
              video_id TEXT PRIMARY KEY,
              start_date TEXT NOT NULL,
              end_date TEXT NOT NULL,
              views REAL,
              estimated_minutes_watched REAL,
              average_view_duration REAL,
              average_view_percentage REAL,
              retention_json TEXT NOT NULL DEFAULT '[]',
              analytics_status TEXT NOT NULL,
              retention_status TEXT NOT NULL,
              retention_error TEXT,
              collected_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_youtube_analytics_collected
              ON youtube_analytics_snapshots(collected_at);
            CREATE TABLE IF NOT EXISTS youtube_analytics_collector_lease(
              id INTEGER PRIMARY KEY CHECK(id=1),
              owner_id TEXT NOT NULL,
              lease_until REAL NOT NULL,
              updated_at TEXT NOT NULL
            );
            """)
            columns = {
                row["name"] for row in connection.execute(
                    "PRAGMA table_info(youtube_analytics_snapshots)"
                ).fetchall()
            }
            if "engaged_views" not in columns:
                connection.execute(
                    "ALTER TABLE youtube_analytics_snapshots ADD COLUMN engaged_views REAL"
                )
            if "engaged_view_share" not in columns:
                connection.execute(
                    "ALTER TABLE youtube_analytics_snapshots ADD COLUMN engaged_view_share REAL"
                )

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def due_video_ids(self, limit=20, min_age_seconds=86400):
        cutoff = datetime.now(timezone.utc).timestamp() - max(300, int(min_age_seconds))
        with self.db() as connection:
            rows = connection.execute("""
                SELECT u.video_id
                FROM youtube_uploads u
                LEFT JOIN youtube_analytics_snapshots a ON a.video_id=u.video_id
                WHERE u.status='uploaded' AND u.video_id IS NOT NULL
                  AND (a.video_id IS NULL OR
                       julianday(a.collected_at) < julianday(?))
                ORDER BY COALESCE(u.uploaded_at,u.updated_at),u.video_id
                LIMIT ?
            """, (datetime.fromtimestamp(cutoff, timezone.utc).isoformat(),
                  max(1, min(50, int(limit))))).fetchall()
        return [row["video_id"] for row in rows]

    def upload_date(self, video_id):
        with self.db() as connection:
            row = connection.execute(
                "SELECT uploaded_at FROM youtube_uploads WHERE video_id=? AND status='uploaded'",
                (video_id,),
            ).fetchone()
        return row["uploaded_at"] if row else None

    def save(self, video_id, start_date, end_date, metrics, retention,
             analytics_status="available", retention_status="available",
             retention_error=None):
        values = {
            "views": _as_number(metrics.get("views")),
            "engaged_views": _as_number(metrics.get("engagedViews")),
            "estimated_minutes_watched": _as_number(metrics.get("estimatedMinutesWatched")),
            "average_view_duration": _as_number(metrics.get("averageViewDuration")),
            "average_view_percentage": _as_number(metrics.get("averageViewPercentage")),
        }
        values["engaged_view_share"] = (
            values["engaged_views"] / values["views"]
            if values["engaged_views"] is not None
            and values["views"] is not None and values["views"] > 0
            else None
        )
        safe_curve = []
        for point in retention if isinstance(retention, list) else []:
            if not isinstance(point, dict):
                continue
            ratio = _as_number(point.get("elapsedVideoTimeRatio"))
            audience = _as_number(point.get("audienceWatchRatio"))
            relative = _as_number(
                point.get("relativeRetentionPerformance"), allow_negative=True
            )
            if ratio is None or audience is None:
                continue
            safe_curve.append({
                "elapsed_video_time_ratio": ratio,
                "audience_watch_ratio": audience,
                "relative_retention_performance": relative,
            })
        with self.db() as connection:
            connection.execute("""
                INSERT INTO youtube_analytics_snapshots(
                  video_id,start_date,end_date,views,engaged_views,engaged_view_share,
                  estimated_minutes_watched,average_view_duration,average_view_percentage,
                  retention_json,analytics_status,retention_status,retention_error,collected_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(video_id) DO UPDATE SET
                  start_date=excluded.start_date,end_date=excluded.end_date,
                  views=excluded.views,
                  engaged_views=excluded.engaged_views,
                  engaged_view_share=excluded.engaged_view_share,
                  estimated_minutes_watched=excluded.estimated_minutes_watched,
                  average_view_duration=excluded.average_view_duration,
                  average_view_percentage=excluded.average_view_percentage,
                  retention_json=excluded.retention_json,
                  analytics_status=excluded.analytics_status,
                  retention_status=excluded.retention_status,
                  retention_error=excluded.retention_error,
                  collected_at=excluded.collected_at
            """, (
                video_id, start_date, end_date, values["views"],
                values["engaged_views"], values["engaged_view_share"],
                values["estimated_minutes_watched"], values["average_view_duration"],
                values["average_view_percentage"], json.dumps(safe_curve, separators=(",", ":")),
                analytics_status, retention_status, retention_error, _now(),
            ))

    def get(self, video_id):
        with self.db() as connection:
            row = connection.execute(
                "SELECT * FROM youtube_analytics_snapshots WHERE video_id=?",
                (video_id,),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        try:
            result["retention_curve"] = json.loads(result.pop("retention_json") or "[]")
        except (TypeError, ValueError):
            result["retention_curve"] = []
        return result

    def acquire_lease(self, owner_id, lease_seconds=300):
        now = datetime.now(timezone.utc).timestamp()
        with self.db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT owner_id,lease_until FROM youtube_analytics_collector_lease WHERE id=1"
            ).fetchone()
            if row and row["lease_until"] > now and row["owner_id"] != owner_id:
                return None
            connection.execute("""
                INSERT INTO youtube_analytics_collector_lease(id,owner_id,lease_until,updated_at)
                VALUES(1,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                  owner_id=excluded.owner_id,lease_until=excluded.lease_until,
                  updated_at=excluded.updated_at
            """, (owner_id, now + max(30, int(lease_seconds)), _now()))
        return owner_id

    def release_lease(self, owner_id):
        with self.db() as connection:
            connection.execute(
                "DELETE FROM youtube_analytics_collector_lease WHERE id=1 AND owner_id=?",
                (owner_id,),
            )


class YouTubeAnalyticsCollector:
    def __init__(self, store, service=None, today=None):
        self.store = store
        self.service = service
        self.today = today or date.today

    def _service(self):
        if self.service is not None:
            return self.service
        refresh = os.getenv("YOUTUBE_REFRESH_TOKEN")
        client_id = os.getenv("YOUTUBE_CLIENT_ID")
        client_secret = os.getenv("YOUTUBE_CLIENT_SECRET")
        if not all((refresh, client_id, client_secret)):
            raise RuntimeError(
                "YOUTUBE_REFRESH_TOKEN, YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET are required"
            )
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build
            credentials = Credentials(
                token=None, refresh_token=refresh,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=client_id, client_secret=client_secret,
                scopes=["https://www.googleapis.com/auth/youtube.readonly"],
            )
            credentials.refresh(Request())
            return build("youtubeAnalytics", "v2", credentials=credentials,
                         cache_discovery=False)
        except Exception as exc:
            raise RuntimeError("YouTube Analytics OAuth initialization failed: "
                               + type(exc).__name__) from exc

    @staticmethod
    def _row_map(response):
        headers = [item.get("name") for item in response.get("columnHeaders", [])]
        rows = response.get("rows") or []
        return dict(zip(headers, rows[0])) if rows else {}

    def collect_video(self, video_id, start_date=None, end_date=None):
        if not isinstance(video_id, str) or not video_id.strip() or len(video_id) > 128:
            raise ValueError("A valid YouTube video ID is required")
        end = end_date or (self.today() - timedelta(days=2))
        # Explicit report ranges do not need local publication metadata.
        uploaded_at = self.store.upload_date(video_id) if start_date is None else None
        if start_date:
            start = start_date
        elif uploaded_at:
            try:
                uploaded = datetime.fromisoformat(str(uploaded_at).replace("Z", "+00:00")).date()
                start = max(uploaded, end - timedelta(days=89))
            except (TypeError, ValueError):
                start = end - timedelta(days=89)
        else:
            start = end - timedelta(days=89)
        if isinstance(start, str):
            start = date.fromisoformat(start)
        if isinstance(end, str):
            end = date.fromisoformat(end)
        if start > end:
            if start_date is not None or end_date is not None:
                raise ValueError("Analytics start date must not be after end date")
            # YouTube Analytics reporting lags recent uploads. Do not query an
            # invalid date range or label the absence of a report as zero views.
            self.store.save(
                video_id, end.isoformat(), end.isoformat(), {}, [],
                analytics_status="pending_availability",
                retention_status="pending_availability",
            )
            return {
                "video_id": video_id,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "analytics_status": "pending_availability",
                "retention_status": "pending_availability",
                "metrics": {
                    "views": None, "engaged_views": None, "engaged_view_share": None,
                    "estimated_minutes_watched": None,
                    "average_view_duration_seconds": None,
                    "average_view_percentage": None,
                },
                "retention_points": 0,
                "source": "YouTube Analytics API v2",
                "live_connectivity_verified": False,
            }
        service = self._service()
        report = service.reports().query(
            ids="channel==MINE",
            startDate=start.isoformat(),
            endDate=end.isoformat(),
            metrics="views,engagedViews,estimatedMinutesWatched,averageViewDuration,averageViewPercentage",
            # The basic user-activity report uses the video filter, not a video
            # dimension; it returns one metric row for the selected video.
            filters="video==" + video_id,
            maxResults=1,
        ).execute()
        metrics = self._row_map(report)
        retention_status = "unavailable"
        retention_error = None
        retention = []
        try:
            retention_report = service.reports().query(
                ids="channel==MINE",
                startDate=start.isoformat(),
                endDate=end.isoformat(),
                metrics="audienceWatchRatio,relativeRetentionPerformance",
                dimensions="elapsedVideoTimeRatio",
                filters="video==" + video_id,
                maxResults=200,
            ).execute()
            headers = [item.get("name") for item in retention_report.get("columnHeaders", [])]
            retention = [dict(zip(headers, row))
                         for row in retention_report.get("rows", [])]
            retention_status = "available" if retention else "no_data"
        except Exception as exc:
            # Keep watch-time metrics usable when a video is not eligible for
            # audience-retention reporting or the API denies that report.
            retention_error = type(exc).__name__
        analytics_status = "available" if metrics else "no_data"
        self.store.save(
            video_id, start.isoformat(), end.isoformat(), metrics, retention,
            analytics_status, retention_status, retention_error,
        )
        return {
            "video_id": video_id,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "analytics_status": analytics_status,
            "retention_status": retention_status,
            "metrics": {
                "views": metrics.get("views"),
                "engaged_views": metrics.get("engagedViews"),
                "engaged_view_share": (
                    _as_number(metrics.get("engagedViews")) / _as_number(metrics.get("views"))
                    if _as_number(metrics.get("engagedViews")) is not None
                    and _as_number(metrics.get("views")) not in (None, 0)
                    else None
                ),
                "estimated_minutes_watched": metrics.get("estimatedMinutesWatched"),
                "average_view_duration_seconds": metrics.get("averageViewDuration"),
                "average_view_percentage": metrics.get("averageViewPercentage"),
            },
            "retention_points": len(retention),
            "source": "YouTube Analytics API v2",
            "live_connectivity_verified": True,
        }

    def refresh_due_metrics(self, limit=20, min_age_seconds=86400):
        video_ids = self.store.due_video_ids(limit, min_age_seconds)
        results = []
        failures = []
        for video_id in video_ids:
            try:
                results.append(self.collect_video(video_id))
            except Exception as exc:
                failures.append({"video_id": video_id, "error": type(exc).__name__})
        return {
            "requested": len(video_ids),
            "collected": len(results),
            "failed": failures,
            "results": results,
            "source": "YouTube Analytics API v2",
        }
