"""Persistent interval scheduler with idempotent queue dispatch."""
import json,sqlite3,uuid
from contextlib import contextmanager
from datetime import datetime,timezone,timedelta
from pathlib import Path


def _dt(value):
    return datetime.fromisoformat(value.replace("Z","+00:00"))
def _stamp(value): return value.astimezone(timezone.utc).isoformat()
class ScheduleStore:
    def __init__(self,db_path="data/nexus.sqlite3"):
        self.db_path=str(db_path); Path(self.db_path).parent.mkdir(parents=True,exist_ok=True)
        with self.db() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS production_schedules(
              id TEXT PRIMARY KEY, name TEXT NOT NULL, interval_seconds INTEGER NOT NULL,
              payload_json TEXT NOT NULL, next_run_at TEXT NOT NULL,
              active INTEGER NOT NULL DEFAULT 1, last_enqueued_at TEXT,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_schedule_due
              ON production_schedules(active,next_run_at);
            """)
    @contextmanager
    def db(self):
        c=sqlite3.connect(self.db_path,timeout=30); c.row_factory=sqlite3.Row
        c.execute("PRAGMA busy_timeout=30000")
        try: yield c; c.commit()
        except Exception: c.rollback(); raise
        finally: c.close()
    def create(self,name,interval_seconds,payload,start_at=None):
        if not name.strip(): raise ValueError("schedule name is required")
        interval=int(interval_seconds)
        if interval<3600: raise ValueError("minimum schedule interval is one hour")
        now=datetime.now(timezone.utc); start=_dt(start_at) if start_at else now
        if start.tzinfo is None: raise ValueError("start_at must include timezone")
        sid=str(uuid.uuid4()); stamp=_stamp(now); due=_stamp(start)
        with self.db() as c:
            c.execute("""INSERT INTO production_schedules
              (id,name,interval_seconds,payload_json,next_run_at,active,created_at,updated_at)
              VALUES(?,?,?,?,?,1,?,?)""",
              (sid,name.strip(),interval,json.dumps(payload,ensure_ascii=False),due,stamp,stamp))
            return self.get(sid,c)
    def get(self,sid,c=None):
        if c is not None:
            row=c.execute("SELECT * FROM production_schedules WHERE id=?",(sid,)).fetchone()
            return self._decode(row)
        with self.db() as db:return self.get(sid,db)
    @staticmethod
    def _decode(row):
        if row is None:return None
        d=dict(row); d["payload"]=json.loads(d.pop("payload_json")); d["active"]=bool(d["active"]);return d
    def list(self):
        with self.db() as c:
            return [self._decode(r) for r in c.execute(
                "SELECT * FROM production_schedules ORDER BY created_at DESC")]
    def set_active(self,sid,active):
        with self.db() as c:
            cur=c.execute("UPDATE production_schedules SET active=?,updated_at=? WHERE id=?",
                          (int(bool(active)),_stamp(datetime.now(timezone.utc)),sid))
            if not cur.rowcount: return None
            return self.get(sid,c)
    def dispatch_due(self,queue,now=None,limit=20):
        current=now or datetime.now(timezone.utc)
        if current.tzinfo is None: raise ValueError("now must be timezone-aware")
        current_s=_stamp(current); dispatched=[]
        with self.db() as c:
            rows=c.execute("""SELECT * FROM production_schedules
              WHERE active=1 AND next_run_at<=? ORDER BY next_run_at LIMIT ?""",
              (current_s,max(1,min(int(limit),100)))).fetchall()
        for row in rows:
            due=row["next_run_at"]; payload=json.loads(row["payload_json"])
            job=queue.enqueue("short_video_production",payload,
                channel_name=payload["brand"],
                idempotency_key="schedule:"+row["id"]+":"+due)
            due_dt=_dt(due); interval=timedelta(seconds=row["interval_seconds"])
            next_due=due_dt+interval
            while next_due<=current: next_due+=interval
            with self.db() as c:
                c.execute("""UPDATE production_schedules SET next_run_at=?,last_enqueued_at=?,
                  updated_at=? WHERE id=? AND next_run_at=?""",
                  (_stamp(next_due),current_s,current_s,row["id"],due))
            dispatched.append({"schedule_id":row["id"],"job":job,"scheduled_for":due})
        return {"dispatched":dispatched,"count":len(dispatched)}
