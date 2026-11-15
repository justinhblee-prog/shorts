"""YouTube private upload and public counter snapshots.

Uploads require a prior human approval record. This module never publishes publicly.
"""
import json
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
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
              attempt_id TEXT
            );
            CREATE TABLE IF NOT EXISTS youtube_video_snapshots(
              id INTEGER PRIMARY KEY AUTOINCREMENT, video_id TEXT NOT NULL,
              view_count INTEGER, like_count INTEGER, comment_count INTEGER,
              source TEXT NOT NULL DEFAULT 'YouTube Data API v3 videos.list',
              collected_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS youtube_upload_events(
              id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
              event_type TEXT NOT NULL, outcome TEXT, video_id TEXT,
              operator_id TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
              previous_status TEXT, resulting_status TEXT, created_at TEXT NOT NULL
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
            """)
            upload_columns={r["name"] for r in c.execute("PRAGMA table_info(youtube_uploads)")}
            if "attempt_id" not in upload_columns:
                c.execute("ALTER TABLE youtube_uploads ADD COLUMN attempt_id TEXT")
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
                "SELECT decision FROM review_decisions WHERE job_id=? ORDER BY id DESC LIMIT 1",
                (job_id,)
            ).fetchone()
            if run is None or run["status"]!="approved" or latest is None or latest["decision"]!="approved":
                raise YouTubeUploadError(
                    "The production job must remain approved by its latest human review decision"
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
              (job_id,status,privacy_status,title,description,updated_at,attempt_id)
              VALUES(?,'uploading','private',?,?,?,?)
              ON CONFLICT(job_id) DO UPDATE SET status='uploading',
                privacy_status='private',title=excluded.title,
                description=excluded.description,error=NULL,updated_at=excluded.updated_at,
                video_id=NULL,uploaded_at=NULL,attempt_id=excluded.attempt_id
            """,(job_id,title,description,_now(),attempt_id))
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
                  (job_id,event_type,outcome,video_id,operator_id,note,
                   previous_status,resulting_status,created_at)
                  VALUES(?,'late_remote_success','uploaded',?,'system:youtube_response',
                   'Remote success arrived for a superseded or reconciled upload attempt',
                   ?, 'late_success_review_required',?)""",
                  (job_id,video_id.strip(),prior_status,now))
                c.execute("""UPDATE youtube_uploads SET
                  video_id=COALESCE(video_id,?),status='late_success_review_required',
                  error=?,updated_at=? WHERE job_id=?""",
                  (video_id.strip(),"Late remote success from a superseded upload attempt; operator resolution required",now,job_id))
                late_conflict=True
            else:
                c.execute("""UPDATE youtube_uploads SET video_id=?,status='uploaded',
                  privacy_status='private',uploaded_at=?,updated_at=?,error=NULL
                  WHERE job_id=? AND status='uploading' AND attempt_id=?""",
                  (video_id.strip(),_now(),_now(),job_id,attempt_id))
                if c.rowcount != 1:
                    state_error="Upload attempt was replaced before finalization"
        if late_conflict:
            raise YouTubeUploadError("Late YouTube success detected for a superseded attempt. Retry is blocked; all returned video IDs are preserved for operator review.")
        if state_error:
            raise YouTubeUploadError(state_error)

    def fail(self,job_id,error,attempt_id=None):
        with self.db() as c:
            c.execute("""UPDATE youtube_uploads SET status='failed',error=?,updated_at=?
                         WHERE job_id=? AND status='uploading' AND attempt_id=?""",
                      (str(error)[:2000],_now(),job_id,attempt_id))

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
            c.execute("""UPDATE youtube_uploads SET updated_at=?
              WHERE job_id=? AND status='uploading' AND attempt_id=?""",(_now(),job_id,attempt_id))
            return c.rowcount==1

    def mark_reconciliation_required(self,job_id,error,attempt_id=None):
        with self.db() as c:
            row=c.execute("SELECT status,attempt_id FROM youtube_uploads WHERE job_id=?",(job_id,)).fetchone()
            if row is None or row["status"]=="late_success_review_required":
                return
            now=_now()
            if row["attempt_id"]!=attempt_id:
                c.execute("""INSERT INTO youtube_upload_events
                  (job_id,event_type,outcome,video_id,operator_id,note,previous_status,resulting_status,created_at)
                  VALUES(?,'superseded_attempt_uncertain','uncertain',NULL,'system:upload_worker',?,?, 'reconciliation_required',?)""",
                  (job_id,str(error)[:2000],row["status"],now))
                c.execute("""UPDATE youtube_uploads SET status='reconciliation_required',
                  error=?,updated_at=? WHERE job_id=? AND status!='late_success_review_required'""",
                  ("A superseded upload attempt ended with an uncertain remote outcome. "+str(error)[:1500],now,job_id))
                return
            c.execute("""UPDATE youtube_uploads SET status='reconciliation_required',
              error=?,updated_at=? WHERE job_id=? AND status IN ('uploading','reconciliation_required')
              AND attempt_id=?""",
              (str(error)[:2000],now,job_id,attempt_id))
            if c.rowcount != 1:
                raise YouTubeUploadError("Upload record is not in a reconcilable state")

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
                c.execute("""UPDATE youtube_uploads SET video_id=?,status='uploaded',
                  privacy_status='private',uploaded_at=?,updated_at=?,error=NULL
                  WHERE job_id=? AND status IN ('uploading','reconciliation_required')""",
                  (video_id.strip(),_now(),_now(),job_id))
            else:
                c.execute("""UPDATE youtube_uploads SET status='failed',error=?,updated_at=?
                  WHERE job_id=? AND status IN ('uploading','reconciliation_required')""",
                  ("Operator verified no matching remote upload. "+note,_now(),job_id))
            if c.rowcount != 1:
                raise YouTubeUploadError("Upload state changed during reconciliation")
            resulting="uploaded" if outcome=="uploaded" else "failed"
            c.execute("""INSERT INTO youtube_upload_events
              (job_id,event_type,outcome,video_id,operator_id,note,previous_status,resulting_status,created_at)
              VALUES(?,'operator_reconciliation',?,?,?,?,?,?,?)""",
              (job_id,outcome,video_id.strip() if isinstance(video_id,str) else None,
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
            known=c.execute("""SELECT 1 FROM youtube_upload_events
              WHERE job_id=? AND event_type='late_remote_success' AND video_id=? LIMIT 1""",
              (job_id,chosen)).fetchone()
            if not chosen or not known:
                raise YouTubeUploadError("Choose a video ID preserved in the late-success audit events")
            now=_now()
            c.execute("""UPDATE youtube_uploads SET video_id=?,status='uploaded',privacy_status='private',
              uploaded_at=COALESCE(uploaded_at,?),error=NULL,updated_at=?
              WHERE job_id=? AND status='late_success_review_required'""",(chosen,now,now,job_id))
            if c.rowcount!=1:
                raise YouTubeUploadError("Late success state changed during resolution")
            c.execute("""INSERT INTO youtube_upload_events
              (job_id,event_type,outcome,video_id,operator_id,note,previous_status,resulting_status,created_at)
              VALUES(?,'late_success_resolved','uploaded',?,?,?,?,?,?)""",
              (job_id,chosen,operator_id,note,row["status"],"uploaded",now))
        return self.get(job_id)

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
        existing=self.store.get(job_id)
        if existing and existing["status"]=="uploaded":
            return existing
        upload_attempt=self.store.begin(job_id,title,description)
        remote_request_started=False
        heartbeat_stop=threading.Event()
        heartbeat_thread=None
        try:
            from googleapiclient.http import MediaFileUpload
            service=self._service()
            body={
                "snippet":{"title":title,"description":description,
                           "tags":list(tags or []),"categoryId":str(category_id)},
                "status":{"privacyStatus":"private","selfDeclaredMadeForKids":False}
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
