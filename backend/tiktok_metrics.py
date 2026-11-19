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


def _lease_duration_seconds(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > 3600:
        raise ValueError("TikTok metrics lease duration must be an integer from 1 to 3600 seconds")
    return max(30, value)


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
            CREATE INDEX IF NOT EXISTS idx_tiktok_metric_video_time_id
              ON tiktok_video_metric_snapshots(video_id,collected_at DESC,id DESC);
            CREATE INDEX IF NOT EXISTS idx_tiktok_metric_time
              ON tiktok_video_metric_snapshots(collected_at DESC,id DESC);
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
            CREATE TABLE IF NOT EXISTS tiktok_metrics_missing_retry(
              video_id TEXT PRIMARY KEY, attempts INTEGER NOT NULL DEFAULT 0,
              next_retry_at TEXT NOT NULL, last_missing_at TEXT NOT NULL
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

    def assert_lease(self, owner_id, lease_token):
        with self.db() as c:
            self._assert_lease(c, owner_id, lease_token)

    def acquire_lease(self, owner_id, lease_seconds=300, now=None):
        if not isinstance(owner_id, str) or not owner_id.strip():
            raise ValueError("A valid TikTok metrics collector owner ID is required")
        now = now or _now()
        if isinstance(now, (int, float)):
            now = datetime.fromtimestamp(float(now), timezone.utc)
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
            """, (owner_id, token, _stamp(now + timedelta(seconds=_lease_duration_seconds(lease_seconds)))))
        return token

    def renew_lease(self, owner_id, lease_token, lease_seconds=300, now=None):
        now = now or _now()
        if isinstance(now, (int, float)):
            now = datetime.fromtimestamp(float(now), timezone.utc)
        stamp = _stamp(now)
        expires = _stamp(now + timedelta(seconds=_lease_duration_seconds(lease_seconds)))
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            cur = c.execute(
                """UPDATE tiktok_metrics_collector_lease SET expires_at=?
                   WHERE id=1 AND owner_id=? AND lease_token=? AND expires_at>?""",
                (expires, owner_id, lease_token, stamp),
            )
            return cur.rowcount == 1

    def release_lease(self, owner_id, lease_token):
        with self.db() as c:
            cur = c.execute(
                "DELETE FROM tiktok_metrics_collector_lease WHERE id=1 AND owner_id=? AND lease_token=?",
                (owner_id, lease_token),
            )
            return cur.rowcount == 1

    @staticmethod
    def _assert_lease(c, owner_id, lease_token):
        if owner_id is None and lease_token is None:
            return
        if not owner_id or not lease_token:
            raise ValueError("Both TikTok metrics lease owner and token are required")
        lease = c.execute(
            "SELECT owner_id,lease_token,expires_at FROM tiktok_metrics_collector_lease WHERE id=1"
        ).fetchone()
        if (
            lease is None or lease["owner_id"] != owner_id
            or lease["lease_token"] != lease_token
            or datetime.fromisoformat(lease["expires_at"]) <= _now()
        ):
            raise RuntimeError("TikTok metrics lease lost; stale write rejected")

    def record_collection(self, status, requested=0, collected=0, missing=0,
                          error=None, source="TikTok Display API v2",
                          lease_owner=None, lease_token=None):
        if status not in {"running", "succeeded", "failed", "not_configured", "scope_missing"}:
            raise ValueError("Invalid TikTok metrics collection status")
        stamp = _stamp()
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            self._assert_lease(c, lease_owner, lease_token)
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

    def save_snapshot(self, job_id, video, lease_owner=None, lease_token=None):
        self.save_snapshots(
            [(job_id, video)], lease_owner=lease_owner, lease_token=lease_token
        )

    def save_snapshots(self, items, lease_owner=None, lease_token=None,
                       missing_video_ids=None, retry_seconds=21600, now=None):
        if not isinstance(items, (list, tuple)):
            raise TikTokMetricsError("TikTok metrics batch must be a list")
        normalized, seen = [], set()
        for item in items:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                raise TikTokMetricsError("TikTok metrics batch item is malformed")
            job_id, video = item
            if not isinstance(job_id, str) or not job_id.strip() or len(job_id) > 128:
                raise TikTokMetricsError("TikTok metrics job ID is invalid")
            if not isinstance(video, dict):
                raise TikTokMetricsError("TikTok metrics video record is malformed")
            video_id = video.get("id")
            if (
                not isinstance(video_id, str) or not video_id.strip()
                or len(video_id) > 256 or any(ord(char) < 32 for char in video_id)
            ):
                raise TikTokMetricsError("TikTok metrics response omitted a valid video ID")
            if video_id in seen:
                raise TikTokMetricsError("TikTok metrics response contained duplicate video IDs")
            seen.add(video_id)
            values = {}
            for key in ("view_count", "like_count", "comment_count", "share_count"):
                value = video.get(key)
                if value is None:
                    values[key] = None
                elif (
                    isinstance(value, bool) or not isinstance(value, int)
                    or value < 0 or value > 9223372036854775807
                ):
                    raise TikTokMetricsError("TikTok returned an invalid " + key)
                else:
                    values[key] = value
            normalized.append((job_id, video_id, values))
        if isinstance(retry_seconds, bool) or not isinstance(retry_seconds, int) or retry_seconds < 1:
            raise TikTokMetricsError("TikTok missing-video retry interval is invalid")
        if missing_video_ids is None:
            missing_video_ids = []
        if not isinstance(missing_video_ids, (list, tuple, set)):
            raise TikTokMetricsError("TikTok missing-video IDs must be a collection")
        missing, missing_seen = [], set()
        for video_id in missing_video_ids:
            if (not isinstance(video_id, str) or not video_id.strip()
                    or len(video_id) > 256 or any(ord(char) < 32 for char in video_id)):
                raise TikTokMetricsError("TikTok missing-video ID is invalid")
            if video_id in seen:
                raise TikTokMetricsError("TikTok video cannot be both collected and missing")
            if video_id not in missing_seen:
                missing.append(video_id)
                missing_seen.add(video_id)
        if not normalized and not missing:
            return
        current = now or _now()
        if isinstance(current, (int, float)):
            current = datetime.fromtimestamp(float(current), timezone.utc)
        stamp = _stamp(current)
        collected_at = _stamp()
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            self._assert_lease(c, lease_owner, lease_token)
            if normalized:
                c.executemany("""
                  INSERT INTO tiktok_video_metric_snapshots
                    (job_id,video_id,view_count,like_count,comment_count,share_count,collected_at)
                  VALUES(?,?,?,?,?,?,?)
                """, [
                    (job_id, video_id, values["view_count"], values["like_count"],
                     values["comment_count"], values["share_count"], collected_at)
                    for job_id, video_id, values in normalized
                ])
                c.executemany(
                    "DELETE FROM tiktok_metrics_missing_retry WHERE video_id=?",
                    [(video_id,) for _, video_id, _ in normalized],
                )
            for video_id in missing:
                row = c.execute(
                    "SELECT attempts FROM tiktok_metrics_missing_retry WHERE video_id=?",
                    (video_id,),
                ).fetchone()
                attempts = int(row["attempts"]) + 1 if row else 1
                delay = min(7 * 86400, retry_seconds * (2 ** min(attempts - 1, 5)))
                retry_at = _stamp(current + timedelta(seconds=delay))
                c.execute("""
                    INSERT INTO tiktok_metrics_missing_retry
                      (video_id,attempts,next_retry_at,last_missing_at)
                    VALUES(?,?,?,?)
                    ON CONFLICT(video_id) DO UPDATE SET
                      attempts=excluded.attempts,
                      next_retry_at=excluded.next_retry_at,
                      last_missing_at=excluded.last_missing_at
                """, (video_id, attempts, retry_at, stamp))

    def deferred_video_ids(self, now=None):
        """Return provider-missing videos still inside their retry backoff."""
        stamp = _stamp(now)
        with self.db() as c:
            rows = c.execute(
                "SELECT video_id FROM tiktok_metrics_missing_retry WHERE next_retry_at>?",
                (stamp,),
            ).fetchall()
        return {row["video_id"] for row in rows}

    def record_missing_video_ids(self, video_ids, retry_seconds=21600,
                                 lease_owner=None, lease_token=None, now=None):
        """Back off missing provider results so they cannot starve older videos."""
        if isinstance(retry_seconds, bool) or not isinstance(retry_seconds, int) or retry_seconds < 1:
            raise TikTokMetricsError("TikTok missing-video retry interval is invalid")
        if not isinstance(video_ids, (list, tuple, set)):
            raise TikTokMetricsError("TikTok missing-video IDs must be a collection")
        normalized = []
        for video_id in video_ids:
            if (not isinstance(video_id, str) or not video_id.strip()
                    or len(video_id) > 256 or any(ord(char) < 32 for char in video_id)):
                raise TikTokMetricsError("TikTok missing-video ID is invalid")
            if video_id not in normalized:
                normalized.append(video_id)
        if not normalized:
            return
        current = now or _now()
        if isinstance(current, (int, float)):
            current = datetime.fromtimestamp(float(current), timezone.utc)
        stamp = _stamp(current)
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            self._assert_lease(c, lease_owner, lease_token)
            for video_id in normalized:
                row = c.execute(
                    "SELECT attempts FROM tiktok_metrics_missing_retry WHERE video_id=?",
                    (video_id,),
                ).fetchone()
                attempts = int(row["attempts"]) + 1 if row else 1
                delay = min(7 * 86400, retry_seconds * (2 ** min(attempts - 1, 5)))
                retry_at = _stamp(current + timedelta(seconds=delay))
                c.execute("""
                    INSERT INTO tiktok_metrics_missing_retry
                      (video_id,attempts,next_retry_at,last_missing_at)
                    VALUES(?,?,?,?)
                    ON CONFLICT(video_id) DO UPDATE SET
                      attempts=excluded.attempts,
                      next_retry_at=excluded.next_retry_at,
                      last_missing_at=excluded.last_missing_at
                """, (video_id, attempts, retry_at, stamp))

    def due_videos(self, limit=20, min_age_seconds=21600, now=None):
        """Select a bounded set of stale published videos in SQLite."""
        limit = max(1, min(int(limit), 20))
        min_age_seconds = max(0, int(min_age_seconds))
        current = now or _now()
        if isinstance(current, (int, float)):
            current = datetime.fromtimestamp(float(current), timezone.utc)
        stamp = _stamp(current)
        cutoff = _stamp(current - timedelta(seconds=min_age_seconds))
        with self.db() as c:
            rows = c.execute("""
              SELECT p.job_id,p.video_id
              FROM tiktok_publications AS p
              LEFT JOIN tiktok_metrics_missing_retry AS r ON r.video_id=p.video_id
              WHERE p.status='publish_complete' AND p.video_id IS NOT NULL
                AND NOT EXISTS (
                  SELECT 1 FROM tiktok_publications AS newer
                  WHERE newer.status='publish_complete'
                    AND newer.video_id=p.video_id
                    AND (newer.updated_at>p.updated_at
                         OR (newer.updated_at=p.updated_at AND newer.job_id>p.job_id))
                )
                AND COALESCE((
                  SELECT s.collected_at
                  FROM tiktok_video_metric_snapshots AS s
                  WHERE s.video_id=p.video_id
                  ORDER BY s.collected_at DESC,s.id DESC
                  LIMIT 1
                ),'')<?
                AND (r.next_retry_at IS NULL OR r.next_retry_at<=?)
              ORDER BY p.updated_at DESC,p.job_id DESC
              LIMIT ?
            """, (cutoff, stamp, limit)).fetchall()
        return [dict(row) for row in rows]

    def latest_snapshot_times(self):
        with self.db() as c:
            rows = c.execute("""
              SELECT video_id,MAX(collected_at) AS collected_at
              FROM tiktok_video_metric_snapshots GROUP BY video_id
            """).fetchall()
        return {row["video_id"]: row["collected_at"] for row in rows}

    def history(self, publication_store, video_id=None, limit=100, since=None, offset=0, before_collected_at=None, before_id=None):
        limit=max(1,min(int(limit),500))
        offset=max(0,min(int(offset),10000000))
        clauses=["p.status='publish_complete'","p.video_id IS NOT NULL"]
        params=[]
        if video_id:
            clauses.append("p.video_id=?")
            params.append(video_id)
        if since:
            clauses.append("s.collected_at>=?")
            params.append(since)
        if before_collected_at is not None and before_id is not None:
            clauses.append("(s.collected_at<? OR (s.collected_at=? AND s.id<?))")
            params.extend((before_collected_at,before_collected_at,int(before_id)))
        where=" AND ".join(clauses)
        with self.db() as c:
            rows=c.execute(f"""
              SELECT DISTINCT s.*,p.status AS publication_status,
                     COALESCE(p.privacy_level,'SELF_ONLY') AS privacy_level
              FROM tiktok_video_metric_snapshots s
              JOIN tiktok_publications p ON p.video_id=s.video_id
              WHERE {where}
              ORDER BY s.collected_at DESC,s.id DESC LIMIT ? OFFSET ?
            """,(*params,limit,offset)).fetchall()
        return [dict(row) for row in rows]

    def recent_metrics(self, publication_store, limit=100):
        limit = max(1, min(int(limit), 200))
        eligible = publication_store.list_metrics_eligible(limit=limit)
        by_video = {x["video_id"]: x for x in eligible}
        if not by_video:
            return []
        ids = list(by_video)[:limit]
        placeholders = ",".join("?" for _ in ids)
        with self.db() as c:
            rows = c.execute(f"""
              SELECT s.* FROM tiktok_video_metric_snapshots s
              JOIN (
                SELECT video_id,MAX(id) AS latest_id
                FROM tiktok_video_metric_snapshots
                WHERE video_id IN ({placeholders})
                GROUP BY video_id
              ) latest ON latest.latest_id=s.id
              ORDER BY s.collected_at DESC,s.id DESC LIMIT ?
            """, (*ids, limit)).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            publication = by_video.get(item["video_id"], {})
            item["publication_status"] = publication.get("status")
            item["privacy_level"] = publication.get("privacy_level") or "SELF_ONLY"
            items.append(item)
        return items

    def status(self, publication_store, freshness_seconds=43200):
        # Aggregate coverage in SQLite instead of materializing every published
        # identity and every snapshot timestamp in Python. Both stores share the
        # same database file; keep the join and counts in one read transaction.
        cutoff = _stamp(_now() - timedelta(seconds=max(0, freshness_seconds)))
        with self.db() as c:
            row = c.execute(
                "SELECT * FROM tiktok_metrics_collection_state WHERE id=1"
            ).fetchone()
            coverage = c.execute("""
              WITH eligible AS (
                SELECT DISTINCT video_id
                FROM tiktok_publications
                WHERE status='publish_complete' AND video_id IS NOT NULL
              ),
              latest AS (
                SELECT s.video_id,MAX(s.collected_at) AS collected_at
                FROM tiktok_video_metric_snapshots AS s
                JOIN eligible AS e ON e.video_id=s.video_id
                GROUP BY s.video_id
              )
              SELECT COUNT(*) AS published_videos,
                     COUNT(latest.video_id) AS with_snapshot,
                     SUM(CASE WHEN latest.video_id IS NOT NULL
                                   AND latest.collected_at < ? THEN 1 ELSE 0 END)
                       AS stale_snapshots,
                     MAX(latest.collected_at) AS latest_snapshot_at
              FROM eligible
              LEFT JOIN latest ON latest.video_id=eligible.video_id
            """, (cutoff,)).fetchone()
        published = int(coverage["published_videos"] or 0)
        with_snapshot = int(coverage["with_snapshot"] or 0)
        stale = int(coverage["stale_snapshots"] or 0)
        latest_snapshot_at = coverage["latest_snapshot_at"]
        missing = max(0, published - with_snapshot)
        state = dict(row) if row else {}
        return {
            "platform": "tiktok",
            "status": state.get("status", "not_started"),
            "last_attempt_at": state.get("last_attempt_at"),
            "last_success_at": state.get("last_success_at"),
            "latest_snapshot_at": latest_snapshot_at,
            "last_error": state.get("last_error"),
            "last_batch": {"requested": state.get("requested", 0),
                           "collected": state.get("collected", 0),
                           "missing": state.get("missing", 0)},
            "source": state.get("source"),
            "available_metrics": ["view_count", "like_count", "comment_count", "share_count"],
            "unavailable_metrics": ["audience_retention", "watch_time", "estimated_revenue"],
            "coverage": {"published_videos": published, "with_snapshot": with_snapshot,
                         "without_snapshot": missing,
                         "stale_snapshots": stale,
                         "stale_or_missing": missing + stale},
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

    def refresh_due_metrics(self, limit=20, min_age_seconds=21600,
                            lease_owner=None, lease_token=None):
        limit = max(1, min(int(limit), 20))
        min_age_seconds = max(0, int(min_age_seconds))
        # Keep candidate selection bounded in SQLite. Avoid loading the
        # entire publication ledger, snapshot map, and retry set into worker RAM.
        due = self.store.due_videos(limit=limit, min_age_seconds=min_age_seconds)
        if not due:
            return {"requested": 0, "collected": 0, "missing": [], "source": "TikTok Display API v2"}
        # OAuth token refresh may make a network request. Reject a worker
        # whose lease is already stale before entering that initialization path.
        self.store.assert_lease(lease_owner, lease_token)
        try:
            token = self.token_provider(required_scope="video.list")
        except Exception as exc:
            raise TikTokMetricsError("TikTok video.list authorization is unavailable: " + type(exc).__name__) from exc
        if not token:
            raise TikTokMetricsError("TikTok account is not connected for video.list analytics")
        # Token refresh can outlive or lose the collector lease; fence the
        # quota-consuming provider request immediately before dispatch.
        self.store.assert_lease(lease_owner, lease_token)
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
        collected_ids, snapshot_items = set(), []
        for video in videos:
            if not isinstance(video, dict):
                raise TikTokMetricsError("TikTok metrics returned a malformed video record")
            video_id = video.get("id")
            if not isinstance(video_id, str) or video_id not in jobs:
                raise TikTokMetricsError("TikTok metrics returned an unrequested video")
            if video_id in collected_ids:
                raise TikTokMetricsError("TikTok metrics returned duplicate video IDs")
            collected_ids.add(video_id)
            snapshot_items.append((jobs[video_id], video))
        # Validate the entire provider batch before committing any snapshots.
        missing = [video_id for video_id in ids if video_id not in collected_ids]
        self.store.save_snapshots(
            snapshot_items, lease_owner=lease_owner, lease_token=lease_token,
            missing_video_ids=missing,
        )
        return {"requested": len(ids), "collected": len(collected_ids),
                "missing": missing, "source": "TikTok Display API v2"}
