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


def _lease_seconds(value, minimum):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > 3600:
        raise ValueError("lease_seconds must be an integer from 1 to 3600")
    return max(minimum, value)


def _bounded_limit(value, name, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError(f"{name} must be an integer from 1 to {maximum}")
    return value


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
              next_attempt_at TEXT,
              UNIQUE(schedule_id,scheduled_for)
            );
            CREATE INDEX IF NOT EXISTS idx_schedule_outbox_pending
              ON schedule_dispatch_outbox(status,created_at);
            CREATE TABLE IF NOT EXISTS scheduler_leader_lease(
              id INTEGER PRIMARY KEY CHECK(id=1), owner_id TEXT NOT NULL,
              lease_token TEXT NOT NULL, expires_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            """)
            columns = {row["name"] for row in c.execute(
                "PRAGMA table_info(schedule_dispatch_outbox)").fetchall()}
            if "next_attempt_at" not in columns:
                c.execute("ALTER TABLE schedule_dispatch_outbox ADD COLUMN next_attempt_at TEXT")
            c.execute("""CREATE INDEX IF NOT EXISTS idx_schedule_outbox_retry
                ON schedule_dispatch_outbox(status,next_attempt_at,created_at)""")

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
        if isinstance(interval_seconds, bool) or not isinstance(interval_seconds, int):
            raise ValueError("interval_seconds must be an integer")
        interval = interval_seconds
        if interval < 3600:
            raise ValueError("minimum schedule interval is one hour")
        if interval > 31536000:
            raise ValueError("maximum schedule interval is 365 days")
        start = _dt(start_at) if start_at else None
        if start is not None and start.tzinfo is None:
            raise ValueError("start_at must include timezone")
        sid = str(uuid.uuid4())
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            # Use the serialized insert time as the default first-run time and
            # for both creation audit fields.
            now = datetime.now(timezone.utc)
            due = _stamp(start if start is not None else now)
            stamp = _stamp(now)
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
        if not isinstance(active, bool):
            raise ValueError("active must be a boolean")
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            stamp = _stamp(datetime.now(timezone.utc))
            cur = c.execute("UPDATE production_schedules SET active=?,updated_at=? WHERE id=?",
                            (int(bool(active)), stamp, sid))
            if not cur.rowcount:
                return None
            if not active:
                # A due occurrence that has not reached the queue is still
                # cancellable. Do not replay it if this schedule is later re-enabled.
                c.execute("""UPDATE schedule_dispatch_outbox
                    SET status='cancelled',last_error='Schedule deactivated before dispatch'
                    WHERE schedule_id=? AND status='pending'""", (sid,))
            return self.get(sid, c)

    def pending_dispatches(self, limit=100, now=None):
        limit = _bounded_limit(limit, "limit", 500)
        with self.db() as c:
            if now is None:
                rows = c.execute("""SELECT * FROM schedule_dispatch_outbox
                    WHERE status='pending' ORDER BY created_at LIMIT ?""",
                    (limit,)).fetchall()
            else:
                if now.tzinfo is None:
                    raise ValueError("now must be timezone-aware")
                rows = c.execute("""SELECT * FROM schedule_dispatch_outbox
                    WHERE status='pending' AND
                    (next_attempt_at IS NULL OR next_attempt_at<=?)
                    ORDER BY created_at LIMIT ?""",
                    (_stamp(now), limit)).fetchall()
            return [dict(row) for row in rows]


    def outbox_status(self, limit=20, now=None):
        limit = _bounded_limit(limit, "limit", 100)
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        current_s = _stamp(current)
        with self.db() as c:
            counts = {row["status"]: row["n"] for row in c.execute(
                "SELECT status,COUNT(*) n FROM schedule_dispatch_outbox GROUP BY status")}
            pending_retries = c.execute("""SELECT COUNT(*) FROM schedule_dispatch_outbox
                WHERE status='pending' AND next_attempt_at IS NOT NULL
                AND next_attempt_at>?""", (current_s,)).fetchone()[0]
            pending_ready = c.execute("""SELECT COUNT(*) FROM schedule_dispatch_outbox
                WHERE status='pending' AND
                (next_attempt_at IS NULL OR next_attempt_at<=?)""",
                (current_s,)).fetchone()[0]
            rows = c.execute("""SELECT id,schedule_id,scheduled_for,status,attempts,
                last_error,created_at,next_attempt_at FROM schedule_dispatch_outbox
                ORDER BY CASE status WHEN 'dead_letter' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END,
                created_at DESC LIMIT ?""", (limit,)).fetchall()
            return {"counts": counts, "items": [dict(row) for row in rows],
                    "pending_retries": pending_retries, "pending_ready": pending_ready}



    def retry_dead_letter(self, outbox_id):
        """Explicitly requeue a dead-letter item without changing its idempotency key."""
        if not isinstance(outbox_id, str) or not outbox_id.strip():
            raise ValueError("outbox_id is required")
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            cur = c.execute("""UPDATE schedule_dispatch_outbox
                SET status='pending',attempts=0,last_error=NULL,next_attempt_at=NULL,
                    dispatched_at=NULL
                WHERE id=? AND status='dead_letter'
                AND EXISTS (
                    SELECT 1 FROM production_schedules s
                    WHERE s.id=schedule_dispatch_outbox.schedule_id AND s.active=1
                )""", (outbox_id,))
            if not cur.rowcount:
                return None
            row = c.execute("SELECT * FROM schedule_dispatch_outbox WHERE id=?",
                            (outbox_id,)).fetchone()
            return dict(row)

    def acquire_scheduler_lease(self, owner_id, lease_seconds=90, now=None):
        """Acquire or renew the singleton scheduler lease; return its fencing token."""
        if not owner_id or not str(owner_id).strip():
            raise ValueError("scheduler owner_id is required")
        ttl = _lease_seconds(lease_seconds, 15)
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            current = now if now is not None else datetime.now(timezone.utc)
            if current.tzinfo is None:
                raise ValueError("now must be timezone-aware")
            current_s = _stamp(current)
            expires = _stamp(current + timedelta(seconds=ttl))
            row = c.execute("SELECT * FROM scheduler_leader_lease WHERE id=1").fetchone()
            if row and row["owner_id"] != owner_id and row["expires_at"] > current_s:
                c.commit()
                return None
            token = row["lease_token"] if row and row["owner_id"] == owner_id else str(uuid.uuid4())
            c.execute("""INSERT INTO scheduler_leader_lease
                (id,owner_id,lease_token,expires_at,updated_at) VALUES(1,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET owner_id=excluded.owner_id,
                lease_token=excluded.lease_token,expires_at=excluded.expires_at,
                updated_at=excluded.updated_at""",
                (str(owner_id), token, expires, current_s))
            c.commit()
            return token

    def renew_scheduler_lease(self, owner_id, lease_token, lease_seconds=90, now=None):
        ttl = _lease_seconds(lease_seconds, 15)
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            current = now if now is not None else datetime.now(timezone.utc)
            if current.tzinfo is None:
                raise ValueError("now must be timezone-aware")
            current_s = _stamp(current)
            expires = _stamp(current + timedelta(seconds=ttl))
            cur = c.execute("""UPDATE scheduler_leader_lease
                SET expires_at=?,updated_at=? WHERE id=1 AND owner_id=?
                AND lease_token=? AND expires_at>?""",
                (expires, current_s, str(owner_id), lease_token, current_s))
            c.commit()
            return bool(cur.rowcount)

    def release_scheduler_lease(self, owner_id, lease_token):
        current_s = _stamp(datetime.now(timezone.utc))
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            cur = c.execute("""DELETE FROM scheduler_leader_lease
                WHERE id=1 AND owner_id=? AND lease_token=?""",
                (str(owner_id), lease_token))
            c.commit()
            return bool(cur.rowcount)

    def scheduler_lease_is_valid(self, owner_id, lease_token, now=None):
        current_s = _stamp(now or datetime.now(timezone.utc))
        with self.db() as c:
            row = c.execute("""SELECT 1 FROM scheduler_leader_lease
                WHERE id=1 AND owner_id=? AND lease_token=? AND expires_at>?""",
                (str(owner_id), lease_token, current_s)).fetchone()
            return row is not None

    def dispatch_due(self, queue, now=None, limit=20, lease_owner=None, lease_token=None, lease_seconds=90):
        limit = _bounded_limit(limit, "limit", 100)
        _lease_seconds(lease_seconds, 15)
        if (lease_owner is None) != (lease_token is None):
            raise ValueError("lease_owner and lease_token must be supplied together")
        # Sample the implicit clock only after SQLite grants the write lock.
        # Validate the fencing lease under the same lock as schedule reservation.
        lease_lost = False
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            current = now if now is not None else datetime.now(timezone.utc)
            if current.tzinfo is None:
                raise ValueError("now must be timezone-aware")
            current_s = _stamp(current)
            if lease_owner is not None:
                lease = c.execute("""SELECT 1 FROM scheduler_leader_lease
                    WHERE id=1 AND owner_id=? AND lease_token=? AND expires_at>?""",
                    (str(lease_owner), lease_token, current_s)).fetchone()
                if not lease:
                    c.commit()
                    lease_lost = True
            rows = [] if lease_lost else c.execute("""SELECT * FROM production_schedules
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
        if lease_lost:
            return {"dispatched": [], "count": 0,
                    "pending": len(self.pending_dispatches()), "lease_lost": True}

        # A production pause also pauses scheduled dispatch. Due occurrences are
        # already durable in the outbox, so they remain pending and replay after
        # an operator explicitly resumes production.
        if getattr(queue, "is_paused", lambda: False)():
            return {"dispatched": [], "count": 0,
                    "pending": len(self.pending_dispatches()) , "paused": True}

        # Queue enqueue is idempotent. If the process dies before marking outbox
        # dispatched, the next scheduler loop safely replays the same idempotency key.
        dispatched = []
        for item in self.pending_dispatches(limit=min(limit * 5, 500), now=current):
            try:
                if lease_owner is not None and not self.renew_scheduler_lease(
                        lease_owner, lease_token, lease_seconds):
                    return {"dispatched": dispatched, "count": len(dispatched),
                            "pending": len(self.pending_dispatches()), "lease_lost": True}
                payload = json.loads(item["payload_json"])
                job = queue.enqueue("short_video_production", payload,
                    channel_name=payload["brand"],
                    idempotency_key="schedule:" + item["schedule_id"] + ":" + item["scheduled_for"])
                with self.db() as c:
                    c.execute("BEGIN IMMEDIATE")
                    # The queue may have accepted the idempotent job while this
                    # process waited for SQLite. Timestamp the durable completion
                    # only after acquiring the write lock, and use that same
                    # decision time for fencing and both persisted records.
                    completed_at = datetime.now(timezone.utc)
                    stamp = _stamp(completed_at)
                    if lease_owner is not None:
                        lease = c.execute("""SELECT 1 FROM scheduler_leader_lease
                            WHERE id=1 AND owner_id=? AND lease_token=? AND expires_at>?""",
                            (str(lease_owner), lease_token, stamp)).fetchone()
                        if not lease:
                            c.rollback()
                            return {"dispatched": dispatched, "count": len(dispatched),
                                    "pending": len(self.pending_dispatches()), "lease_lost": True}
                    c.execute("""UPDATE schedule_dispatch_outbox SET status='dispatched',
                        attempts=attempts+1,last_error=NULL,dispatched_at=?,next_attempt_at=NULL
                        WHERE id=? AND status='pending'""", (stamp, item["id"]))
                    c.execute("""UPDATE production_schedules SET last_enqueued_at=?,updated_at=?
                        WHERE id=?""", (stamp, stamp, item["schedule_id"]))
                dispatched.append({"schedule_id": item["schedule_id"], "job": job,
                                    "scheduled_for": item["scheduled_for"]})
            except Exception as exc:
                # Back off from the actual serialized failure time, not the
                # dispatch-loop start time. A slow provider/queue call must not
                # make the retry deadline stale before it is persisted.
                delay = min(30 * (2 ** min(int(item["attempts"]), 7)), 3600)
                next_attempt = int(item["attempts"]) + 1
                next_status = "dead_letter" if next_attempt >= 10 else "pending"
                with self.db() as c:
                    c.execute("BEGIN IMMEDIATE")
                    failed_at = now if now is not None else datetime.now(timezone.utc)
                    if failed_at.tzinfo is None:
                        raise ValueError("now must be timezone-aware")
                    failed_at_s = _stamp(failed_at)
                    if lease_owner is not None:
                        lease = c.execute("""SELECT 1 FROM scheduler_leader_lease
                            WHERE id=1 AND owner_id=? AND lease_token=? AND expires_at>?""",
                            (str(lease_owner), lease_token, failed_at_s)).fetchone()
                        if not lease:
                            c.rollback()
                            return {"dispatched": dispatched, "count": len(dispatched),
                                    "pending": len(self.pending_dispatches()), "lease_lost": True}
                    retry_at = _stamp(failed_at + timedelta(seconds=delay))
                    c.execute("""UPDATE schedule_dispatch_outbox
                        SET attempts=?,last_error=?,next_attempt_at=?,status=?
                        WHERE id=? AND status='pending'""",
                        (next_attempt, type(exc).__name__ + ": " + str(exc)[:500],
                         None if next_status == "dead_letter" else retry_at,
                         next_status, item["id"]))
        return {"dispatched": dispatched, "count": len(dispatched),
                "pending": len(self.pending_dispatches())}
