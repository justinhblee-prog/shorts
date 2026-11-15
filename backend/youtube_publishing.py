"""YouTube private upload and public counter snapshots.

Uploads require a prior human approval record. This module never publishes publicly.
"""
import json
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from policy_engine import POLICY_VERSION, POLICY_CHECKED_ON
from approval_integrity import approval_snapshot_matches_current_artifacts, create_verified_media_snapshot
from datetime import datetime, timezone, timedelta
from pathlib import Path


class YouTubeUploadError(RuntimeError):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat()


class YouTubeUploadStore:
    def __init__(self, db_path="data/nexus.sqlite3"):
        self.db_path=str(db_path)
        Path(self.db_path).parent.mkdir(parents=True,exist_ok=True)
        with self.db() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS youtube_uploads(
              job_id TEXT PRIMARY KEY, video_id TEXT, status TEXT NOT NULL,
              privacy_status TEXT NOT NULL DEFAULT 'private',
              title TEXT NOT NULL, description TEXT NOT NULL,
              uploaded_at TEXT, error TEXT, updated_at TEXT NOT NULL,
              attempt_id TEXT, policy_version TEXT, policy_checked_on TEXT
            );
            CREATE TABLE IF NOT EXISTS youtube_video_snapshots(
              id INTEGER PRIMARY KEY AUTOINCREMENT, video_id TEXT NOT NULL,
              view_count INTEGER, like_count INTEGER, comment_count INTEGER,
              source TEXT NOT NULL DEFAULT 'YouTube Data API v3 videos.list',
              collected_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS youtube_upload_events(
              id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
              attempt_id TEXT, event_type TEXT NOT NULL, outcome TEXT, video_id TEXT,
              operator_id TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
              previous_status TEXT, resulting_status TEXT, created_at TEXT NOT NULL,
              policy_version TEXT, policy_checked_on TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_youtube_upload_events_job ON youtube_upload_events(job_id,id);
            CREATE TRIGGER IF NOT EXISTS youtube_upload_events_no_update
              BEFORE UPDATE ON youtube_upload_events
              BEGIN SELECT RAISE(ABORT,'youtube upload audit events are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS youtube_upload_events_no_delete
              BEFORE DELETE ON youtube_upload_events
              BEGIN SELECT RAISE(ABORT,'youtube upload audit events are immutable'); END;
            CREATE INDEX IF NOT EXISTS idx_youtube_snapshots_video
              ON youtube_video_snapshots(video_id,collected_at);
            CREATE TABLE IF NOT EXISTS youtube_metrics_collector_lease(
              id INTEGER PRIMARY KEY CHECK(id=1), owner_id TEXT NOT NULL,
              lease_until REAL NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS youtube_metrics_collection_state(
              id INTEGER PRIMARY KEY CHECK(id=1), status TEXT NOT NULL,
              last_attempt_at TEXT, last_success_at TEXT, last_error TEXT,
              requested INTEGER NOT NULL DEFAULT 0, collected INTEGER NOT NULL DEFAULT 0,
              missing INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            """)
            upload_columns={r["name"] for r in c.execute("PRAGMA table_info(youtube_uploads)")}
            if "attempt_id" not in upload_columns:
                c.execute("ALTER TABLE youtube_uploads ADD COLUMN attempt_id TEXT")
            if "policy_version" not in upload_columns:
                c.execute("ALTER TABLE youtube_uploads ADD COLUMN policy_version TEXT")
            if "policy_checked_on" not in upload_columns:
                c.execute("ALTER TABLE youtube_uploads ADD COLUMN policy_checked_on TEXT")
            event_columns={r["name"] for r in c.execute("PRAGMA table_info(youtube_upload_events)")}
            if "attempt_id" not in event_columns:
                c.execute("ALTER TABLE youtube_upload_events ADD COLUMN attempt_id TEXT")
            if "policy_version" not in event_columns:
                c.execute("ALTER TABLE youtube_upload_events ADD COLUMN policy_version TEXT")
            if "policy_checked_on" not in event_columns:
                c.execute("ALTER TABLE youtube_upload_events ADD COLUMN policy_checked_on TEXT")
    @contextmanager
    def db(self):
        c=sqlite3.connect(self.db_path,timeout=30)
        c.row_factory=sqlite3.Row
        c.execute("PRAGMA busy_timeout=30000")
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def begin(self,job_id,title,description):
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            run=c.execute(
                "SELECT status FROM production_runs WHERE job_id=?",(job_id,)
            ).fetchone()
            latest=c.execute(
                "SELECT decision,artifact_snapshot_json FROM review_decisions "
                "WHERE job_id=? ORDER BY id DESC LIMIT 1",
                (job_id,)
            ).fetchone()
            if run is None or run["status"]!="approved" or latest is None or latest["decision"]!="approved":
                raise YouTubeUploadError(
                    "The production job must remain approved by its latest human review decision"
                )

            snapshot_matches, snapshot_error = approval_snapshot_matches_current_artifacts(
                c, job_id, latest["artifact_snapshot_json"]
            )
            if not snapshot_matches:
                raise YouTubeUploadError(
                    snapshot_error or "Production artifacts changed after approval; return to review"
                )

            # A previous human approval cannot silently carry forward after
            # the deterministic policy checklist has changed.
            script_row=c.execute("""SELECT metadata_json FROM production_artifacts
                WHERE job_id=? AND stage='script' AND artifact_type='text'
                ORDER BY created_at DESC,id DESC LIMIT 1""",(job_id,)).fetchone()
            if script_row is None:
                raise YouTubeUploadError(
                    "Current policy evidence is missing from the script artifact; return to review"
                )
            try:
                script_metadata=json.loads(script_row["metadata_json"])
                current_policy=script_metadata.get("policy_preflight") or {}
                approval_snapshot=json.loads(latest["artifact_snapshot_json"] or "[]")
            except (TypeError,ValueError,AttributeError):
                raise YouTubeUploadError(
                    "Saved policy evidence or approval snapshot is invalid; return to review"
                )
            approved_script=next((
                item for item in approval_snapshot
                if isinstance(item,dict) and item.get("stage")=="script"
                and item.get("artifact_type")=="text"
            ),None) if isinstance(approval_snapshot,list) else None
            approved_policy=(
                (approved_script.get("metadata") or {}).get("policy_preflight")
                if isinstance(approved_script,dict)
                and isinstance(approved_script.get("metadata"),dict) else None
            )
            if (not isinstance(current_policy,dict)
                    or current_policy.get("policy_version")!=POLICY_VERSION
                    or not isinstance(approved_policy,dict)
                    or approved_policy.get("policy_version")!=POLICY_VERSION):
                raise YouTubeUploadError(
                    "Platform policy rules changed or were not recorded after human approval; "
                    "refresh policy evidence and obtain a new human approval before upload"
                )
            if (current_policy.get("status")=="blocked"
                    or current_policy.get("approval_blockers")):
                raise YouTubeUploadError(
                    "Current platform policy evidence still contains blocking requirements; "
                    "return to human review before upload"
                )
            row=c.execute("SELECT * FROM youtube_uploads WHERE job_id=?",(job_id,)).fetchone()
            if row and row["status"]=="uploaded":
                return dict(row)
            if row and row["status"] in ("uploading", "reconciliation_required", "late_success_review_required"):
                raise YouTubeUploadError(
                    "Upload outcome requires reconciliation in YouTube Studio before retry; "
                    "automatic retry is blocked to prevent duplicate videos"
                )
            attempt_id=uuid.uuid4().hex
            c.execute("""INSERT INTO youtube_uploads
              (job_id,status,privacy_status,title,description,updated_at,attempt_id,
               policy_version,policy_checked_on)
              VALUES(?,'uploading','private',?,?,?,?,?,?)
              ON CONFLICT(job_id) DO UPDATE SET status='uploading',
                privacy_status='private',title=excluded.title,
                description=excluded.description,error=NULL,updated_at=excluded.updated_at,
                video_id=NULL,uploaded_at=NULL,attempt_id=excluded.attempt_id,
                policy_version=excluded.policy_version,
                policy_checked_on=excluded.policy_checked_on
            """,(job_id,title,description,_now(),attempt_id,
                  current_policy["policy_version"],current_policy.get("policy_checked_on")))
            c.execute("""INSERT INTO youtube_upload_events
              (job_id,attempt_id,event_type,outcome,operator_id,note,previous_status,
               resulting_status,created_at,policy_version,policy_checked_on)
              VALUES(?,?,'upload_attempt_started','started','system:upload_worker',
                ?,?,'uploading',?,?,?)""",
              (job_id,attempt_id,
               "Upload attempt initialized with private visibility; policy version "
               + str(current_policy["policy_version"]),
               row["status"] if row else None,_now(),
               current_policy["policy_version"],current_policy.get("policy_checked_on")))
            return dict(c.execute("SELECT * FROM youtube_uploads WHERE job_id=?",(job_id,)).fetchone())

    def finish(self,job_id,video_id,attempt_id=None):
        if not isinstance(video_id,str) or not video_id.strip():
            raise YouTubeUploadError("A confirmed YouTube video ID is required")
        late_conflict=False
        state_error=None
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            row=c.execute("SELECT * FROM youtube_uploads WHERE job_id=?",(job_id,)).fetchone()
            if row is None:
                state_error="Upload record disappeared before remote completion could be recorded"
            elif row["status"]=="uploaded" and row["video_id"]==video_id.strip():
                return
            elif row["status"]!="uploading" or row["attempt_id"]!=attempt_id:
                now=_now()
                prior_status=row["status"]
                c.execute("""INSERT INTO youtube_upload_events
                  (job_id,attempt_id,event_type,outcome,video_id,operator_id,note,
                   previous_status,resulting_status,created_at)
                  VALUES(?,?,'late_remote_success','uploaded',?,'system:youtube_response',
                   'Remote success arrived for a superseded or reconciled upload attempt',
                   ?, 'late_success_review_required',?)""",
                  (job_id,attempt_id,video_id.strip(),prior_status,now))
                c.execute("""UPDATE youtube_uploads SET
                  video_id=COALESCE(video_id,?),status='late_success_review_required',
                  error=?,updated_at=? WHERE job_id=?""",
                  (video_id.strip(),"Late remote success from a superseded upload attempt; operator resolution required",now,job_id))
                late_conflict=True
            else:
                updated=c.execute("""UPDATE youtube_uploads SET video_id=?,status='uploaded',
                  privacy_status='private',uploaded_at=?,updated_at=?,error=NULL
                  WHERE job_id=? AND status='uploading' AND attempt_id=?""",
                  (video_id.strip(),_now(),_now(),job_id,attempt_id))
                if updated.rowcount != 1:
                    state_error="Upload attempt was replaced before finalization"
                else:
                    c.execute("""INSERT INTO youtube_upload_events
                      (job_id,attempt_id,event_type,outcome,video_id,operator_id,note,
                       previous_status,resulting_status,created_at)
                      VALUES(?,?,'upload_confirmed','uploaded',?,'system:youtube_response',
                       'YouTube returned a video ID for the active upload attempt',
                       'uploading','uploaded',?)""",
                      (job_id,attempt_id,video_id.strip(),_now()))
        if late_conflict:
            raise YouTubeUploadError("Late YouTube success detected for a superseded attempt. Retry is blocked; all returned video IDs are preserved for operator review.")
        if state_error:
            raise YouTubeUploadError(state_error)

    def fail(self,job_id,error,attempt_id=None):
        with self.db() as c:
            now=_now()
            updated=c.execute("""UPDATE youtube_uploads SET status='failed',error=?,updated_at=?
                         WHERE job_id=? AND status='uploading' AND attempt_id=?""",
                      (str(error)[:2000],now,job_id,attempt_id))
            if updated.rowcount==1:
                c.execute("""INSERT INTO youtube_upload_events
                  (job_id,attempt_id,event_type,outcome,operator_id,note,
                   previous_status,resulting_status,created_at)
                  VALUES(?,?,'upload_preflight_failed','failed','system:upload_worker',?,
                    'uploading','failed',?)""",
                  (job_id,attempt_id,str(error)[:2000],now))

    @staticmethod
    def upload_stale_seconds():
        return max(60,int(os.getenv("NEXUS_UPLOAD_STALE_SECONDS","900")))

    @classmethod
    def is_stale_upload(cls,row):
        if row is None or row["status"]!="uploading":
            return False
        try:
            updated=datetime.fromisoformat(row["updated_at"])
            if updated.tzinfo is None:
                updated=updated.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc)-updated).total_seconds() >= cls.upload_stale_seconds()
        except (TypeError,ValueError):
            return False

    def touch_upload(self,job_id,attempt_id=None):
        with self.db() as c:
            updated=c.execute("""UPDATE youtube_uploads SET updated_at=?
              WHERE job_id=? AND status='uploading' AND attempt_id=?""",(_now(),job_id,attempt_id))
            return updated.rowcount==1

    def mark_reconciliation_required(self,job_id,error,attempt_id=None):
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            row=c.execute("SELECT status,attempt_id FROM youtube_uploads WHERE job_id=?",(job_id,)).fetchone()
            if row is None or row["status"]=="late_success_review_required":
                return
            now=_now()
            if row["status"]=="uploaded":
                event_type=("post_confirmation_worker_error"
                            if row["attempt_id"]==attempt_id
                            else "superseded_attempt_uncertain")
                c.execute("""INSERT INTO youtube_upload_events
                  (job_id,attempt_id,event_type,outcome,video_id,operator_id,note,previous_status,resulting_status,created_at)
                  VALUES(?,?,?,'informational',NULL,'system:upload_worker',?,
                    'uploaded','uploaded',?)""",
                  (job_id,attempt_id,event_type,str(error)[:2000],now))
                return
            if row["attempt_id"]!=attempt_id:
                c.execute("""INSERT INTO youtube_upload_events
                  (job_id,attempt_id,event_type,outcome,video_id,operator_id,note,previous_status,resulting_status,created_at)
                  VALUES(?,?,'superseded_attempt_uncertain','uncertain',NULL,'system:upload_worker',?,?, 'reconciliation_required',?)""",
                  (job_id,attempt_id,str(error)[:2000],row["status"],now))
                c.execute("""UPDATE youtube_uploads SET status='reconciliation_required',
                  error=?,updated_at=? WHERE job_id=? AND status IN ('uploading','failed','reconciliation_required')""",
                  ("A superseded upload attempt ended with an uncertain remote outcome. "+str(error)[:1500],now,job_id))
                return
            previous_status=row["status"]
            updated=c.execute("""UPDATE youtube_uploads SET status='reconciliation_required',
              error=?,updated_at=? WHERE job_id=? AND status IN ('uploading','reconciliation_required')
              AND attempt_id=?""",
              (str(error)[:2000],now,job_id,attempt_id))
            if updated.rowcount != 1:
                raise YouTubeUploadError("Upload record is not in a reconcilable state")
            c.execute("""INSERT INTO youtube_upload_events
              (job_id,attempt_id,event_type,outcome,operator_id,note,
               previous_status,resulting_status,created_at)
              VALUES(?,?,'upload_outcome_uncertain','uncertain','system:upload_worker',?,
                ?,'reconciliation_required',?)""",
              (job_id,attempt_id,str(error)[:2000],previous_status,now))

    def reconcile(self,job_id,outcome,video_id=None,note="",operator_id="unspecified"):
        """Resolve an ambiguous remote upload only after explicit operator verification."""
        note=str(note or "").strip()
        if not note or len(note)>2000:
            raise YouTubeUploadError("A reconciliation note is required (max 2000 characters)")
        operator_id=str(operator_id or "").strip()
        if not operator_id or len(operator_id)>128:
            raise YouTubeUploadError("A valid operator ID is required (max 128 characters)")
        if outcome not in ("uploaded","not_uploaded"):
            raise YouTubeUploadError("Outcome must be uploaded or not_uploaded")
        if outcome=="uploaded" and (not isinstance(video_id,str) or not video_id.strip()):
            raise YouTubeUploadError("A confirmed YouTube video ID is required")
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            row=c.execute("SELECT * FROM youtube_uploads WHERE job_id=?",(job_id,)).fetchone()
            if row is None:
                raise YouTubeUploadError("Upload record not found")
            if row["status"]=="uploaded":
                if outcome=="uploaded" and row["video_id"]==video_id:
                    return dict(row)
                raise YouTubeUploadError("Upload is already finalized; conflicting reconciliation rejected")
            if row["status"]=="late_success_review_required":
                raise YouTubeUploadError("A late remote success is preserved; use the late-result resolution action")
            if row["status"]=="uploading" and not self.is_stale_upload(row):
                raise YouTubeUploadError(
                    "Upload is still within its active window; wait for completion or timeout before reconciliation"
                )
            if row["status"] not in ("uploading","reconciliation_required"):
                raise YouTubeUploadError("Only an ambiguous upload can be reconciled")
            if outcome=="uploaded":
                updated=c.execute("""UPDATE youtube_uploads SET video_id=?,status='uploaded',
                  privacy_status='private',uploaded_at=?,updated_at=?,error=NULL
                  WHERE job_id=? AND status IN ('uploading','reconciliation_required')""",
                  (video_id.strip(),_now(),_now(),job_id))
            else:
                updated=c.execute("""UPDATE youtube_uploads SET status='failed',error=?,updated_at=?
                  WHERE job_id=? AND status IN ('uploading','reconciliation_required')""",
                  ("Operator verified no matching remote upload. "+note,_now(),job_id))
            if updated.rowcount != 1:
                raise YouTubeUploadError("Upload state changed during reconciliation")
            resulting="uploaded" if outcome=="uploaded" else "failed"
            c.execute("""INSERT INTO youtube_upload_events
              (job_id,attempt_id,event_type,outcome,video_id,operator_id,note,previous_status,resulting_status,created_at)
              VALUES(?,?,'operator_reconciliation',?,?,?,?,?,?,?)""",
              (job_id,row["attempt_id"],outcome,video_id.strip() if isinstance(video_id,str) else None,
               operator_id,note,row["status"],resulting,_now()))
        return self.get(job_id)

    def resolve_late_success(self,job_id,operator_id,note,video_id=None):
        operator_id=str(operator_id or "").strip()
        note=str(note or "").strip()
        if not operator_id or len(operator_id)>128 or not note or len(note)>2000:
            raise YouTubeUploadError("Operator ID and resolution note are required")
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            row=c.execute("SELECT * FROM youtube_uploads WHERE job_id=?",(job_id,)).fetchone()
            if row is None or row["status"]!="late_success_review_required":
                raise YouTubeUploadError("No preserved late remote success is awaiting resolution")
            chosen=str(video_id or "").strip()
            known=c.execute("""SELECT attempt_id FROM youtube_upload_events
              WHERE job_id=? AND event_type='late_remote_success' AND video_id=?
              ORDER BY id DESC LIMIT 1""",(job_id,chosen)).fetchone()
            if not chosen or (chosen!=row["video_id"] and not known):
                raise YouTubeUploadError(
                    "Choose the currently recorded video ID or one preserved in late-success audit events"
                )
            resolved_attempt_id=(known["attempt_id"] if known else row["attempt_id"])
            now=_now()
            updated=c.execute("""UPDATE youtube_uploads SET video_id=?,status='uploaded',privacy_status='private',
              uploaded_at=COALESCE(uploaded_at,?),error=NULL,updated_at=?
              WHERE job_id=? AND status='late_success_review_required'""",(chosen,now,now,job_id))
            if updated.rowcount!=1:
                raise YouTubeUploadError("Late success state changed during resolution")
            c.execute("""INSERT INTO youtube_upload_events
              (job_id,attempt_id,event_type,outcome,video_id,operator_id,note,previous_status,resulting_status,created_at)
              VALUES(?,?,'late_success_resolved','uploaded',?,?,?,?,?,?)""",
              (job_id,resolved_attempt_id,chosen,operator_id,note,row["status"],"uploaded",now))
        return self.get(job_id)

    def due_metric_video_ids(self, limit=50, min_age_seconds=21600):
        """Return uploaded video IDs with no recent counter snapshot, capped at 50."""
        limit = max(1, min(int(limit), 50))
        min_age_seconds = max(300, int(min_age_seconds))
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=min_age_seconds)).isoformat()
        with self.db() as c:
            rows = c.execute("""
                SELECT u.video_id, MAX(s.collected_at) AS last_collected_at
                FROM youtube_uploads u
                LEFT JOIN youtube_video_snapshots s ON s.video_id=u.video_id
                WHERE u.status='uploaded' AND u.video_id IS NOT NULL
                GROUP BY u.video_id
                HAVING last_collected_at IS NULL OR last_collected_at < ?
                ORDER BY COALESCE(last_collected_at,'') ASC, u.video_id ASC
                LIMIT ?
            """, (cutoff, limit)).fetchall()
        return [row["video_id"] for row in rows]

    def acquire_metrics_collector_lease(self, owner_id, lease_seconds=300):
        """Acquire a database-backed singleton lease for the periodic metrics collector."""
        owner_id = str(owner_id or "").strip()
        if not owner_id or len(owner_id) > 200:
            raise ValueError("A valid metrics collector owner ID is required")
        now = datetime.now(timezone.utc).timestamp()
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT owner_id,lease_until FROM youtube_metrics_collector_lease WHERE id=1"
            ).fetchone()
            if row and row["owner_id"] != owner_id and float(row["lease_until"]) > now:
                return None
            c.execute("""
                INSERT INTO youtube_metrics_collector_lease(id,owner_id,lease_until,updated_at)
                VALUES(1,?,?,?)
                ON CONFLICT(id) DO UPDATE SET owner_id=excluded.owner_id,
                  lease_until=excluded.lease_until,updated_at=excluded.updated_at
            """, (owner_id, now + max(30, int(lease_seconds)), _now()))
        return owner_id

    def release_metrics_collector_lease(self, owner_id):
        with self.db() as c:
            updated = c.execute(
                "DELETE FROM youtube_metrics_collector_lease WHERE id=1 AND owner_id=?",
                (owner_id,)
            )
            return updated.rowcount == 1

    def record_metrics_collection(self, status, requested=0, collected=0,
                                   missing=0, error=None, source="YouTube Data API v3"):
        """Persist collector health without converting provider errors into metric values."""
        if status not in ("running", "succeeded", "failed"):
            raise ValueError("Invalid metrics collection status")
        now = _now()
        with self.db() as c:
            c.execute("""
                INSERT INTO youtube_metrics_collection_state
                  (id,status,last_attempt_at,last_success_at,last_error,requested,
                   collected,missing,source,updated_at)
                VALUES(1,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                  status=excluded.status,
                  last_attempt_at=excluded.last_attempt_at,
                  last_success_at=CASE WHEN excluded.status='succeeded'
                    THEN excluded.last_success_at
                    ELSE youtube_metrics_collection_state.last_success_at END,
                  last_error=CASE WHEN excluded.status='failed'
                    THEN excluded.last_error
                    WHEN excluded.status='succeeded' THEN NULL
                    ELSE youtube_metrics_collection_state.last_error END,
                  requested=excluded.requested,collected=excluded.collected,
                  missing=excluded.missing,source=excluded.source,updated_at=excluded.updated_at
            """, (status, now, now if status == "succeeded" else None,
                  str(error)[:1000] if error else None, max(0, int(requested)),
                  max(0, int(collected)), max(0, int(missing)), source, now))

    def metrics_collection_status(self, freshness_seconds=43200):
        """Return source-backed collection freshness and coverage for uploaded YouTube videos."""
        cutoff = (datetime.now(timezone.utc) -
                  timedelta(seconds=max(300, int(freshness_seconds)))).isoformat()
        with self.db() as c:
            state = c.execute(
                "SELECT * FROM youtube_metrics_collection_state WHERE id=1"
            ).fetchone()
            totals = c.execute("""
                SELECT COUNT(*) AS uploaded_videos,
                  SUM(CASE WHEN latest_snapshot IS NOT NULL THEN 1 ELSE 0 END) AS measured_videos,
                  SUM(CASE WHEN latest_snapshot IS NULL OR latest_snapshot < ? THEN 1 ELSE 0 END) AS stale_videos
                FROM (
                  SELECT u.video_id, MAX(s.collected_at) AS latest_snapshot
                  FROM youtube_uploads u
                  LEFT JOIN youtube_video_snapshots s ON s.video_id=u.video_id
                  WHERE u.status='uploaded' AND u.video_id IS NOT NULL
                  GROUP BY u.video_id
                )
            """, (cutoff,)).fetchone()
        uploaded = int(totals["uploaded_videos"] or 0)
        measured = int(totals["measured_videos"] or 0)
        stale = int(totals["stale_videos"] or 0)
        row = dict(state) if state else {}
        return {
            "platform": "youtube",
            "provider": "YouTube Data API v3 videos.list",
            "status": row.get("status", "not_started"),
            "last_attempt_at": row.get("last_attempt_at"),
            "last_success_at": row.get("last_success_at"),
            "last_error": row.get("last_error"),
            "last_batch": {
                "requested": int(row.get("requested") or 0),
                "collected": int(row.get("collected") or 0),
                "missing": int(row.get("missing") or 0),
            },
            "coverage": {
                "uploaded_videos": uploaded,
                "with_snapshot": measured,
                "without_snapshot": max(0, uploaded - measured),
                "stale_snapshots": stale,
                "freshness_window_seconds": max(300, int(freshness_seconds)),
                "snapshot_coverage_ratio": round(measured / uploaded, 4) if uploaded else None,
            },
            "read_only": True,
        }

    def snapshot(self,video_id,stats):
        def count(key):
            value=stats.get(key)
            return int(value) if value is not None else None
        with self.db() as c:
            c.execute("""INSERT INTO youtube_video_snapshots
              (video_id,view_count,like_count,comment_count,collected_at)
              VALUES(?,?,?,?,?)""",(video_id,count("viewCount"),count("likeCount"),
                                     count("commentCount"),_now()))

    def get(self,job_id):
        with self.db() as c:
            row=c.execute("SELECT * FROM youtube_uploads WHERE job_id=?",(job_id,)).fetchone()
            if row is None: return None
            result=dict(row)
            if row["video_id"]:
                result["snapshots"]=[dict(x) for x in c.execute(
                    "SELECT * FROM youtube_video_snapshots WHERE video_id=? ORDER BY id",
                    (row["video_id"],)).fetchall()]
            else: result["snapshots"]=[]
            result["events"]=[dict(x) for x in c.execute(
                "SELECT * FROM youtube_upload_events WHERE job_id=? ORDER BY id",(job_id,)
            ).fetchall()]
            result["reconciliation_required"]=(
                row["status"] in ("reconciliation_required","late_success_review_required")
                or self.is_stale_upload(row)
            )
            return result


class YouTubePublisher:
    def __init__(self,store,service=None):
        self.store=store
        self.service=service

    def _service(self):
        if self.service is not None:
            return self.service
        refresh=os.getenv("YOUTUBE_REFRESH_TOKEN")
        client_id=os.getenv("YOUTUBE_CLIENT_ID")
        client_secret=os.getenv("YOUTUBE_CLIENT_SECRET")
        if not all((refresh,client_id,client_secret)):
            raise YouTubeUploadError(
                "YOUTUBE_REFRESH_TOKEN, YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET are required"
            )
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build
            creds=Credentials(
                token=None,refresh_token=refresh,token_uri="https://oauth2.googleapis.com/token",
                client_id=client_id,client_secret=client_secret,
                scopes=["https://www.googleapis.com/auth/youtube.upload",
                        "https://www.googleapis.com/auth/youtube.readonly"])
            creds.refresh(Request())
            return build("youtube","v3",credentials=creds,cache_discovery=False)
        except Exception as exc:
            raise YouTubeUploadError("YouTube OAuth initialization failed: "+type(exc).__name__) from exc

    def upload_approved(self,job_id,media_path,review_store,title,description="",tags=None,
                        category_id="22"):
        history=review_store.history(job_id)
        if not history or history[-1]["decision"]!="approved":
            raise YouTubeUploadError(
                "The latest human review decision must be approved before upload"
            )
        if not isinstance(media_path,str) or not media_path.strip():
            raise YouTubeUploadError("A staged media path is required")
        media_root=Path(os.getenv("NEXUS_MEDIA_DIR","data/media")).resolve()
        candidate=Path(media_path)
        if not candidate.is_absolute():
            candidate=media_root/candidate
        try:
            resolved=candidate.resolve(strict=True)
            resolved.relative_to(media_root)
        except (OSError,ValueError):
            raise YouTubeUploadError("Media path must resolve to an existing file inside NEXUS_MEDIA_DIR")
        if not resolved.is_file():
            raise YouTubeUploadError("Staged media path is not a regular file")
        allowed={".mp4": "video/mp4", ".m4v": "video/x-m4v",
                 ".mov": "video/quicktime", ".webm": "video/webm"}
        media_type=allowed.get(resolved.suffix.lower())
        if not media_type:
            raise YouTubeUploadError("Unsupported media extension; use MP4, M4V, MOV or WebM")
        max_bytes=max(1,int(os.getenv("NEXUS_MAX_MEDIA_BYTES",str(256*1024*1024))))
        size=resolved.stat().st_size
        if size<=0:
            raise YouTubeUploadError("Rendered video file is empty")
        if size>max_bytes:
            raise YouTubeUploadError("Rendered video exceeds NEXUS_MAX_MEDIA_BYTES")
        if not isinstance(title,str) or not title.strip() or len(title)>100:
            raise YouTubeUploadError("Video title must contain 1 to 100 characters")
        if not isinstance(description,str) or len(description)>5000:
            raise YouTubeUploadError("Video description exceeds 5000 characters")
        if len(tags or [])>30 or any(not isinstance(tag,str) or len(tag)>500 for tag in (tags or [])):
            raise YouTubeUploadError("At most 30 valid tags are allowed")
        # The policy preflight records an explicit YouTube A/S declaration.
        # Never infer the platform disclosure from the generic "AI-generated" label.
        with self.store.db() as connection:
            policy_row=connection.execute(
                """SELECT metadata_json FROM production_artifacts
                   WHERE job_id=? AND stage='script' AND artifact_type='text'
                   ORDER BY created_at DESC,id DESC LIMIT 1""",(job_id,)
            ).fetchone()
        if policy_row is None:
            raise YouTubeUploadError("YouTube synthetic-media disclosure evidence is missing; return to review")
        try:
            policy_evidence=json.loads(policy_row["metadata_json"]).get("policy_preflight") or {}
        except (TypeError, ValueError, AttributeError):
            raise YouTubeUploadError("YouTube synthetic-media disclosure evidence is invalid; return to review")
        contains_synthetic_media=policy_evidence.get("youtube_contains_synthetic_media")
        if not isinstance(contains_synthetic_media,bool):
            raise YouTubeUploadError(
                "YouTube realistic altered/synthetic-media status is not explicitly classified; "
                "return to policy review before upload"
            )
        existing=self.store.get(job_id)
        if existing and existing["status"]=="uploaded":
            return existing
        try:
            snapshot_path, snapshot_size = create_verified_media_snapshot(
                resolved, history[-1].get("staged_media_sha256"),
                history[-1].get("staged_media_size_bytes")
            )
        except (OSError, ValueError) as exc:
            raise YouTubeUploadError(str(exc)) from exc
        resolved = Path(snapshot_path)
        size = snapshot_size
        try:
            upload_attempt=self.store.begin(job_id,title,description)
        except Exception:
            try:
                os.unlink(snapshot_path)
            except OSError:
                pass
            raise
        remote_request_started=False
        heartbeat_stop=threading.Event()
        heartbeat_thread=None
        try:
            from googleapiclient.http import MediaFileUpload
            service=self._service()
            body={
                "snippet":{"title":title,"description":description,
                           "tags":list(tags or []),"categoryId":str(category_id)},
                "status":{"privacyStatus":"private","selfDeclaredMadeForKids":False,
                          "containsSyntheticMedia":contains_synthetic_media}
            }
            request=service.videos().insert(
                part="snippet,status",body=body,
                media_body=MediaFileUpload(str(resolved),mimetype=media_type,
                                           chunksize=8*1024*1024,resumable=True))
            remote_request_started=True
            heartbeat_interval=max(5,min(30,self.store.upload_stale_seconds()//3))
            def refresh_upload_activity():
                while not heartbeat_stop.wait(heartbeat_interval):
                    try:
                        self.store.touch_upload(job_id,upload_attempt.get("attempt_id"))
                    except Exception:
                        # The upload itself remains authoritative; a later poll can retry.
                        continue
            heartbeat_thread=threading.Thread(target=refresh_upload_activity,daemon=True)
            heartbeat_thread.start()
            response=None
            while response is None:
                _,response=request.next_chunk()
                if response is None:
                    self.store.touch_upload(job_id,upload_attempt.get("attempt_id"))
            video_id=response.get("id")
            if not video_id:
                raise YouTubeUploadError("YouTube response did not contain a video ID")
            self.store.finish(job_id,video_id,upload_attempt.get("attempt_id"))
            try:
                result=service.videos().list(part="statistics,status",id=video_id).execute()
                items=result.get("items",[])
                if items:
                    self.store.snapshot(video_id,items[0].get("statistics",{}))
            except Exception:
                # Upload is confirmed even if the first metrics snapshot is unavailable.
                pass
            return self.store.get(job_id)
        except Exception as exc:
            detail=type(exc).__name__+": "+str(exc)
            if remote_request_started:
                self.store.mark_reconciliation_required(
                    job_id,"Remote upload outcome is uncertain. "+detail,
                    upload_attempt.get("attempt_id")
                )
            else:
                self.store.fail(job_id,detail,upload_attempt.get("attempt_id"))
            if isinstance(exc,YouTubeUploadError):
                raise
            if remote_request_started:
                raise YouTubeUploadError(
                    "YouTube upload outcome is uncertain. Check YouTube Studio and reconcile "
                    "this job before retrying; duplicate uploads are blocked."
                ) from exc
            raise YouTubeUploadError("YouTube upload failed before remote upload started: "+type(exc).__name__) from exc
        finally:
            heartbeat_stop.set()
            if heartbeat_thread is not None:
                heartbeat_thread.join(timeout=2)
            try:
                os.unlink(snapshot_path)
            except OSError:
                pass

    def refresh_due_metrics(self, limit=50, min_age_seconds=21600):
        """Refresh due uploaded videos in one quota-efficient videos.list request."""
        video_ids = self.store.due_metric_video_ids(limit, min_age_seconds)
        if not video_ids:
            return {"requested": 0, "collected": 0, "missing": [], "source": "YouTube Data API v3"}
        service = self._service()
        response = service.videos().list(
            part="statistics,status", id=",".join(video_ids), maxResults=len(video_ids)
        ).execute()
        items = response.get("items", [])
        collected = []
        for item in items:
            video_id = item.get("id")
            if video_id in video_ids:
                self.store.snapshot(video_id, item.get("statistics", {}))
                collected.append(video_id)
        missing = sorted(set(video_ids) - set(collected))
        return {
            "requested": len(video_ids), "collected": len(collected),
            "missing": missing, "source": "YouTube Data API v3",
            "privacy_statuses": {
                item.get("id"): item.get("status", {}).get("privacyStatus")
                for item in items if item.get("id") in collected
            }
        }

    def refresh_metrics(self,video_id):
        service=self._service()
        response=service.videos().list(part="statistics,status",id=video_id).execute()
        items=response.get("items",[])
        if not items:
            raise YouTubeUploadError("Video not found or inaccessible")
        item=items[0]
        self.store.snapshot(video_id,item.get("statistics",{}))
        return {"video_id":video_id,"statistics":item.get("statistics",{}),
                "status":item.get("status",{}),"source":"YouTube Data API v3"}
