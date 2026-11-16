"""Durable SQLite queue with lease fencing."""
import json, sqlite3, uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc)

def stamp(value):
    return value.astimezone(timezone.utc).isoformat()


def _lease_seconds(value, minimum):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > 3600:
        raise ValueError("lease_seconds must be an integer from 1 to 3600")
    return max(minimum, value)


class LeaseConflict(Exception): pass
class JobNotFound(Exception): pass
class IdempotencyConflict(ValueError): pass


class JobQueue:
    def __init__(self, db_path="data/nexus.sqlite3", lease_seconds=90):
        self.db_path=str(db_path)
        self.lease_seconds=_lease_seconds(lease_seconds, 10)
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
              worker_id TEXT PRIMARY KEY, hostname TEXT, last_seen_at TEXT NOT NULL,
              status TEXT NOT NULL, generation_token TEXT);
            CREATE INDEX IF NOT EXISTS idx_worker_registry_generation
              ON worker_registry(worker_id,generation_token);
            CREATE TABLE IF NOT EXISTS worker_control(
              id INTEGER PRIMARY KEY CHECK(id=1), paused INTEGER NOT NULL DEFAULT 0,
              pause_reason TEXT, paused_job_id TEXT, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS worker_control_events(
              id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL,
              actor TEXT NOT NULL, reason TEXT NOT NULL, paused_job_id TEXT,
              created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS production_reconciliation_events(
              id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
              outcome TEXT NOT NULL, operator_id TEXT NOT NULL,
              evidence_reference TEXT NOT NULL, note TEXT NOT NULL,
              previous_status TEXT NOT NULL, resulting_status TEXT NOT NULL,
              created_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_production_reconciliation_job
              ON production_reconciliation_events(job_id,id);
            CREATE TRIGGER IF NOT EXISTS production_reconciliation_no_update
              BEFORE UPDATE ON production_reconciliation_events
              BEGIN SELECT RAISE(ABORT,'production reconciliation events are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS production_reconciliation_no_delete
              BEFORE DELETE ON production_reconciliation_events
              BEGIN SELECT RAISE(ABORT,'production reconciliation events are immutable'); END;
            INSERT OR IGNORE INTO worker_control(id,paused,updated_at)
              VALUES(1,0,'1970-01-01T00:00:00+00:00');
            """)
            worker_columns = {row["name"] for row in c.execute("PRAGMA table_info(worker_registry)")}
            if "generation_token" not in worker_columns:
                c.execute("ALTER TABLE worker_registry ADD COLUMN generation_token TEXT")

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
                updated_at=?,error_code='production_pause_external_outcome_ambiguous',error_message=?
                WHERE id=? AND status='running'""",
                (timestamp, ("Production paused while provider outcome may be in flight: " + reason)[:2000], row["id"]))
            self.event(c, row["id"], "worker_pause", "running", "failed_terminal",
                       row["worker_id"], {"reason": reason, "paused_job_id": job_id})
            if has_runs:
                c.execute("""UPDATE production_runs SET status='failed_terminal',
                    current_stage='pause_outcome_ambiguous',error=?,updated_at=?
                    WHERE job_id=? AND status NOT IN ('approved','uploaded')""",
                    (("Production paused; external outcome requires reconciliation: " + reason)[:2000], timestamp, row["id"]))
    def _recover_expired_leases_in_transaction(self, c, timestamp):
        """Resolve expired leases consistently in claim and periodic recovery.

        Production work is never replayed automatically: a provider request may
        have completed before its worker lost the lease. Caller owns the
        BEGIN IMMEDIATE transaction and pauses production after this helper.
        """
        rows = c.execute("""SELECT id,job_type,attempt,max_attempts,worker_id
            FROM pipeline_jobs
            WHERE status='running' AND lease_expires_at IS NOT NULL
              AND lease_expires_at<=?
            ORDER BY lease_expires_at,id""", (timestamp,)).fetchall()
        requeued = terminal = 0
        production_expired = []
        has_production_runs = c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='production_runs'"
        ).fetchone() is not None
        for row in rows:
            ambiguous = row["job_type"] == "short_video_production"
            target = ("failed_terminal" if ambiguous or row["attempt"] >= row["max_attempts"]
                      else "queued")
            code = ("production_lease_expired_ambiguous" if ambiguous else "lease_expired")
            message = ("Production lease expired; external provider outcome is ambiguous"
                       if ambiguous else "Worker lease expired")
            updated = c.execute("""UPDATE pipeline_jobs SET status=?,worker_id=NULL,lease_token=NULL,
                lease_expires_at=NULL,available_at=?,updated_at=?,error_code=?,error_message=?
                WHERE id=? AND status='running' AND lease_expires_at<=?""",
                (target, timestamp, timestamp, code, message, row["id"], timestamp))
            if updated.rowcount != 1:
                continue
            self.event(c, row["id"], "lease_expired", "running", target, row["worker_id"],
                       {"attempt": row["attempt"], "expired_worker_id": row["worker_id"],
                        "ambiguous_external_work": ambiguous,
                        "resolution": "manual_reconciliation_required" if ambiguous else
                                     ("retry_available" if target == "queued" else "attempts_exhausted")})
            if ambiguous:
                production_expired.append(row["id"])
                if has_production_runs:
                    c.execute("""UPDATE production_runs SET status='failed_terminal',
                        current_stage='lease_expired_ambiguous',error=?,updated_at=?
                        WHERE job_id=? AND status NOT IN ('approved','uploaded')""",
                        (message, timestamp, row["id"]))
            if target == "queued":
                requeued += 1
            else:
                terminal += 1
        return {"requeued": requeued, "terminal": terminal,
                "production_expired": production_expired}

    @staticmethod
    def _assert_worker_generation(c, worker_id, generation_token):
        row = c.execute(
            "SELECT generation_token,status FROM worker_registry WHERE worker_id=?",
            (worker_id,),
        ).fetchone()
        # Preserve the unregistered legacy/test path, but once a worker ID is
        # registered every process-originated mutation must prove its generation.
        if row is None:
            if generation_token is not None:
                raise LeaseConflict("Worker process generation is no longer current")
            return
        # Older queue clients that never registered a process generation keep
        # their legacy lease path. A registered process (non-null token) must
        # always present the exact current token; omission cannot bypass fencing.
        if row["generation_token"] is None and generation_token is None:
            return
        if (generation_token is None or row["generation_token"] != generation_token
                or row["status"] != "online"):
            raise LeaseConflict("Worker process generation is no longer current")

    def claim(self,worker_id,hostname=None,job_type=None,generation_token=None):
        if not worker_id.strip(): raise ValueError("worker_id required")
        token=str(uuid.uuid4())
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            dt=now(); n=stamp(dt); expiry=stamp(dt+timedelta(seconds=self.lease_seconds))
            self._assert_worker_generation(c, worker_id, generation_token)
            control=c.execute("SELECT paused FROM worker_control WHERE id=1").fetchone()
            production_paused=bool(control and control["paused"])
            if production_paused and job_type == "short_video_production":
                c.commit()
                return None
            registry_generation = generation_token
            c.execute("""INSERT INTO worker_registry(
              worker_id,hostname,last_seen_at,status,generation_token)
              VALUES(?,?,?,'online',?) ON CONFLICT(worker_id)
              DO UPDATE SET hostname=excluded.hostname,last_seen_at=excluded.last_seen_at,
              status='online'""",(worker_id,hostname,n,registry_generation))
            expiry_result = self._recover_expired_leases_in_transaction(c, n)
            production_expired = expiry_result["production_expired"]
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

    def heartbeat(self,jid,worker,token,generation_token=None):
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            dt=now(); n=stamp(dt); expiry=stamp(dt+timedelta(seconds=self.lease_seconds))
            self._assert_worker_generation(c, worker, generation_token)
            row=c.execute("SELECT * FROM pipeline_jobs WHERE id=?",(jid,)).fetchone(); self.assert_lease(row,worker,token,n)
            c.execute("UPDATE pipeline_jobs SET lease_expires_at=?,updated_at=? WHERE id=?",(expiry,n,jid))
            c.execute("UPDATE worker_registry SET last_seen_at=? WHERE worker_id=?",(n,worker))
            self.event(c,jid,"heartbeat","running","running",worker,{"lease_expires_at":expiry})
            out=c.execute("SELECT * FROM pipeline_jobs WHERE id=?",(jid,)).fetchone(); c.commit(); return self.decode(out)

    def finish(self,jid,worker,token,result=None,generation_token=None):
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE"); n=stamp(now())
            self._assert_worker_generation(c, worker, generation_token)
            row=c.execute("SELECT * FROM pipeline_jobs WHERE id=?",(jid,)).fetchone()
            self.assert_lease(row,worker,token,n)
            c.execute("""UPDATE pipeline_jobs SET status='review_pending',worker_id=NULL,lease_token=NULL,
              lease_expires_at=NULL,completed_at=?,updated_at=? WHERE id=?""",(n,n,jid))
            self.event(c,jid,"completed","running","review_pending",worker,{"result":result or {}})
            out=c.execute("SELECT * FROM pipeline_jobs WHERE id=?",(jid,)).fetchone(); c.commit(); return self.decode(out)

    def fail(self,jid,worker,token,error_code,error_message,retryable=True,generation_token=None):
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE"); n=stamp(now())
            self._assert_worker_generation(c, worker, generation_token)
            row=c.execute("SELECT * FROM pipeline_jobs WHERE id=?",(jid,)).fetchone()
            self.assert_lease(row,worker,token,n)
            retry=bool(retryable and row["attempt"]<row["max_attempts"]); status="failed_retriable" if retry else "failed_terminal"
            c.execute("""UPDATE pipeline_jobs SET status=?,worker_id=NULL,lease_token=NULL,lease_expires_at=NULL,
              available_at=?,updated_at=?,error_code=?,error_message=? WHERE id=?""",(status,n,n,error_code,error_message[:2000],jid))
            self.event(c,jid,"failed","running",status,worker,{"error_code":error_code,"retryable":retry})
            out=c.execute("SELECT * FROM pipeline_jobs WHERE id=?",(jid,)).fetchone(); c.commit(); return self.decode(out)

    def get(self,jid):
        with self.db() as c:
            row=c.execute("SELECT * FROM pipeline_jobs WHERE id=?",(jid,)).fetchone()
            if row is None: raise JobNotFound()
            return self.decode(row)

    def events(self,jid):
        with self.db() as c:
            return [{**dict(r),"details":json.loads(r["details_json"])} for r in c.execute("SELECT * FROM job_events WHERE job_id=? ORDER BY id",(jid,))]

    def cancel(self,jid,reason="Cancelled by operator"):
        reason = str(reason)[:2000]
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            n=stamp(now())
            row=c.execute("SELECT * FROM pipeline_jobs WHERE id=?",(jid,)).fetchone()
            if row is None: raise JobNotFound()
            if row["status"] in ("uploaded","cancelled","failed_terminal"):
                raise ValueError("Job is already terminal")

            is_production = row["job_type"] == "short_video_production"
            if is_production and row["status"] not in (
                "queued", "failed_retriable", "running", "review_pending"
            ):
                raise ValueError("Production jobs can only be cancelled before review handoff")

            production_table = c.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='production_runs'"
            ).fetchone()
            production = None
            if is_production and production_table:
                production = c.execute(
                    "SELECT status FROM production_runs WHERE job_id=?", (jid,)
                ).fetchone()
                if production and production["status"] in ("approved", "uploaded"):
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
                if ambiguous else reason
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
                       {"reason":reason,"external_outcome_ambiguous":ambiguous})
            if ambiguous:
                self._pause_production_in_transaction(
                    c,
                    "Production cancellation occurred during provider execution; external outcome is ambiguous",
                    jid, n, actor="system",
                )
            out=c.execute("SELECT * FROM pipeline_jobs WHERE id=?",(jid,)).fetchone()
            c.commit()
            return self.decode(out)

    def ambiguous_production_jobs(self, limit=100):
        """List production jobs blocked because an external provider outcome is unknown."""
        bounded = max(1, min(int(limit), 200))
        with self.db() as c:
            rows = c.execute("""SELECT id,status,attempt,max_attempts,
                    error_code,error_message,updated_at
                FROM pipeline_jobs
                WHERE job_type='short_video_production'
                  AND (
                    (status='failed_terminal'
                     AND error_code IN (
                       'production_lease_expired_ambiguous',
                       'production_pause_external_outcome_ambiguous'
                     ))
                    OR
                    (status='cancelled'
                     AND error_code='cancelled_external_outcome_ambiguous')
                  )
                ORDER BY updated_at DESC,id LIMIT ?""", (bounded,)).fetchall()
            return [dict(row) for row in rows]

    def reconcile_production_retry(self, job_id, operator_id, evidence_reference, note):
        """Authorize exactly one new attempt only after an operator proves no side effect occurred.

        The global production pause is intentionally retained. Resuming the queue is a
        separate explicit control action after all affected work has been reviewed.
        """
        operator_id = str(operator_id or "").strip()
        evidence_reference = str(evidence_reference or "").strip()
        note = str(note or "").strip()
        if not operator_id or len(operator_id) > 128:
            raise ValueError("operator_id is required and must be at most 128 characters")
        if not evidence_reference or len(evidence_reference) > 1000:
            raise ValueError("evidence_reference is required and must be at most 1000 characters")
        if not note or len(note) > 2000:
            raise ValueError("note is required and must be at most 2000 characters")
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            timestamp = stamp(now())
            row = c.execute("""SELECT * FROM pipeline_jobs
                WHERE id=? AND job_type='short_video_production'""", (job_id,)).fetchone()
            if row is None:
                raise JobNotFound()
            expected_status = (
                "cancelled"
                if row["error_code"] == "cancelled_external_outcome_ambiguous"
                else "failed_terminal"
            )
            if (row["status"] != expected_status or row["error_code"] not in (
                "production_lease_expired_ambiguous",
                "cancelled_external_outcome_ambiguous",
                "production_pause_external_outcome_ambiguous",
            )):
                raise ValueError("Job is not awaiting ambiguous production reconciliation")
            previous_status = row["status"]
            next_attempt_ceiling = max(row["max_attempts"], row["attempt"] + 1)
            updated = c.execute("""UPDATE pipeline_jobs SET status='failed_retriable',
                max_attempts=?,available_at=?,updated_at=?,
                error_code='operator_reconciled_no_side_effect',error_message=?
                WHERE id=? AND status=? AND error_code=?""",
                (next_attempt_ceiling, timestamp, timestamp,
                 ("Operator confirmed no external side effect: " + note)[:2000],
                 job_id, expected_status, row["error_code"]))
            if updated.rowcount != 1:
                raise ValueError("Job state changed during reconciliation")
            has_runs = c.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='production_runs'"
            ).fetchone()
            if has_runs:
                c.execute("""UPDATE production_runs SET status='queued',
                    current_stage='operator_reconciled_retry_authorized',
                    error=?,updated_at=? WHERE job_id=?
                    AND status NOT IN ('approved','uploaded')""",
                    (("Operator authorized one retry: " + note)[:2000], timestamp, job_id))
            c.execute("""INSERT INTO production_reconciliation_events
                (job_id,outcome,operator_id,evidence_reference,note,
                 previous_status,resulting_status,created_at)
                VALUES(?,?,?,?,?,?,?,?)""",
                (job_id,"confirmed_no_external_side_effect",operator_id,
                 evidence_reference,note,previous_status,"failed_retriable",timestamp))
            self.event(c,job_id,"operator_reconciliation",previous_status,
                "failed_retriable",None,{
                    "outcome":"confirmed_no_external_side_effect",
                    "operator_id":operator_id,
                    "evidence_reference":evidence_reference,
                    "retry_attempt_ceiling":next_attempt_ceiling,
                })
            result = c.execute("SELECT * FROM pipeline_jobs WHERE id=?", (job_id,)).fetchone()
            c.commit()
            return self.decode(result)

    def production_reconciliation_events(self, job_id):
        with self.db() as c:
            return [dict(row) for row in c.execute("""SELECT * FROM
                production_reconciliation_events WHERE job_id=? ORDER BY id""",
                (job_id,)).fetchall()]

    def recover(self):
        recovered=0; terminal=0
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            n=stamp(now())
            expiry_result = self._recover_expired_leases_in_transaction(c, n)
            recovered = expiry_result["requeued"]
            terminal = expiry_result["terminal"]
            production_expired = expiry_result["production_expired"]
            if production_expired:
                self._pause_production_in_transaction(c,
                    "Production worker lease expired; provider result may be ambiguous",
                    production_expired[0], n)
            c.commit()
        return {"requeued":recovered,"terminal":terminal}

    def pause(self, reason, job_id=None, actor="system", worker_id=None,
              generation_token=None):
        """Persist a pause; worker-originated pauses are fenced by process generation."""
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            n=stamp(now())
            if worker_id is not None:
                self._assert_worker_generation(c, worker_id, generation_token)
            elif generation_token is not None:
                raise ValueError("worker_id required with generation_token")
            self._pause_production_in_transaction(c, reason, job_id, n, actor)
            c.commit()
            return self.worker_control()

    def resume(self, actor="operator", note="Operator confirmed recovery checks"):
        """Explicitly resume after operator investigation and record the decision."""
        actor = str(actor).strip()[:128]
        note = str(note).strip()[:2000]
        if not actor or not note:
            raise ValueError("operator_id and resume note are required")
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            n=stamp(now())
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
        """Register a process incarnation and return its fencing generation."""
        if not str(worker_id).strip():
            raise ValueError("worker_id required")
        generation_token = str(uuid.uuid4())
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            n = stamp(now())
            # Rotating a process generation invalidates the old worker's lease
            # writes, but the old process may still be inside an external provider
            # call. Quarantine any production work it still owns before allowing
            # the replacement generation to become active.
            active_production = c.execute("""SELECT id FROM pipeline_jobs
                WHERE worker_id=? AND job_type='short_video_production'
                  AND status='running'
                ORDER BY created_at,id LIMIT 1""", (worker_id,)).fetchone()
            if active_production:
                self._pause_production_in_transaction(
                    c,
                    "Production worker generation was replaced while a job remained active; external outcome is ambiguous",
                    active_production["id"], n, actor="system",
                )
            c.execute("""INSERT INTO worker_registry(
                worker_id,hostname,last_seen_at,status,generation_token)
                VALUES(?,?,?,'online',?) ON CONFLICT(worker_id) DO UPDATE SET
                hostname=excluded.hostname,last_seen_at=excluded.last_seen_at,
                status='online',generation_token=excluded.generation_token""",
                (worker_id, hostname, n, generation_token))
            c.commit()
        return {"worker_id": worker_id, "hostname": hostname,
                "last_seen_at": n, "status": "online",
                "generation_token": generation_token}

    def mark_worker_offline(self, worker_id, generation_token=None):
        """Only the current process generation may mark its registry row offline."""
        worker_id = str(worker_id or "").strip()
        if not worker_id:
            raise ValueError("worker_id required")
        if not generation_token:
            return False
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            n = stamp(now())
            updated = c.execute(
                """UPDATE worker_registry SET last_seen_at=?,status='offline'
                   WHERE worker_id=? AND generation_token=?""",
                (n, worker_id, generation_token),
            )
            c.commit()
            return updated.rowcount == 1

    def workers(self, stale_after_seconds=None):
        threshold = max(30, int(stale_after_seconds or self.lease_seconds))
        observed_at = now()
        with self.db() as c:
            rows = [dict(r) for r in c.execute(
                "SELECT * FROM worker_registry ORDER BY last_seen_at DESC")]
        for row in rows:
            try:
                last_seen = datetime.fromisoformat(row["last_seen_at"])
                age = max(0, int((observed_at - last_seen).total_seconds()))
            except (TypeError, ValueError, OverflowError):
                # A malformed registry timestamp is never treated as healthy.
                age = threshold + 1
            row["heartbeat_age_seconds"] = age
            row["stale_after_seconds"] = threshold
            if row["status"] == "online" and age > threshold:
                row["status"] = "stale"
        return rows

    def stats(self):
        with self.db() as c:
            d={r["status"]:r["n"] for r in c.execute("SELECT status,COUNT(*) n FROM pipeline_jobs GROUP BY status")}
            d["total"]=sum(d.values()); return d
