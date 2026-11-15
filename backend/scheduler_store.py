"""Persistent interval scheduler with recoverable outbox and idempotent dispatch."""
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path


def _dt(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _stamp(value):
    return value.astimezone(timezone.utc).isoformat()


class ScheduleStore:
    def __init__(self, db_path="data/nexus.sqlite3"):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
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
            CREATE TABLE IF NOT EXISTS schedule_dispatch_outbox(
              id TEXT PRIMARY KEY, schedule_id TEXT NOT NULL,
              scheduled_for TEXT NOT NULL, payload_json TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
              last_error TEXT, created_at TEXT NOT NULL, dispatched_at TEXT,
              UNIQUE(schedule_id,scheduled_for)
            );
            CREATE INDEX IF NOT EXISTS idx_schedule_outbox_pending
              ON schedule_dispatch_outbox(status,created_at);
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

    def create(self, name, interval_seconds, payload, start_at=None):
        if not name.strip():
            raise ValueError("schedule name is required")
        interval = int(interval_seconds)
        if interval < 3600:
            raise ValueError("minimum schedule interval is one hour")
        now = datetime.now(timezone.utc)
        start = _dt(start_at) if start_at else now
        if start.tzinfo is None:
            raise ValueError("start_at must include timezone")
        sid = str(uuid.uuid4())
        stamp, due = _stamp(now), _stamp(start)
        with self.db() as c:
            c.execute("""INSERT INTO production_schedules
              (id,name,interval_seconds,payload_json,next_run_at,active,created_at,updated_at)
              VALUES(?,?,?,?,?,1,?,?)""",
              (sid, name.strip(), interval, json.dumps(payload, ensure_ascii=False), due, stamp, stamp))
            return self.get(sid, c)

    def get(self, sid, c=None):
        if c is not None:
            row = c.execute("SELECT * FROM production_schedules WHERE id=?", (sid,)).fetchone()
            return self._decode(row)
        with self.db() as db:
            return self.get(sid, db)

    @staticmethod
    def _decode(row):
        if row is None:
            return None
        d = dict(row)
        d["payload"] = json.loads(d.pop("payload_json"))
        d["active"] = bool(d["active"])
        return d

    def list(self):
        with self.db() as c:
            return [self._decode(r) for r in c.execute(
                "SELECT * FROM production_schedules ORDER BY created_at DESC")]

    def set_active(self, sid, active):
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            cur = c.execute("UPDATE production_schedules SET active=?,updated_at=? WHERE id=?",
                            (int(bool(active)), _stamp(datetime.now(timezone.utc)), sid))
            if not cur.rowcount:
                return None
            return self.get(sid, c)

    def pending_dispatches(self, limit=100):
        with self.db() as c:
            rows = c.execute("""SELECT * FROM schedule_dispatch_outbox
                WHERE status='pending' ORDER BY created_at LIMIT ?""",
                (max(1, min(int(limit), 500)),)).fetchall()
            return [dict(row) for row in rows]


    def outbox_status(self, limit=20):
        with self.db() as c:
            counts = {row["status"]: row["n"] for row in c.execute(
                "SELECT status,COUNT(*) n FROM schedule_dispatch_outbox GROUP BY status")}
            rows = c.execute("""SELECT id,schedule_id,scheduled_for,status,attempts,
                last_error,created_at FROM schedule_dispatch_outbox
                ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END,
                created_at DESC LIMIT ?""", (max(1, min(int(limit), 100)),)).fetchall()
            return {"counts": counts, "items": [dict(row) for row in rows],
                    "pending_retries": counts.get("pending", 0)}

    def dispatch_due(self, queue, now=None, limit=20):
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        current_s = _stamp(current)
        # Reserve each due occurrence and persist an outbox item atomically.
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            rows = c.execute("""SELECT * FROM production_schedules
                WHERE active=1 AND next_run_at<=? ORDER BY next_run_at LIMIT ?""",
                (current_s, max(1, min(int(limit), 100)))).fetchall()
            for row in rows:
                due = row["next_run_at"]
                due_dt = _dt(due)
                interval = timedelta(seconds=row["interval_seconds"])
                next_due = due_dt + interval
                while next_due <= current:
                    next_due += interval
                outbox_id = str(uuid.uuid4())
                c.execute("""INSERT OR IGNORE INTO schedule_dispatch_outbox
                    (id,schedule_id,scheduled_for,payload_json,status,created_at)
                    VALUES(?,?,?,?,'pending',?)""",
                    (outbox_id, row["id"], due, row["payload_json"], current_s))
                c.execute("""UPDATE production_schedules SET next_run_at=?,updated_at=?
                    WHERE id=? AND next_run_at=?""",
                    (_stamp(next_due), current_s, row["id"], due))

        # Queue enqueue is idempotent. If the process dies before marking outbox
        # dispatched, the next scheduler loop safely replays the same idempotency key.
        dispatched = []
        for item in self.pending_dispatches(limit=max(20, min(int(limit) * 5, 500))):
            try:
                payload = json.loads(item["payload_json"])
                job = queue.enqueue("short_video_production", payload,
                    channel_name=payload["brand"],
                    idempotency_key="schedule:" + item["schedule_id"] + ":" + item["scheduled_for"])
                stamp = _stamp(datetime.now(timezone.utc))
                with self.db() as c:
                    c.execute("BEGIN IMMEDIATE")
                    c.execute("""UPDATE schedule_dispatch_outbox SET status='dispatched',
                        attempts=attempts+1,last_error=NULL,dispatched_at=?
                        WHERE id=? AND status='pending'""", (stamp, item["id"]))
                    c.execute("""UPDATE production_schedules SET last_enqueued_at=?,updated_at=?
                        WHERE id=?""", (stamp, stamp, item["schedule_id"]))
                dispatched.append({"schedule_id": item["schedule_id"], "job": job,
                                    "scheduled_for": item["scheduled_for"]})
            except Exception as exc:
                with self.db() as c:
                    c.execute("""UPDATE schedule_dispatch_outbox
                        SET attempts=attempts+1,last_error=? WHERE id=? AND status='pending'""",
                        (type(exc).__name__ + ": " + str(exc)[:500], item["id"]))
        return {"dispatched": dispatched, "count": len(dispatched),
                "pending": len(self.pending_dispatches())}
