"""TikTok-owned video counter snapshots via the official Display API.

Only IDs already confirmed by the creator's own publication records are queried.
This does not discover third-party videos or infer audience-retention metrics.
"""
import json
import os
import sqlite3
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlencode

API_URL = "https://open.tiktokapis.com/v2/video/query/"
FIELDS = "id,view_count,like_count,comment_count,share_count"


def _now():
    return datetime.now(timezone.utc)


def _stamp(value=None):
    return (value or _now()).astimezone(timezone.utc).isoformat()


class TikTokMetricsError(RuntimeError):
    pass


class TikTokMetricsStore:
    def __init__(self, db_path="data/nexus.sqlite3"):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS tiktok_video_metric_snapshots(
              id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
              video_id TEXT NOT NULL, view_count INTEGER, like_count INTEGER,
              comment_count INTEGER, share_count INTEGER, collected_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_tiktok_metric_video_time
              ON tiktok_video_metric_snapshots(video_id,collected_at DESC);
            CREATE TABLE IF NOT EXISTS tiktok_metrics_collection_state(
              id INTEGER PRIMARY KEY CHECK(id=1), status TEXT NOT NULL,
              last_attempt_at TEXT, last_success_at TEXT, last_error TEXT,
              requested INTEGER NOT NULL DEFAULT 0, collected INTEGER NOT NULL DEFAULT 0,
              missing INTEGER NOT NULL DEFAULT 0, source TEXT, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tiktok_metrics_collector_lease(
              id INTEGER PRIMARY KEY CHECK(id=1), owner_id TEXT NOT NULL,
              lease_token TEXT NOT NULL, expires_at TEXT NOT NULL
            );
            """)

    @contextmanager
    def db(self):
        c = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA busy_timeout=30000")
        try:
            yield c
            if c.in_transaction:
                c.commit()
        except Exception:
            if c.in_transaction:
                c.rollback()
            raise
        finally:
            c.close()

    def acquire_lease(self, owner_id, lease_seconds=300):
        if not isinstance(owner_id, str) or not owner_id.strip():
            raise ValueError("A valid TikTok metrics collector owner ID is required")
        now = _now()
        token = uuid.uuid4().hex
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT * FROM tiktok_metrics_collector_lease WHERE id=1").fetchone()
            if row and datetime.fromisoformat(row["expires_at"]) > now:
                return None
            c.execute("""
              INSERT INTO tiktok_metrics_collector_lease(id,owner_id,lease_token,expires_at)
              VALUES(1,?,?,?) ON CONFLICT(id) DO UPDATE SET
              owner_id=excluded.owner_id,lease_token=excluded.lease_token,
              expires_at=excluded.expires_at
            """, (owner_id, token, _stamp(now + timedelta(seconds=lease_seconds))))
        return token

    def release_lease(self, owner_id, lease_token):
        with self.db() as c:
            cur = c.execute(
                "DELETE FROM tiktok_metrics_collector_lease WHERE id=1 AND owner_id=? AND lease_token=?",
                (owner_id, lease_token),
            )
            return cur.rowcount == 1

    def record_collection(self, status, requested=0, collected=0, missing=0,
                          error=None, source="TikTok Display API v2"):
        if status not in {"running", "succeeded", "failed", "not_configured", "scope_missing"}:
            raise ValueError("Invalid TikTok metrics collection status")
        stamp = _stamp()
        with self.db() as c:
            c.execute("""
              INSERT INTO tiktok_metrics_collection_state
                (id,status,last_attempt_at,last_success_at,last_error,requested,
                 collected,missing,source,updated_at)
              VALUES(1,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(id) DO UPDATE SET status=excluded.status,
                last_attempt_at=excluded.last_attempt_at,
                last_success_at=CASE WHEN excluded.status='succeeded'
                  THEN excluded.last_attempt_at
                  ELSE tiktok_metrics_collection_state.last_success_at END,
                last_error=CASE WHEN excluded.status='succeeded' THEN NULL
                  ELSE excluded.last_error END,
                requested=excluded.requested,collected=excluded.collected,
                missing=excluded.missing,source=excluded.source,updated_at=excluded.updated_at
            """, (status, stamp, stamp if status == "succeeded" else None,
                  error, int(requested), int(collected), int(missing), source, stamp))

    def save_snapshot(self, job_id, video):
        video_id = video.get("id")
        if not isinstance(video_id, str) or not video_id.strip():
            raise TikTokMetricsError("TikTok metrics response omitted a video ID")
        values = {}
        for key in ("view_count", "like_count", "comment_count", "share_count"):
            value = video.get(key)
            if value is None:
                values[key] = None
            elif isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise TikTokMetricsError("TikTok returned an invalid " + key)
            else:
                values[key] = value
        with self.db() as c:
            c.execute("""
              INSERT INTO tiktok_video_metric_snapshots
                (job_id,video_id,view_count,like_count,comment_count,share_count,collected_at)
              VALUES(?,?,?,?,?,?,?)
            """, (job_id, video_id, values["view_count"], values["like_count"],
                  values["comment_count"], values["share_count"], _stamp()))

    def latest_snapshot_times(self):
        with self.db() as c:
            rows = c.execute("""
              SELECT video_id,MAX(collected_at) AS collected_at
              FROM tiktok_video_metric_snapshots GROUP BY video_id
            """).fetchall()
        return {row["video_id"]: row["collected_at"] for row in rows}

    def status(self, publication_store, freshness_seconds=43200):
        with self.db() as c:
            row = c.execute(
                "SELECT * FROM tiktok_metrics_collection_state WHERE id=1"
            ).fetchone()
            count = c.execute("""
              SELECT COUNT(DISTINCT video_id) FROM tiktok_video_metric_snapshots
            """).fetchone()[0]
        records = publication_store.list_recent(200)
        eligible = [x for x in records if x.get("status") == "publish_complete" and x.get("video_id")]
        latest = self.latest_snapshot_times()
        cutoff = _stamp(_now() - timedelta(seconds=max(0, freshness_seconds)))
        with_snapshot = sum(1 for x in eligible if x["video_id"] in latest)
        stale = sum(1 for x in eligible if x["video_id"] in latest and latest[x["video_id"]] < cutoff)
        state = dict(row) if row else {}
        return {
            "platform": "tiktok",
            "status": state.get("status", "not_started"),
            "last_attempt_at": state.get("last_attempt_at"),
            "last_success_at": state.get("last_success_at"),
            "last_error": state.get("last_error"),
            "last_batch": {"requested": state.get("requested", 0),
                           "collected": state.get("collected", 0),
                           "missing": state.get("missing", 0)},
            "source": state.get("source"),
            "available_metrics": ["view_count", "like_count", "comment_count", "share_count"],
            "unavailable_metrics": ["audience_retention", "watch_time", "estimated_revenue"],
            "coverage": {"published_videos": len(eligible), "with_snapshot": with_snapshot,
                         "without_snapshot": len(eligible)-with_snapshot,
                         "stale_snapshots": stale},
            "read_only": True,
        }


class TikTokMetricsCollector:
    def __init__(self, store, publication_store, token_provider, transport=None):
        self.store = store
        self.publication_store = publication_store
        self.token_provider = token_provider
        self.transport = transport or self._request

    @staticmethod
    def _request(url, headers, body, timeout):
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(4000)
        except (urllib.error.URLError, TimeoutError) as exc:
            raise TikTokMetricsError("TikTok metrics network request failed: " + type(exc).__name__) from exc

    def refresh_due_metrics(self, limit=20, min_age_seconds=21600):
        limit = max(1, min(int(limit), 20))
        min_age_seconds = max(0, int(min_age_seconds))
        records = self.publication_store.list_recent(200)
        eligible = [x for x in records if x.get("status") == "publish_complete" and x.get("video_id")]
        latest = self.store.latest_snapshot_times()
        cutoff = _stamp(_now() - timedelta(seconds=min_age_seconds))
        due = [x for x in eligible if x["video_id"] not in latest or latest[x["video_id"]] < cutoff][:limit]
        if not due:
            return {"requested": 0, "collected": 0, "missing": [], "source": "TikTok Display API v2"}
        try:
            token = self.token_provider(required_scope="video.list")
        except Exception as exc:
            raise TikTokMetricsError("TikTok video.list authorization is unavailable: " + type(exc).__name__) from exc
        if not token:
            raise TikTokMetricsError("TikTok account is not connected for video.list analytics")
        ids = [x["video_id"] for x in due]
        url = API_URL + "?" + urlencode({"fields": FIELDS})
        body = json.dumps({"filters": {"video_ids": ids}}).encode("utf-8")
        status, raw = self.transport(url, {
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }, body, 30)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise TikTokMetricsError("TikTok metrics returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise TikTokMetricsError("TikTok metrics returned an unexpected response shape")
        error = data.get("error")
        if status < 200 or status >= 300 or not isinstance(error, dict) or error.get("code") not in ("ok", 0):
            code = error.get("code") if isinstance(error, dict) else "invalid_error_envelope"
            raise TikTokMetricsError("TikTok metrics request failed: " + str(code or "http_" + str(status)))
        response_data = data.get("data")
        if not isinstance(response_data, dict):
            raise TikTokMetricsError("TikTok metrics response omitted its data object")
        videos = response_data.get("videos")
        if not isinstance(videos, list):
            raise TikTokMetricsError("TikTok metrics response omitted data.videos")
        jobs = {x["video_id"]: x["job_id"] for x in due}
        collected_ids = set()
        for video in videos:
            if not isinstance(video, dict) or video.get("id") not in jobs:
                raise TikTokMetricsError("TikTok metrics returned an unrequested video")
            self.store.save_snapshot(jobs[video["id"]], video)
            collected_ids.add(video["id"])
        missing = [video_id for video_id in ids if video_id not in collected_ids]
        return {"requested": len(ids), "collected": len(collected_ids),
                "missing": missing, "source": "TikTok Display API v2"}
