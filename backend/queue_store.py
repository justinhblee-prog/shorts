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
                if old: c.commit(); return self.decode(old)
            c.execute("""INSERT INTO pipeline_jobs(id,job_type,channel_name,payload_json,status,priority,max_attempts,available_at,idempotency_key,created_at,updated_at)
              VALUES(?,?,?,?, 'queued',?,?,?,?,?,?)""",
              (jid,job_type,channel_name,json.dumps(payload,ensure_ascii=False),int(priority),max(1,int(max_attempts)),n,idempotency_key,n,n))
            self.event(c,jid,"enqueued",None,"queued",None)
            row=c.execute("SELECT * FROM pipeline_jobs WHERE id=?",(jid,)).fetchone(); c.commit()
            return self.decode(row)

    def claim(self,worker_id,hostname=None,job_type=None):
        if not worker_id.strip(): raise ValueError("worker_id required")
        dt=now(); n=stamp(dt); expiry=stamp(dt+timedelta(seconds=self.lease_seconds)); token=str(uuid.uuid4())
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute("""INSERT INTO worker_registry VALUES(?,?,?,'online') ON CONFLICT(worker_id)
              DO UPDATE SET hostname=excluded.hostname,last_seen_at=excluded.last_seen_at,status='online'""",(worker_id,hostname,n))
            expired=c.execute("""SELECT id,attempt,max_attempts FROM pipeline_jobs WHERE status='running'
              AND lease_expires_at IS NOT NULL AND lease_expires_at<=?""",(n,)).fetchall()
            for e in expired:
                target="queued" if e["attempt"]<e["max_attempts"] else "failed_terminal"
                c.execute("""UPDATE pipeline_jobs SET status=?,worker_id=NULL,lease_token=NULL,lease_expires_at=NULL,
                  available_at=?,updated_at=?,error_code='lease_expired',error_message='Worker lease expired' WHERE id=?""",(target,n,n,e["id"]))
                self.event(c,e["id"],"lease_expired","running",target,None,{"attempt":e["attempt"]})
            if job_type:
                row=c.execute("""SELECT * FROM pipeline_jobs WHERE status IN ('queued','failed_retriable')
                  AND available_at<=? AND attempt<max_attempts AND job_type=?
                  ORDER BY priority,created_at LIMIT 1""",(n,job_type)).fetchone()
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
            c.execute("""UPDATE pipeline_jobs SET status='cancelled',worker_id=NULL,lease_token=NULL,
              lease_expires_at=NULL,updated_at=?,error_code='cancelled',error_message=? WHERE id=?""",
              (n,reason[:2000],jid))
            self.event(c,jid,"cancelled",row["status"],"cancelled",None,{"reason":reason})
            out=c.execute("SELECT * FROM pipeline_jobs WHERE id=?",(jid,)).fetchone()
            c.commit()
            return self.decode(out)

    def recover(self):
        n=stamp(now()); recovered=0; terminal=0
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            rows=c.execute("""SELECT id,attempt,max_attempts FROM pipeline_jobs WHERE status='running'
              AND lease_expires_at IS NOT NULL AND lease_expires_at<=?""",(n,)).fetchall()
            for row in rows:
                target="queued" if row["attempt"]<row["max_attempts"] else "failed_terminal"
                c.execute("""UPDATE pipeline_jobs SET status=?,worker_id=NULL,lease_token=NULL,
                  lease_expires_at=NULL,available_at=?,updated_at=?,error_code='lease_expired',
                  error_message='Worker lease expired' WHERE id=?""",(target,n,n,row["id"]))
                self.event(c,row["id"],"lease_recovered","running",target,None,{"attempt":row["attempt"]})
                if target=="queued": recovered+=1
                else: terminal+=1
            c.commit()
        return {"requeued":recovered,"terminal":terminal}

    def pause(self, reason, job_id=None):
        """Persist a global production-worker pause until an explicit operator resume."""
        n=stamp(now())
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute("""UPDATE worker_control SET paused=1,pause_reason=?,
              paused_job_id=?,updated_at=? WHERE id=1""",
              (str(reason)[:2000], job_id, n))
            c.commit()
            return self.worker_control()

    def resume(self):
        """Explicitly clear a persisted worker pause after operator investigation."""
        n=stamp(now())
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute("""UPDATE worker_control SET paused=0,pause_reason=NULL,
              paused_job_id=NULL,updated_at=? WHERE id=1""", (n,))
            c.commit()
            return self.worker_control()

    def worker_control(self):
        with self.db() as c:
            row=c.execute("SELECT * FROM worker_control WHERE id=1").fetchone()
            return dict(row) if row else {"paused": 0, "pause_reason": None,
                                           "paused_job_id": None}

    def is_paused(self):
        return bool(self.worker_control()["paused"])

    def workers(self):
        with self.db() as c:
            return [dict(r) for r in c.execute("SELECT * FROM worker_registry ORDER BY last_seen_at DESC")]

    def stats(self):
        with self.db() as c:
            d={r["status"]:r["n"] for r in c.execute("SELECT status,COUNT(*) n FROM pipeline_jobs GROUP BY status")}
            d["total"]=sum(d.values()); return d
