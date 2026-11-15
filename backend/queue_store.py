"""Durable SQLite queue with lease fencing."""
import json, sqlite3, uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc)

def stamp(value):
    return value.astimezone(timezone.utc).isoformat()


class LeaseConflict(Exception): pass
class JobNotFound(Exception): pass
class IdempotencyConflict(ValueError): pass


class JobQueue:
    def __init__(self, db_path="data/nexus.sqlite3", lease_seconds=90):
        self.db_path=str(db_path)
        self.lease_seconds=max(10,int(lease_seconds))
        Path(self.db_path).parent.mkdir(parents=True,exist_ok=True)
        with self.db() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript("""
            CREATE TABLE IF NOT EXISTS pipeline_jobs(
              id TEXT PRIMARY KEY, job_type TEXT NOT NULL, channel_name TEXT,
              payload_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
              priority INTEGER NOT NULL DEFAULT 100, attempt INTEGER NOT NULL DEFAULT 0,
              max_attempts INTEGER NOT NULL DEFAULT 3, available_at TEXT NOT NULL,
              worker_id TEXT, lease_token TEXT, lease_expires_at TEXT,
              idempotency_key TEXT UNIQUE, error_code TEXT, error_message TEXT,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL, started_at TEXT,
              completed_at TEXT);
            CREATE INDEX IF NOT EXISTS idx_jobs_claim ON pipeline_jobs(status,available_at,priority,created_at);
            CREATE INDEX IF NOT EXISTS idx_jobs_lease ON pipeline_jobs(status,lease_expires_at);
            CREATE TABLE IF NOT EXISTS job_events(
              id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL REFERENCES pipeline_jobs(id) ON DELETE CASCADE,
              event_type TEXT NOT NULL, from_status TEXT, to_status TEXT, worker_id TEXT,
              details_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_events_job ON job_events(job_id,id);
            CREATE TABLE IF NOT EXISTS worker_registry(
              worker_id TEXT PRIMARY KEY, hostname TEXT, last_seen_at TEXT NOT NULL, status TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS worker_control(
              id INTEGER PRIMARY KEY CHECK(id=1), paused INTEGER NOT NULL DEFAULT 0,
              pause_reason TEXT, paused_job_id TEXT, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS worker_control_events(
              id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL,
              actor TEXT NOT NULL, reason TEXT NOT NULL, paused_job_id TEXT,
              created_at TEXT NOT NULL);
            INSERT OR IGNORE INTO worker_control(id,paused,updated_at)
              VALUES(1,0,'1970-01-01T00:00:00+00:00');
            """)

    @contextmanager
    def db(self):
        c=sqlite3.connect(self.db_path,timeout=30,isolation_level=None)
        c.row_factory=sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=30000")
        try:
            yield c
        except Exception:
            if c.in_transaction:
                c.rollback()
            raise
        finally:
            c.close()

    def event(self,c,jid,kind,before,after,worker,details=None):
        c.execute("INSERT INTO job_events(job_id,event_type,from_status,to_status,worker_id,details_json,created_at) VALUES(?,?,?,?,?,?,?)",
          (jid,kind,before,after,worker,json.dumps(details or {},ensure_ascii=False),stamp(now())))

    def decode(self,row):
        if row is None: return None
        d=dict(row); d["payload"]=json.loads(d.pop("payload_json")); return d

    def enqueue(self,job_type,payload,channel_name=None,priority=100,max_attempts=3,idempotency_key=None):
        if not job_type.strip(): raise ValueError("job_type required")
        n=stamp(now()); jid=str(uuid.uuid4())
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            if idempotency_key:
                old=c.execute("SELECT * FROM pipeline_jobs WHERE idempotency_key=?",(idempotency_key,)).fetchone()
                if old:
                    try:
                        old_payload=json.loads(old["payload_json"])
                    except (TypeError, ValueError, json.JSONDecodeError) as exc:
                        raise IdempotencyConflict(
                            "Existing idempotency record cannot be safely compared"
                        ) from exc
                    if (old["job_type"] != job_type
                            or old["channel_name"] != channel_name
                            or old_payload != payload):
                        raise IdempotencyConflict(
                            "Idempotency key is already used by a different job request"
                        )
                    c.commit()
                    return self.decode(old)
            c.execute("""INSERT INTO pipeline_jobs(id,job_type,channel_name,payload_json,status,priority,max_attempts,available_at,idempotency_key,created_at,updated_at)
              VALUES(?,?,?,?, 'queued',?,?,?,?,?,?)""",
              (jid,job_type,channel_name,json.dumps(payload,ensure_ascii=False),int(priority),max(1,int(max_attempts)),n,idempotency_key,n,n))
            self.event(c,jid,"enqueued",None,"queued",None)
            row=c.execute("SELECT * FROM pipeline_jobs WHERE id=?",(jid,)).fetchone(); c.commit()
            return self.decode(row)

    def _pause_production_in_transaction(self, c, reason, job_id, timestamp, actor="system"):
        """Persist pause and fence all running production jobs in caller transaction."""
        reason = str(reason)[:2000]
        c.execute("""UPDATE worker_control SET paused=1,pause_reason=?,
          paused_job_id=?,updated_at=? WHERE id=1""", (reason, job_id, timestamp))
        c.execute("""INSERT INTO worker_control_events
            (event_type,actor,reason,paused_job_id,created_at)
            VALUES('paused',?,?,?,?)""", (str(actor)[:128], reason, job_id, timestamp))
        running = c.execute("""SELECT id,worker_id FROM pipeline_jobs
            WHERE status='running' AND job_type='short_video_production'""").fetchall()
        has_runs = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='production_runs'").fetchone()
        for row in running:
            c.execute("""UPDATE pipeline_jobs SET status='failed_terminal',
                worker_id=NULL,lease_token=NULL,lease_expires_at=NULL,
                updated_at=?,error_code='worker_paused',error_message=?
                WHERE id=? AND status='running'""",
                (timestamp, ("Queue paused: " + reason)[:2000], row["id"]))
            self.event(c, row["id"], "worker_pause", "running", "failed_terminal",
                       row["worker_id"], {"reason": reason, "paused_job_id": job_id})
            if has_runs:
                c.execute("""UPDATE production_runs SET status='failed_terminal',
                    current_stage='worker_paused',error=?,updated_at=?
                    WHERE job_id=? AND status NOT IN ('approved','uploaded')""",
                    (("Queue paused: " + reason)[:2000], timestamp, row["id"]))
    def claim(self,worker_id,hostname=None,job_type=None):
        if not worker_id.strip(): raise ValueError("worker_id required")
        dt=now(); n=stamp(dt); expiry=stamp(dt+timedelta(seconds=self.lease_seconds)); token=str(uuid.uuid4())
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            control=c.execute("SELECT paused FROM worker_control WHERE id=1").fetchone()
            production_paused=bool(control and control["paused"])
            if production_paused and job_type == "short_video_production":
                c.commit()
                return None
            c.execute("""INSERT INTO worker_registry VALUES(?,?,?,'online') ON CONFLICT(worker_id)
              DO UPDATE SET hostname=excluded.hostname,last_seen_at=excluded.last_seen_at,status='online'""",(worker_id,hostname,n))
            expired=c.execute("""SELECT id,job_type,attempt,max_attempts FROM pipeline_jobs WHERE status='running'
              AND lease_expires_at IS NOT NULL AND lease_expires_at<=?""",(n,)).fetchall()
            production_expired = []
            for e in expired:
                ambiguous = e["job_type"] == "short_video_production"
                target = "failed_terminal" if ambiguous or e["attempt"]>=e["max_attempts"] else "queued"
                code = "production_lease_expired_ambiguous" if ambiguous else "lease_expired"
                message = "Production lease expired; external provider outcome is ambiguous" if ambiguous else "Worker lease expired"
                c.execute("""UPDATE pipeline_jobs SET status=?,worker_id=NULL,lease_token=NULL,lease_expires_at=NULL,
                  available_at=?,updated_at=?,error_code=?,error_message=? WHERE id=?""",
                  (target,n,n,code,message,e["id"]))
                self.event(c,e["id"],"lease_expired","running",target,None,
                           {"attempt":e["attempt"],"ambiguous_external_work":ambiguous})
                if ambiguous:
                    production_expired.append(e["id"])
                    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='production_runs'").fetchone():
                        c.execute("""UPDATE production_runs SET status='failed_terminal',
                            current_stage='lease_expired_ambiguous',error=?,updated_at=?
                            WHERE job_id=? AND status NOT IN ('approved','uploaded')""",
                            (message,n,e["id"]))
            if production_expired:
                self._pause_production_in_transaction(c,
                    "Production worker lease expired; provider result may be ambiguous",
                    production_expired[0], n)
            production_paused = bool(c.execute("SELECT paused FROM worker_control WHERE id=1").fetchone()["paused"])
            if production_paused and job_type == "short_video_production":
                c.commit()
                return None
            if job_type:
                row=c.execute("""SELECT * FROM pipeline_jobs WHERE status IN ('queued','failed_retriable')
                  AND available_at<=? AND attempt<max_attempts AND job_type=?
                  ORDER BY priority,created_at LIMIT 1""",(n,job_type)).fetchone()
            elif production_paused:
                row=c.execute("""SELECT * FROM pipeline_jobs WHERE status IN ('queued','failed_retriable')
                  AND available_at<=? AND attempt<max_attempts
                  AND job_type!='short_video_production'
                  ORDER BY priority,created_at LIMIT 1""",(n,)).fetchone()
            else:
                row=c.execute("""SELECT * FROM pipeline_jobs WHERE status IN ('queued','failed_retriable')
                  AND available_at<=? AND attempt<max_attempts
                  ORDER BY priority,created_at LIMIT 1""",(n,)).fetchone()
            if row is None: c.commit(); return None
            c.execute("""UPDATE pipeline_jobs SET status='running',worker_id=?,lease_token=?,lease_expires_at=?,
              attempt=attempt+1,started_at=COALESCE(started_at,?),updated_at=?,error_code=NULL,error_message=NULL
              WHERE id=? AND status=?""",(worker_id,token,expiry,n,n,row["id"],row["status"]))
            claimed=c.execute("SELECT * FROM pipeline_jobs WHERE id=?",(row["id"],)).fetchone()
            self.event(c,row["id"],"claimed",row["status"],"running",worker_id,{"attempt":claimed["attempt"],"lease_expires_at":expiry})
            c.commit(); return self.decode(claimed)

    def assert_lease(self,row,worker,token,n):
        if row is None: raise JobNotFound()
        if row["status"]!="running" or row["worker_id"]!=worker or row["lease_token"]!=token or not row["lease_expires_at"] or row["lease_expires_at"]<=n:
            raise LeaseConflict("Lease expired or no longer owned by this worker")

    def heartbeat(self,jid,worker,token):
        dt=now(); n=stamp(dt); expiry=stamp(dt+timedelta(seconds=self.lease_seconds))
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            row=c.execute("SELECT * FROM pipeline_jobs WHERE id=?",(jid,)).fetchone(); self.assert_lease(row,worker,token,n)
            c.execute("UPDATE pipeline_jobs SET lease_expires_at=?,updated_at=? WHERE id=?",(expiry,n,jid))
            c.execute("UPDATE worker_registry SET last_seen_at=? WHERE worker_id=?",(n,worker))
            self.event(c,jid,"heartbeat","running","running",worker,{"lease_expires_at":expiry})
            out=c.execute("SELECT * FROM pipeline_jobs WHERE id=?",(jid,)).fetchone(); c.commit(); return self.decode(out)

    def finish(self,jid,worker,token,result=None):
        n=stamp(now())
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE"); row=c.execute("SELECT * FROM pipeline_jobs WHERE id=?",(jid,)).fetchone()
            self.assert_lease(row,worker,token,n)
            c.execute("""UPDATE pipeline_jobs SET status='review_pending',worker_id=NULL,lease_token=NULL,
              lease_expires_at=NULL,completed_at=?,updated_at=? WHERE id=?""",(n,n,jid))
            self.event(c,jid,"completed","running","review_pending",worker,{"result":result or {}})
            out=c.execute("SELECT * FROM pipeline_jobs WHERE id=?",(jid,)).fetchone(); c.commit(); return self.decode(out)

    def fail(self,jid,worker,token,error_code,error_message,retryable=True):
        n=stamp(now())
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE"); row=c.execute("SELECT * FROM pipeline_jobs WHERE id=?",(jid,)).fetchone()
            self.assert_lease(row,worker,token,n)
            retry=bool(retryable and row["attempt"]<row["max_attempts"]); status="failed_retriable" if retry else "failed_terminal"
            c.execute("""UPDATE pipeline_jobs SET status=?,worker_id=NULL,lease_token=NULL,lease_expires_at=NULL,
              available_at=?,updated_at=?,error_code=?,error_message=? WHERE id=?""",(status,n,n,error_code,error_message[:2000],jid))
            self.event(c,jid,"failed","running",status,worker,{"error_code":error_code,"retryable":retry})
            out=c.execute("SELECT * FROM pipeline_jobs WHERE id=?",(jid,)).fetchone(); c.commit(); return self.decode(out)

    def list_jobs(self, job_type=None, limit=50, offset=0, status=None):
        """Return bounded, metadata-only queue rows for read-only operator dashboards."""
        limit = max(1, min(int(limit), 100))
        offset = max(0, int(offset))
        clauses = []
        params = []
        if job_type:
            clauses.append("job_type=?")
            params.append(str(job_type))
        if status:
            clauses.append("status=?")
            params.append(str(status))
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self.db() as c:
            total = c.execute("SELECT COUNT(*) FROM pipeline_jobs" + where, params).fetchone()[0]
            rows = c.execute(
                """SELECT id,job_type,channel_name,status,priority,attempt,max_attempts,
                   available_at,worker_id,lease_expires_at,error_code,error_message,
                   created_at,updated_at,started_at,completed_at
                   FROM pipeline_jobs""" + where +
                " ORDER BY updated_at DESC,created_at DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
            counts = c.execute(
                "SELECT status,COUNT(*) AS count FROM pipeline_jobs" + where + " GROUP BY status",
                params,
            ).fetchall()
        return {
            "items": [dict(row) for row in rows],
            "total": int(total),
            "limit": limit,
            "offset": offset,
            "status_counts": {row["status"]: int(row["count"]) for row in counts},
        }

    def lifecycle_summaries(self, job_ids):
        """Fetch compact lifecycle state for a page in one indexed read query.

        Deliberately excludes artifacts, payloads, event bodies, tokens and snapshots.
        """
        ids = list(dict.fromkeys(str(value) for value in (job_ids or []) if value))
        if not ids:
            return {}
        if len(ids) > 100:
            raise ValueError("At most 100 job IDs may be summarized")
        placeholders = ",".join("?" for _ in ids)
        sql = f"""
            SELECT q.id AS job_id,
                   p.status AS production_status,
                   p.current_stage AS current_stage,
                   p.brand AS brand,
                   p.topic AS topic,
                   (SELECT r.decision FROM review_decisions r
                    WHERE r.job_id=q.id ORDER BY r.id DESC LIMIT 1) AS latest_review_decision,
                   y.status AS youtube_status,
                   y.attempt_id AS youtube_attempt_id,
                   y.video_id AS youtube_video_id,
                   EXISTS(SELECT 1 FROM youtube_upload_events ye
                          WHERE ye.job_id=q.id AND ye.event_type='upload_attempt_started')
                       AS youtube_attempt_started,
                   t.status AS tiktok_status,
                   t.attempt_id AS tiktok_attempt_id,
                   t.video_id AS tiktok_video_id,
                   EXISTS(SELECT 1 FROM tiktok_publication_events te
                          WHERE te.job_id=q.id AND te.event_type IN
                          ('operator_consent_recorded','publish_initialization_started',
                           'publication_attempt_started'))
                       AS tiktok_attempt_started
            FROM pipeline_jobs q
            LEFT JOIN production_runs p ON p.job_id=q.id
            LEFT JOIN youtube_uploads y ON y.job_id=q.id
            LEFT JOIN tiktok_publications t ON t.job_id=q.id
            WHERE q.id IN ({placeholders})
        """
        with self.db() as c:
            rows = c.execute(sql, ids).fetchall()
        return {row["job_id"]: {
            **dict(row),
            "youtube_events": ([{"event_type": "upload_attempt_started"}]
                               if row["youtube_attempt_started"] else []),
            "tiktok_events": ([{"event_type": "publication_attempt_started"}]
                              if row["tiktok_attempt_started"] else []),
        } for row in rows}

    def get(self,jid):
        with self.db() as c:
            row=c.execute("SELECT * FROM pipeline_jobs WHERE id=?",(jid,)).fetchone()
            if row is None: raise JobNotFound()
            return self.decode(row)

    def events(self,jid):
        with self.db() as c:
            return [{**dict(r),"details":json.loads(r["details_json"])} for r in c.execute("SELECT * FROM job_events WHERE job_id=? ORDER BY id",(jid,))]

    def cancel(self,jid,reason="Cancelled by operator"):
        n=stamp(now())
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            row=c.execute("SELECT * FROM pipeline_jobs WHERE id=?",(jid,)).fetchone()
            if row is None: raise JobNotFound()
            if row["status"] in ("uploaded","cancelled","failed_terminal"):
                raise ValueError("Job is already terminal")
            is_production = row["job_type"] == "short_video_production"
            if is_production and row["status"] not in ("queued","failed_retriable","running","review_pending"):
                raise ValueError("Production jobs can only be cancelled before review handoff")
            production_table = c.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='production_runs'"
            ).fetchone()
            production = None
            if is_production and production_table:
                production = c.execute(
                    "SELECT status FROM production_runs WHERE job_id=?", (jid,)
                ).fetchone()
                if production and production["status"] in ("approved","uploaded"):
                    raise ValueError("Approved or uploaded production cannot be cancelled")
            if row["status"] == "review_pending" and (
                not production_table or production is None or production["status"] != "rendered"
            ):
                raise ValueError("Production has already completed the review handoff")
            ambiguous = is_production and row["status"] == "running"
            error_code = "cancelled_external_outcome_ambiguous" if ambiguous else "cancelled"
            error_message = (
                "Production cancelled while a provider request may be in flight; "
                "external outcome must be reconciled manually before any retry"
                if ambiguous else str(reason)[:2000]
            )
            c.execute("""UPDATE pipeline_jobs SET status='cancelled',worker_id=NULL,lease_token=NULL,
              lease_expires_at=NULL,updated_at=?,error_code=?,error_message=? WHERE id=?""",
              (n,error_code,error_message,jid))
            if is_production and production_table and production:
                stage = "cancelled_ambiguous" if ambiguous else "cancelled"
                c.execute("""UPDATE production_runs SET status='cancelled',
                    current_stage=?,error=?,updated_at=?
                    WHERE job_id=? AND status NOT IN ('approved','uploaded')""",
                    (stage,error_message,n,jid))
            self.event(c,jid,"cancelled",row["status"],"cancelled",None,
                       {"reason":str(reason)[:2000],"external_outcome_ambiguous":ambiguous})
            if ambiguous:
                self._pause_production_in_transaction(
                    c, "Production cancellation occurred during provider execution; external outcome is ambiguous",
                    jid, n, actor="system"
                )
            out=c.execute("SELECT * FROM pipeline_jobs WHERE id=?",(jid,)).fetchone()
            c.commit()
            return self.decode(out)

    def recover(self):
        n=stamp(now()); recovered=0; terminal=0
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            rows=c.execute("""SELECT id,job_type,attempt,max_attempts FROM pipeline_jobs WHERE status='running'
              AND lease_expires_at IS NOT NULL AND lease_expires_at<=?""",(n,)).fetchall()
            production_expired = []
            for row in rows:
                ambiguous = row["job_type"] == "short_video_production"
                target = "failed_terminal" if ambiguous or row["attempt"]>=row["max_attempts"] else "queued"
                code = "production_lease_expired_ambiguous" if ambiguous else "lease_expired"
                message = "Production lease expired; external provider outcome is ambiguous" if ambiguous else "Worker lease expired"
                c.execute("""UPDATE pipeline_jobs SET status=?,worker_id=NULL,lease_token=NULL,
                  lease_expires_at=NULL,available_at=?,updated_at=?,error_code=?,error_message=? WHERE id=?""",
                  (target,n,n,code,message,row["id"]))
                self.event(c,row["id"],"lease_recovered","running",target,None,
                           {"attempt":row["attempt"],"ambiguous_external_work":ambiguous})
                if ambiguous:
                    production_expired.append(row["id"])
                    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='production_runs'").fetchone():
                        c.execute("""UPDATE production_runs SET status='failed_terminal',
                            current_stage='lease_expired_ambiguous',error=?,updated_at=?
                            WHERE job_id=? AND status NOT IN ('approved','uploaded')""",
                            (message,n,row["id"]))
                if target=="queued": recovered+=1
                else: terminal+=1
            if production_expired:
                self._pause_production_in_transaction(c,
                    "Production worker lease expired; provider result may be ambiguous",
                    production_expired[0], n)
            c.commit()
        return {"requeued":recovered,"terminal":terminal}

    def pause(self, reason, job_id=None, actor="system"):
        """Persist a production pause, fence in-flight leases, and audit the action."""
        n=stamp(now())
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            self._pause_production_in_transaction(c, reason, job_id, n, actor)
            c.commit()
            return self.worker_control()

    def resume(self, actor="operator", note="Operator confirmed recovery checks"):
        """Explicitly resume after operator investigation and record the decision."""
        actor = str(actor).strip()[:128]
        note = str(note).strip()[:2000]
        if not actor or not note:
            raise ValueError("operator_id and resume note are required")
        n=stamp(now())
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            row=c.execute("SELECT paused,pause_reason,paused_job_id FROM worker_control WHERE id=1").fetchone()
            if not row or not row["paused"]:
                raise ValueError("Production queue is not paused")
            prior_reason = row["pause_reason"] or ""
            paused_job_id = row["paused_job_id"]
            c.execute("""UPDATE worker_control SET paused=0,pause_reason=NULL,
              paused_job_id=NULL,updated_at=? WHERE id=1""", (n,))
            c.execute("""INSERT INTO worker_control_events
              (event_type,actor,reason,paused_job_id,created_at)
              VALUES('resumed',?,?,?,?)""",
              (actor, ("Resume note: " + note + " | Previous pause: " + prior_reason)[:2000],
               paused_job_id, n))
            c.commit()
            return self.worker_control()

    def worker_control_events(self, limit=20):
        with self.db() as c:
            rows=c.execute("""SELECT id,event_type,actor,reason,paused_job_id,created_at
              FROM worker_control_events ORDER BY id DESC LIMIT ?""",
              (max(1,min(int(limit),100)),)).fetchall()
            return [dict(row) for row in rows]
    def worker_control(self):
        with self.db() as c:
            row=c.execute("SELECT * FROM worker_control WHERE id=1").fetchone()
            return dict(row) if row else {"paused": 0, "pause_reason": None,
                                           "paused_job_id": None}

    def is_paused(self):
        return bool(self.worker_control()["paused"])

    def register_worker(self, worker_id, hostname=None):
        if not str(worker_id).strip():
            raise ValueError("worker_id required")
        n = stamp(now())
        with self.db() as c:
            c.execute("""INSERT INTO worker_registry(worker_id,hostname,last_seen_at,status)
                VALUES(?,?,?,'online') ON CONFLICT(worker_id) DO UPDATE SET
                hostname=excluded.hostname,last_seen_at=excluded.last_seen_at,status='online'""",
                (worker_id, hostname, n))
        return {"worker_id": worker_id, "hostname": hostname,
                "last_seen_at": n, "status": "online"}

    def mark_worker_offline(self, worker_id):
        """Persist a graceful worker shutdown; stale heartbeats still cover hard crashes."""
        worker_id = str(worker_id or "").strip()
        if not worker_id:
            raise ValueError("worker_id required")
        with self.db() as c:
            updated = c.execute(
                "UPDATE worker_registry SET last_seen_at=?,status='offline' WHERE worker_id=?",
                (stamp(now()), worker_id),
            )
            return updated.rowcount == 1

    def workers(self, stale_after_seconds=None):
        threshold = max(30, int(stale_after_seconds or self.lease_seconds))
        cutoff = stamp(now() - timedelta(seconds=threshold))
        with self.db() as c:
            rows = [dict(r) for r in c.execute(
                "SELECT * FROM worker_registry ORDER BY last_seen_at DESC")]
        for row in rows:
            if row["last_seen_at"] < cutoff:
                row["status"] = "offline"
        return rows

    def operational_health(self):
        """Read-only operational safety snapshot; never requeues, pauses or contacts providers."""
        current = stamp(now())
        stale_cutoff = stamp(now() - timedelta(seconds=max(30, self.lease_seconds)))
        with self.db() as c:
            status_rows = c.execute(
                "SELECT status,COUNT(*) AS n FROM pipeline_jobs GROUP BY status"
            ).fetchall()
            control = c.execute(
                "SELECT paused,pause_reason,paused_job_id,updated_at FROM worker_control WHERE id=1"
            ).fetchone()
            expired = c.execute("""SELECT COUNT(*) AS n FROM pipeline_jobs
                WHERE status='running' AND lease_expires_at IS NOT NULL
                  AND lease_expires_at<=?""", (current,)).fetchone()["n"]
            missing_lease = c.execute("""SELECT COUNT(*) AS n FROM pipeline_jobs
                WHERE status='running' AND
                  (worker_id IS NULL OR worker_id='' OR lease_token IS NULL OR lease_token=''
                   OR lease_expires_at IS NULL OR lease_expires_at='')""").fetchone()["n"]
            worker_rows = c.execute("""SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status='online' AND last_seen_at>=? THEN 1 ELSE 0 END) AS online,
                SUM(CASE WHEN status='online' AND last_seen_at<? THEN 1 ELSE 0 END) AS stale
                FROM worker_registry""", (stale_cutoff, stale_cutoff)).fetchone()
        statuses = {row["status"]: row["n"] for row in status_rows}
        control = dict(control) if control else {
            "paused": 0, "pause_reason": None, "paused_job_id": None, "updated_at": None
        }
        blockers = []
        warnings = []
        if control["paused"]:
            blockers.append({"code":"production_queue_paused","message":"Production queue is paused"})
        if expired:
            blockers.append({"code":"worker_lease_expired","message":"One or more running jobs have expired worker leases","count":expired})
        if missing_lease:
            blockers.append({"code":"worker_lease_incomplete","message":"One or more running jobs have incomplete lease ownership fields","count":missing_lease})
        stale_workers = int(worker_rows["stale"] or 0)
        if stale_workers:
            warnings.append({"code":"workers_stale","message":"One or more registered workers have stale heartbeats","count":stale_workers})
        retryable = int(statuses.get("failed_retriable", 0))
        if retryable:
            warnings.append({"code":"retryable_failures","message":"Jobs are waiting for an eligible retry","count":retryable})
        return {
            "status": "blocked" if blockers else ("attention_required" if warnings else "healthy"),
            "checked_at": current,
            "read_only": True,
            "queue": {"total":sum(statuses.values()),"status_counts":statuses,
                      "paused":bool(control["paused"])},
            "workers": {"total":int(worker_rows["total"] or 0),
                        "online":int(worker_rows["online"] or 0),"stale":stale_workers,
                        "stale_after_seconds":max(30,self.lease_seconds)},
            "leases": {"expired_running":int(expired),"running_missing_ownership":int(missing_lease)},
            "control": control,
            "blockers": blockers,
            "warnings": warnings,
            "actions_taken": [],
        }

    def stats(self):
        with self.db() as c:
            d={r["status"]:r["n"] for r in c.execute("SELECT status,COUNT(*) n FROM pipeline_jobs GROUP BY status")}
            d["total"]=sum(d.values()); return d
