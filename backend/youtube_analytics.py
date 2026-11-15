"""Read-only YouTube Analytics API v2 collection for owned uploaded videos.

Requires a refresh token consented to youtube.readonly and yt-analytics.readonly.
No monetary metrics are requested or inferred.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import math
import os
import sqlite3

SOURCE = "YouTube Analytics API v2"
ANALYTICS_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"
YOUTUBE_READ_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
METRICS = (
    "views,engagedViews,estimatedMinutesWatched,averageViewDuration,"
    "averageViewPercentage,likes,comments,shares,subscribersGained"
)
NUMERIC_FIELDS = (
    "views", "engagedViews", "estimatedMinutesWatched", "averageViewDuration",
    "averageViewPercentage", "likes", "comments", "shares", "subscribersGained",
)


class YouTubeAnalyticsError(RuntimeError):
    pass


def build_analytics_service():
    refresh = os.getenv("YOUTUBE_REFRESH_TOKEN")
    client_id = os.getenv("YOUTUBE_CLIENT_ID")
    client_secret = os.getenv("YOUTUBE_CLIENT_SECRET")
    if not all((refresh, client_id, client_secret)):
        raise YouTubeAnalyticsError(
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
            scopes=[YOUTUBE_UPLOAD_SCOPE, YOUTUBE_READ_SCOPE, ANALYTICS_SCOPE],
        )
        credentials.refresh(Request())
        granted = getattr(credentials, "granted_scopes", None)
        if granted is not None and ANALYTICS_SCOPE not in granted:
            raise YouTubeAnalyticsError(
                "YouTube refresh token lacks yt-analytics.readonly; reauthorize the channel"
            )
        return build("youtubeAnalytics", "v2", credentials=credentials, cache_discovery=False)
    except YouTubeAnalyticsError:
        raise
    except Exception as exc:
        raise YouTubeAnalyticsError(
            "YouTube Analytics OAuth initialization failed: " + type(exc).__name__
        ) from exc


class YouTubeAnalyticsStore:
    def __init__(self, db_path="data/nexus.sqlite3"):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as connection:
            connection.executescript("""
            CREATE TABLE IF NOT EXISTS youtube_analytics_snapshots(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              video_id TEXT NOT NULL,
              start_date TEXT NOT NULL,
              end_date TEXT NOT NULL,
              views REAL, engaged_views REAL,
              estimated_minutes_watched REAL, average_view_duration REAL,
              average_view_percentage REAL, likes REAL, comments REAL,
              shares REAL, subscribers_gained REAL,
              source TEXT NOT NULL, collected_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_youtube_analytics_video
              ON youtube_analytics_snapshots(video_id,collected_at,id);
            CREATE TABLE IF NOT EXISTS youtube_analytics_lease(
              id INTEGER PRIMARY KEY CHECK(id=1), owner_id TEXT NOT NULL,
              token TEXT NOT NULL, lease_until REAL NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS youtube_analytics_collection_state(
              id INTEGER PRIMARY KEY CHECK(id=1), status TEXT NOT NULL,
              last_attempt_at TEXT, last_success_at TEXT, last_error TEXT,
              requested INTEGER NOT NULL DEFAULT 0, collected INTEGER NOT NULL DEFAULT 0,
              missing INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            """)

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

    def acquire_lease(self, owner_id, lease_seconds=300, now=None):
        import uuid
        now = float(now if now is not None else datetime.now(timezone.utc).timestamp())
        token = uuid.uuid4().hex
        with self.db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT owner_id,lease_until FROM youtube_analytics_lease WHERE id=1"
            ).fetchone()
            if row and row["lease_until"] > now:
                return None
            connection.execute("""
              INSERT INTO youtube_analytics_lease(id,owner_id,token,lease_until,updated_at)
              VALUES(1,?,?,?,?)
              ON CONFLICT(id) DO UPDATE SET owner_id=excluded.owner_id,
                token=excluded.token,lease_until=excluded.lease_until,updated_at=excluded.updated_at
            """, (owner_id, token, now + max(30, int(lease_seconds)),
                  datetime.fromtimestamp(now, timezone.utc).isoformat()))
        return token

    def renew_lease(self, owner_id, token, lease_seconds=300, now=None):
        """Renew a still-live analytics lease without allowing a stale owner to revive it."""
        now = float(now if now is not None else datetime.now(timezone.utc).timestamp())
        with self.db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            updated = connection.execute(
                """UPDATE youtube_analytics_lease SET lease_until=?,updated_at=?
                   WHERE id=1 AND owner_id=? AND token=? AND lease_until>?""",
                (now + max(30, int(lease_seconds)),
                 datetime.fromtimestamp(now, timezone.utc).isoformat(),
                 owner_id, token, now),
            )
            return updated.rowcount == 1

    def release_lease(self, owner_id, token):
        with self.db() as connection:
            connection.execute(
                "DELETE FROM youtube_analytics_lease WHERE id=1 AND owner_id=? AND token=?",
                (owner_id, token),
            )

    def record_collection(self, status, requested=0, collected=0, missing=0, error=None):
        now = datetime.now(timezone.utc).isoformat()
        with self.db() as connection:
            connection.execute("""
              INSERT INTO youtube_analytics_collection_state
                (id,status,last_attempt_at,last_success_at,last_error,requested,collected,
                 missing,source,updated_at)
              VALUES(1,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(id) DO UPDATE SET status=excluded.status,
                last_attempt_at=excluded.last_attempt_at,
                last_success_at=CASE WHEN excluded.status='succeeded'
                  THEN excluded.last_success_at
                  ELSE youtube_analytics_collection_state.last_success_at END,
                last_error=excluded.last_error,requested=excluded.requested,
                collected=excluded.collected,missing=excluded.missing,
                source=excluded.source,updated_at=excluded.updated_at
            """, (status, now, now if status == "succeeded" else None,
                  error, int(requested), int(collected), int(missing), SOURCE, now))

    def status(self, freshness_seconds=172800):
        now = datetime.now(timezone.utc)
        with self.db() as connection:
            row = connection.execute(
                "SELECT * FROM youtube_analytics_collection_state WHERE id=1"
            ).fetchone()
        result = dict(row) if row else {
            "status": "not_started", "last_attempt_at": None, "last_success_at": None,
            "last_error": None, "requested": 0, "collected": 0, "missing": 0,
            "source": SOURCE,
        }
        success = result.get("last_success_at")
        if success:
            try:
                age = (now - datetime.fromisoformat(success)).total_seconds()
                result["fresh"] = age <= max(0, int(freshness_seconds))
            except (TypeError, ValueError):
                result["fresh"] = False
        else:
            result["fresh"] = False
        result.update({
            "platform": "youtube_analytics",
            "scope_required": ANALYTICS_SCOPE,
            "available_metrics": list(NUMERIC_FIELDS),
            "unavailable_metrics": ["estimated_revenue", "ad_revenue"],
            "read_only": True,
        })
        return result

    def save_snapshot(self, video_id, start_date, end_date, values):
        if not isinstance(video_id, str) or not video_id.strip():
            raise YouTubeAnalyticsError("Analytics row has no video ID")
        if not isinstance(values, dict):
            raise YouTubeAnalyticsError("Analytics row values are malformed")
        normalized = {}
        for key in NUMERIC_FIELDS:
            value = values.get(key)
            if value is None:
                normalized[key] = None
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise YouTubeAnalyticsError("Analytics metric is not numeric: " + key)
            if not math.isfinite(float(value)) or float(value) < 0:
                raise YouTubeAnalyticsError("Analytics metric is outside the valid range: " + key)
            normalized[key] = float(value)
        now = datetime.now(timezone.utc).isoformat()
        with self.db() as connection:
            connection.execute("""
              INSERT INTO youtube_analytics_snapshots(
                video_id,start_date,end_date,views,engaged_views,estimated_minutes_watched,
                average_view_duration,average_view_percentage,likes,comments,shares,
                subscribers_gained,source,collected_at
              ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (video_id, start_date, end_date, normalized["views"],
                  normalized["engagedViews"] if "engagedViews" in normalized else normalized["engaged_views"],
                  normalized["estimatedMinutesWatched"] if "estimatedMinutesWatched" in normalized else normalized["estimated_minutes_watched"],
                  normalized["averageViewDuration"] if "averageViewDuration" in normalized else normalized["average_view_duration"],
                  normalized["averageViewPercentage"] if "averageViewPercentage" in normalized else normalized["average_view_percentage"],
                  normalized["likes"], normalized["comments"], normalized["shares"],
                  normalized["subscribersGained"] if "subscribersGained" in normalized else normalized["subscribers_gained"],
                  SOURCE, now))

    def due_video_ids(self, upload_store, limit=50, min_age_seconds=21600):
        limit = max(1, min(int(limit), 50))
        now = datetime.now(timezone.utc)
        uploads = upload_store.list_uploaded_video_ids(10000)
        eligible = [x for x in uploads
                    if x.get("status") == "uploaded" and x.get("video_id")]
        # Oldest uploads are considered first; recently refreshed videos are skipped.
        eligible.sort(key=lambda x: (x.get("uploaded_at") or x.get("updated_at") or "",
                                     x.get("video_id") or ""))
        ids = list(dict.fromkeys(x["video_id"] for x in eligible))
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        with self.db() as connection:
            rows = connection.execute(f"""
              SELECT video_id,MAX(collected_at) AS collected_at
              FROM youtube_analytics_snapshots WHERE video_id IN ({placeholders})
              GROUP BY video_id
            """, ids).fetchall()
        latest = {row["video_id"]: row["collected_at"] for row in rows}
        due = []
        for video_id in ids:
            collected_at = latest.get(video_id)
            if not collected_at:
                due.append(video_id)
            else:
                try:
                    age = (now - datetime.fromisoformat(collected_at)).total_seconds()
                except (TypeError, ValueError):
                    age = float("inf")
                if age >= max(0, int(min_age_seconds)):
                    due.append(video_id)
            if len(due) >= limit:
                break
        return due

    def recent_metrics(self, upload_store, limit=100):
        limit = max(1, min(int(limit), 200))
        uploads = upload_store.list_recent(200)
        eligible = {x["video_id"] for x in uploads
                    if x.get("status") == "uploaded" and x.get("video_id")}
        if not eligible:
            return []
        ids = list(eligible)[:limit]
        placeholders = ",".join("?" for _ in ids)
        with self.db() as connection:
            rows = connection.execute(f"""
              SELECT snapshot.* FROM youtube_analytics_snapshots snapshot
              JOIN (
                SELECT video_id,MAX(id) AS latest_id
                FROM youtube_analytics_snapshots WHERE video_id IN ({placeholders})
                GROUP BY video_id
              ) latest ON latest.latest_id=snapshot.id
              ORDER BY snapshot.collected_at DESC,snapshot.id DESC LIMIT ?
            """, (*ids, limit)).fetchall()
        return [dict(row) for row in rows]


class YouTubeAnalyticsCollector:
    def __init__(self, store, upload_store, service_factory=None):
        self.store = store
        self.upload_store = upload_store
        self.service_factory = service_factory or build_analytics_service

    @staticmethod
    def _date_window(today=None, days=28):
        today = today or datetime.now(timezone.utc).date()
        end_date = today - timedelta(days=2)
        start_date = end_date - timedelta(days=max(1, int(days)) - 1)
        return start_date.isoformat(), end_date.isoformat()

    @staticmethod
    def _parse_response(response, requested_ids):
        if not isinstance(response, dict):
            raise YouTubeAnalyticsError("YouTube Analytics response is malformed")
        headers = response.get("columnHeaders")
        rows = response.get("rows", [])
        if not isinstance(headers, list) or not isinstance(rows, list):
            raise YouTubeAnalyticsError("YouTube Analytics response omitted headers or rows")
        names = [item.get("name") for item in headers if isinstance(item, dict)]
        if len(names) != len(headers) or len(names) != len(set(names)) or "video" not in names:
            raise YouTubeAnalyticsError("YouTube Analytics response columns are invalid")
        required = {"video", *NUMERIC_FIELDS}
        if not required.issubset(set(names)):
            raise YouTubeAnalyticsError("YouTube Analytics response omitted requested metrics")
        parsed = []
        for row in rows:
            if not isinstance(row, list) or len(row) != len(names):
                raise YouTubeAnalyticsError("YouTube Analytics row shape is invalid")
            item = dict(zip(names, row))
            video_id = item.get("video")
            if video_id not in requested_ids:
                raise YouTubeAnalyticsError("YouTube Analytics returned an unrequested video ID")
            values = {key: item.get(key) for key in NUMERIC_FIELDS}
            parsed.append((video_id, values))
        if len({video_id for video_id, _ in parsed}) != len(parsed):
            raise YouTubeAnalyticsError("YouTube Analytics returned duplicate video rows")
        return parsed

    def refresh(self, limit=50, days=28, min_age_seconds=21600):
        video_ids = self.store.due_video_ids(
            self.upload_store, limit=limit, min_age_seconds=min_age_seconds
        )
        if not video_ids:
            return {"requested": 0, "collected": 0, "missing": [],
                    "source": SOURCE, "start_date": None, "end_date": None}
        start_date, end_date = self._date_window(days=days)
        service = self.service_factory()
        collected = []
        missing = set(video_ids)
        for offset in range(0, len(video_ids), 50):
            batch = video_ids[offset:offset + 50]
            response = service.reports().query(
                ids="channel==MINE",
                startDate=start_date,
                endDate=end_date,
                metrics=METRICS,
                dimensions="video",
                filters="video==" + ",".join(batch),
                maxResults=200,
            ).execute()
            parsed = self._parse_response(response, set(batch))
            for video_id, values in parsed:
                self.store.save_snapshot(video_id, start_date, end_date, values)
                collected.append(video_id)
                missing.discard(video_id)
        return {
            "requested": len(video_ids), "collected": len(collected),
            "missing": sorted(missing), "source": SOURCE,
            "start_date": start_date, "end_date": end_date,
        }
