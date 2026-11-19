"""Durable engineering-job registry, dependency scheduler, and evidence gate.

This store is intentionally separate from JobQueue/ScheduleStore, which operate
short-video production work rather than repository development work.
"""
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse


TERMINAL = {"completed", "cancelled"}
ACTIVE = {"leased", "running"}


def _now():
    return datetime.now(timezone.utc)


def _stamp(value):
    return value.astimezone(timezone.utc).isoformat()


def _parse(value):
    return datetime.fromisoformat(value)


class DevelopmentJobError(Exception):
    pass


class DevelopmentJobNotFound(DevelopmentJobError):
    pass


class DevelopmentJobConflict(DevelopmentJobError):
    pass


class DevelopmentJobStore:
    """SQLite-backed DAG with fenced worker leases and evidence-based completion."""

    def __init__(self, db_path="data/nexus.sqlite3", lease_seconds=300):
        if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int) or not 10 <= lease_seconds <= 3600:
            raise ValueError("lease_seconds must be an integer from 10 to 3600")
        self.db_path = str(db_path)
        self.lease_seconds = lease_seconds
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as connection:
            connection.executescript("""
            CREATE TABLE IF NOT EXISTS development_jobs(
              id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'blocked', priority INTEGER NOT NULL DEFAULT 100,
              scope_json TEXT NOT NULL DEFAULT '[]', acceptance_json TEXT NOT NULL DEFAULT '[]',
              max_attempts INTEGER NOT NULL DEFAULT 3, attempts INTEGER NOT NULL DEFAULT 0,
              worker_id TEXT, lease_token TEXT, lease_expires_at TEXT,
              source_ref TEXT, changed_files_json TEXT, tests_passed INTEGER,
              validation_ref TEXT, result_summary TEXT,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              started_at TEXT, completed_at TEXT, retry_after TEXT,
              review_url TEXT, review_head_sha TEXT, review_published_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_development_jobs_ready
              ON development_jobs(status,priority,created_at);
            CREATE INDEX IF NOT EXISTS idx_development_jobs_source_ref
              ON development_jobs(source_ref) WHERE source_ref IS NOT NULL;
            CREATE TABLE IF NOT EXISTS development_job_dependencies(
              job_id TEXT NOT NULL REFERENCES development_jobs(id),
              depends_on_id TEXT NOT NULL REFERENCES development_jobs(id),
              created_at TEXT NOT NULL,
              PRIMARY KEY(job_id,depends_on_id),
              CHECK(job_id <> depends_on_id)
            );
            CREATE INDEX IF NOT EXISTS idx_dev_job_dependencies_parent
              ON development_job_dependencies(depends_on_id,job_id);
            CREATE TABLE IF NOT EXISTS development_job_events(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              job_id TEXT NOT NULL REFERENCES development_jobs(id),
              event_type TEXT NOT NULL, from_status TEXT, to_status TEXT,
              actor TEXT NOT NULL, details_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_dev_job_events_job
              ON development_job_events(job_id,id);
            CREATE TABLE IF NOT EXISTS development_workers(
              worker_id TEXT PRIMARY KEY,
              hostname TEXT,
              status TEXT NOT NULL DEFAULT 'offline',
              current_job_id TEXT,
              started_at TEXT NOT NULL,
              last_seen_at TEXT NOT NULL,
              stopped_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_development_workers_seen
              ON development_workers(last_seen_at,status);
            CREATE TRIGGER IF NOT EXISTS development_job_events_no_update
              BEFORE UPDATE ON development_job_events
              BEGIN SELECT RAISE(ABORT,'development job events are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS development_job_events_no_delete
              BEFORE DELETE ON development_job_events
              BEGIN SELECT RAISE(ABORT,'development job events are immutable'); END;
            """)
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(development_jobs)")}
            for column in ("retry_after", "review_url", "review_head_sha", "review_published_at"):
                if column not in columns:
                    connection.execute(f"ALTER TABLE development_jobs ADD COLUMN {column} TEXT")

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            yield connection
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _decode(row):
        if row is None:
            return None
        result = dict(row)
        for column, target in (("scope_json", "scope"), ("acceptance_json", "acceptance"),
                               ("changed_files_json", "changed_files")):
            raw = result.pop(column, None)
            result[target] = json.loads(raw) if raw is not None else None
        result["tests_passed"] = (None if result.get("tests_passed") is None
                                  else bool(result["tests_passed"]))
        return result

    @staticmethod
    def _event(connection, job_id, kind, before, after, actor, details, timestamp):
        connection.execute(
            """INSERT INTO development_job_events
               (job_id,event_type,from_status,to_status,actor,details_json,created_at)
               VALUES(?,?,?,?,?,?,?)""",
            (job_id, kind, before, after, actor[:128],
             json.dumps(details or {}, ensure_ascii=False), timestamp),
        )

    def create(self, title, description="", priority=100, scope=None, acceptance=None,
               max_attempts=3, source_ref=None, job_id=None):
        if not isinstance(title, str) or not title.strip() or len(title) > 240:
            raise ValueError("title must contain 1 to 240 characters")
        if isinstance(priority, bool) or not isinstance(priority, int):
            raise ValueError("priority must be an integer")
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 1 <= max_attempts <= 10:
            raise ValueError("max_attempts must be an integer from 1 to 10")
        scope = scope or []
        acceptance = acceptance or []
        if not isinstance(scope, list) or not all(isinstance(x, str) and x.strip() for x in scope):
            raise ValueError("scope must be a list of non-empty strings")
        if not isinstance(acceptance, list) or not all(isinstance(x, str) and x.strip() for x in acceptance):
            raise ValueError("acceptance must be a list of non-empty strings")
        if source_ref is not None and (not isinstance(source_ref, str) or len(source_ref) > 500):
            raise ValueError("source_ref must be a string of at most 500 characters")
        if job_id is None:
            job_id = str(uuid.uuid4())
        elif not isinstance(job_id, str) or not job_id.strip() or len(job_id) > 128:
            raise ValueError("job_id must contain 1 to 128 characters")
        else:
            job_id = job_id.strip()
        with self.db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if isinstance(source_ref, str) and source_ref.startswith("github:issue:"):
                duplicate = connection.execute(
                    "SELECT id FROM development_jobs WHERE source_ref=? LIMIT 1",
                    (source_ref,),
                ).fetchone()
                if duplicate:
                    raise DevelopmentJobConflict("source_ref already exists")
            timestamp = _stamp(_now())
            connection.execute(
                """INSERT INTO development_jobs
                   (id,title,description,status,priority,scope_json,acceptance_json,
                    max_attempts,source_ref,created_at,updated_at)
                   VALUES(?,?,?,'ready',?,?,?,?,?,?,?)""",
                (job_id, title.strip(), str(description)[:8000], priority,
                 json.dumps(scope), json.dumps(acceptance), max_attempts,
                 source_ref, timestamp, timestamp),
            )
            self._event(connection, job_id, "created", None, "ready", "system",
                        {"source_ref": source_ref}, timestamp)
            row = connection.execute("SELECT * FROM development_jobs WHERE id=?", (job_id,)).fetchone()
            connection.commit()
            return self._decode(row)

    def add_dependency(self, job_id, depends_on_id):
        if not job_id or not depends_on_id or job_id == depends_on_id:
            raise ValueError("a job cannot depend on itself")
        with self.db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT id FROM development_jobs WHERE id IN (?,?)", (job_id, depends_on_id)
            ).fetchall()
            if len(rows) != 2:
                raise DevelopmentJobNotFound("job or dependency not found")
            # Adding job -> parent is invalid if parent already depends (transitively) on job.
            cycle = connection.execute(
                """WITH RECURSIVE ancestors(id) AS (
                     SELECT depends_on_id FROM development_job_dependencies WHERE job_id=?
                     UNION
                     SELECT d.depends_on_id FROM development_job_dependencies d
                     JOIN ancestors a ON d.job_id=a.id
                   ) SELECT 1 FROM ancestors WHERE id=? LIMIT 1""",
                (depends_on_id, job_id),
            ).fetchone()
            if cycle:
                raise DevelopmentJobConflict("dependency would create a cycle")
            timestamp = _stamp(_now())
            inserted = connection.execute(
                """INSERT OR IGNORE INTO development_job_dependencies
                   (job_id,depends_on_id,created_at) VALUES(?,?,?)""",
                (job_id, depends_on_id, timestamp),
            ).rowcount
            if inserted:
                row = connection.execute("SELECT status FROM development_jobs WHERE id=?", (job_id,)).fetchone()
                connection.execute(
                    "UPDATE development_jobs SET status='blocked',updated_at=? WHERE id=? AND status='ready'",
                    (timestamp, job_id),
                )
                self._event(connection, job_id, "dependency_added", row["status"], "blocked",
                            "system", {"depends_on": depends_on_id}, timestamp)
            connection.commit()
        return self.get(job_id)

    def get(self, job_id):
        with self.db() as connection:
            row = connection.execute("SELECT * FROM development_jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                return None
            result = self._decode(row)
            result["dependencies"] = [r["depends_on_id"] for r in connection.execute(
                "SELECT depends_on_id FROM development_job_dependencies WHERE job_id=? ORDER BY depends_on_id",
                (job_id,),
            )]
            return result

    def source_ref_exists(self, source_ref):
        if not isinstance(source_ref, str) or not source_ref:
            return False
        with self.db() as connection:
            return connection.execute(
                "SELECT 1 FROM development_jobs WHERE source_ref=? LIMIT 1",
                (source_ref,),
            ).fetchone() is not None

    def list(self, statuses=None, limit=100):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("limit must be an integer from 1 to 500")
        with self.db() as connection:
            if statuses:
                values = tuple(statuses)
                marks = ",".join("?" for _ in values)
                rows = connection.execute(
                    f"SELECT * FROM development_jobs WHERE status IN ({marks}) ORDER BY priority,created_at LIMIT ?",
                    (*values, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM development_jobs ORDER BY priority,created_at LIMIT ?", (limit,)
                ).fetchall()
            return [self._decode(row) for row in rows]

    @staticmethod
    def _scopes_conflict(left, right):
        # Empty scope means unknown write set: serialize conservatively.
        if not left or not right:
            return True
        for first in left:
            a = first.rstrip("/")
            for second in right:
                b = second.rstrip("/")
                if a == b or a.startswith(b + "/") or b.startswith(a + "/"):
                    return True
        return False

    def claim_ready(self, worker_id):
        if not isinstance(worker_id, str) or not worker_id.strip() or len(worker_id) > 128:
            raise ValueError("worker_id must contain 1 to 128 characters")
        with self.db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            timestamp_dt = _now()
            timestamp = _stamp(timestamp_dt)
            # Expired leases are returned to ready only after the old fencing token is revoked.
            expired = connection.execute(
                """SELECT id,status FROM development_jobs
                   WHERE status IN ('leased','running') AND lease_expires_at<=?""", (timestamp,)
            ).fetchall()
            for item in expired:
                attempts = connection.execute(
                    "SELECT attempts,max_attempts FROM development_jobs WHERE id=?", (item["id"],)
                ).fetchone()
                next_status = "quarantined" if attempts["attempts"] >= attempts["max_attempts"] else "ready"
                connection.execute(
                    """UPDATE development_jobs SET status=?,worker_id=NULL,lease_token=NULL,
                       lease_expires_at=NULL,updated_at=? WHERE id=?""",
                    (next_status, timestamp, item["id"]),
                )
                self._event(connection, item["id"], "lease_expired", item["status"], next_status,
                            "system", {"reason": "worker lease expired"}, timestamp)
            # Promote due retries before selecting the next ready job.
            connection.execute(
                """UPDATE development_jobs SET status='ready',retry_after=NULL,updated_at=?
                   WHERE status='retry_wait' AND retry_after<=? AND attempts<max_attempts""",
                (timestamp, timestamp),
            )
            connection.execute(
                """UPDATE development_jobs SET status='quarantined',updated_at=?
                   WHERE status='retry_wait' AND attempts>=max_attempts AND retry_after<=?""",
                (timestamp, timestamp),
            )
            # Unblock jobs only when every prerequisite has completed.
            connection.execute(
                """UPDATE development_jobs SET status='ready',updated_at=?
                   WHERE status='blocked' AND NOT EXISTS (
                     SELECT 1 FROM development_job_dependencies d
                     JOIN development_jobs parent ON parent.id=d.depends_on_id
                     WHERE d.job_id=development_jobs.id AND parent.status<>'completed'
                   )""", (timestamp,)
            )
            candidates = connection.execute(
                """SELECT * FROM development_jobs
                   WHERE status='ready' AND attempts<max_attempts
                   ORDER BY priority,created_at"""
            ).fetchall()
            active_rows = connection.execute(
                """SELECT scope_json FROM development_jobs
                   WHERE status IN ('leased','running','review_pending')"""
            ).fetchall()
            active_scopes = [json.loads(item["scope_json"]) for item in active_rows]
            row = next((candidate for candidate in candidates
                        if not any(self._scopes_conflict(json.loads(candidate["scope_json"]), active)
                                   for active in active_scopes)), None)
            if row is None:
                connection.commit()
                return None
            token = str(uuid.uuid4())
            expires = _stamp(timestamp_dt + timedelta(seconds=self.lease_seconds))
            connection.execute(
                """UPDATE development_jobs SET status='leased',attempts=attempts+1,
                   worker_id=?,lease_token=?,lease_expires_at=?,started_at=COALESCE(started_at,?),
                   updated_at=? WHERE id=? AND status='ready'""",
                (worker_id.strip(), token, expires, timestamp, timestamp, row["id"]),
            )
            self._event(connection, row["id"], "claimed", "ready", "leased", worker_id,
                        {"lease_expires_at": expires}, timestamp)
            claimed = connection.execute("SELECT * FROM development_jobs WHERE id=?", (row["id"],)).fetchone()
            connection.commit()
            return self._decode(claimed)

    def heartbeat(self, job_id, worker_id, lease_token):
        with self.db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            timestamp_dt = _now()
            timestamp = _stamp(timestamp_dt)
            expires = _stamp(timestamp_dt + timedelta(seconds=self.lease_seconds))
            cur = connection.execute(
                """UPDATE development_jobs SET status='running',lease_expires_at=?,updated_at=?
                   WHERE id=? AND worker_id=? AND lease_token=? AND status IN ('leased','running')
                     AND lease_expires_at>?""",
                (expires, timestamp, job_id, worker_id, lease_token, timestamp),
            )
            if not cur.rowcount:
                raise DevelopmentJobConflict("development job lease is missing, expired, or fenced")
            self._event(connection, job_id, "heartbeat", "leased/running", "running",
                        worker_id, {"lease_expires_at": expires}, timestamp)
            connection.commit()
            return self.get(job_id)

    def mark_review_pending(self, job_id, worker_id, lease_token, changed_files, tests_passed,
                            validation_ref, result_summary=""):
        """Record validated source evidence without claiming a review artifact exists."""
        if not isinstance(changed_files, list) or not changed_files or not all(
            isinstance(path, str) and path.strip() for path in changed_files
        ):
            raise ValueError("review-pending transition requires at least one meaningful changed file")
        if tests_passed is not True:
            raise ValueError("review-pending transition requires tests_passed=True")
        if not isinstance(validation_ref, str) or not validation_ref.strip() or len(validation_ref) > 1000:
            raise ValueError("review-pending transition requires a validation evidence reference")
        normalized_files = []
        for raw_path in changed_files:
            if not isinstance(raw_path, str) or not raw_path.strip():
                raise ValueError("changed_files contains an invalid path")
            path = raw_path.strip()
            if "\\" in path or path.startswith("/") or any(part in ("", ".", "..") for part in path.split("/")):
                raise ValueError("changed_files contains an unsafe or non-normalized path")
            normalized_files.append(path)
        if len(normalized_files) != len(set(normalized_files)):
            raise ValueError("changed_files must not contain duplicates")

        with self.db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            timestamp = _stamp(_now())
            current = connection.execute(
                """SELECT scope_json FROM development_jobs
                   WHERE id=? AND worker_id=? AND lease_token=?
                     AND status IN ('leased','running') AND lease_expires_at>?""",
                (job_id, worker_id, lease_token, timestamp),
            ).fetchone()
            if current is None:
                raise DevelopmentJobConflict("review-pending transition rejected: lease is missing, expired, or fenced")
            scope = json.loads(current["scope_json"] or "[]")
            if not scope:
                raise ValueError("review-pending transition requires a declared file scope")
            outside_scope = [
                path for path in normalized_files
                if not any(
                    path == item.rstrip("/")
                    or item.endswith("/") and path.startswith(item)
                    for item in scope
                )
            ]
            if outside_scope:
                raise ValueError("changed_files contains paths outside the declared scope")
            cur = connection.execute(
                """UPDATE development_jobs SET status='review_pending',worker_id=NULL,lease_token=NULL,
                   lease_expires_at=NULL,changed_files_json=?,tests_passed=1,validation_ref=?,
                   result_summary=?,completed_at=NULL,review_url=NULL,review_head_sha=NULL,
                   review_published_at=NULL,updated_at=?
                   WHERE id=? AND worker_id=? AND lease_token=? AND status IN ('leased','running')
                     AND lease_expires_at>?""",
                (json.dumps(sorted(normalized_files)), validation_ref.strip(),
                 str(result_summary)[:4000], timestamp,
                 job_id, worker_id, lease_token, timestamp),
            )
            if not cur.rowcount:
                raise DevelopmentJobConflict("review-pending transition rejected: lease is missing, expired, or fenced")
            self._event(connection, job_id, "review_pending", "leased/running", "review_pending",
                        worker_id, {"changed_files": sorted(normalized_files),
                                    "validation_ref": validation_ref.strip()}, timestamp)
            connection.commit()
        return self.get(job_id)

    def complete(self, job_id, worker_id, lease_token, changed_files, tests_passed,
                 validation_ref, result_summary=""):
        """Backward-compatible alias; validation alone only reaches review_pending."""
        return self.mark_review_pending(
            job_id, worker_id, lease_token, changed_files, tests_passed,
            validation_ref, result_summary,
        )

    def publish_review_artifact(self, job_id, review_url, review_head_sha, review_files,
                                is_draft, is_open):
        """Complete a job only after its exact changes appear in an open Draft PR."""
        if not isinstance(review_url, str) or not review_url.strip():
            raise ValueError("review URL is required")
        review_url = review_url.strip()
        parsed = urlparse(review_url)
        if (parsed.scheme != "https" or parsed.netloc.lower() != "github.com"
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or not re.fullmatch(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/[1-9][0-9]*", parsed.path)):
            raise ValueError("review URL must be a canonical GitHub pull-request URL")
        if not isinstance(review_head_sha, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", review_head_sha):
            raise ValueError("review head SHA must be a full 40-character commit SHA")
        if not isinstance(review_files, list) or not review_files:
            raise ValueError("review artifact must contain at least one changed file")
        normalized_review_files = set()
        for raw_path in review_files:
            if not isinstance(raw_path, str) or not raw_path.strip():
                raise ValueError("review artifact contains an invalid file path")
            path = raw_path.strip()
            if "\\" in path or path.startswith("/") or any(part in ("", ".", "..") for part in path.split("/")):
                raise ValueError("review artifact contains an unsafe or non-normalized file path")
            normalized_review_files.add(path)
        if is_draft is not True:
            raise ValueError("review artifact must be a Draft pull request")
        if is_open is not True:
            raise ValueError("review artifact must be an open, unmerged pull request")

        with self.db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM development_jobs WHERE id=?", (job_id,)
            ).fetchone()
            if row is None:
                raise DevelopmentJobNotFound("development job not found")
            if row["status"] == "completed":
                if row["review_url"] == review_url and row["review_head_sha"] == review_head_sha.lower():
                    connection.commit()
                    return self.get(job_id)
                raise DevelopmentJobConflict("completed job is already bound to a different review artifact")
            if row["status"] != "review_pending":
                raise DevelopmentJobConflict("job must be review_pending before its PR artifact can complete it")
            changed_files = set(json.loads(row["changed_files_json"] or "[]"))
            if not changed_files or not changed_files.issubset(normalized_review_files):
                missing = sorted(changed_files - normalized_review_files)
                raise ValueError("review PR does not contain every job change: " + ", ".join(missing[:20]))
            timestamp = _stamp(_now())
            cur = connection.execute(
                """UPDATE development_jobs SET status='completed',review_url=?,review_head_sha=?,
                   review_published_at=?,completed_at=?,updated_at=?
                   WHERE id=? AND status='review_pending'""",
                (review_url, review_head_sha.lower(), timestamp, timestamp, timestamp, job_id),
            )
            if not cur.rowcount:
                raise DevelopmentJobConflict("review publication lost a concurrent state transition")
            self._event(connection, job_id, "review_published", "review_pending", "completed",
                        "github", {"review_url": review_url, "review_head_sha": review_head_sha.lower(),
                                   "draft": True, "state": "open",
                                   "review_file_count": len(normalized_review_files)}, timestamp)
            connection.commit()
        return self.get(job_id)

    def fail(self, job_id, worker_id, lease_token, error, retryable=True, retry_delay_seconds=None):
        """Record a failed attempt; retry with bounded exponential backoff or quarantine."""
        if not isinstance(error, str) or not error.strip():
            raise ValueError("error must be a non-empty string")
        if not isinstance(retryable, bool):
            raise ValueError("retryable must be a boolean")
        if retry_delay_seconds is not None and (
            isinstance(retry_delay_seconds, bool) or not isinstance(retry_delay_seconds, int)
            or not 0 <= retry_delay_seconds <= 86400
        ):
            raise ValueError("retry_delay_seconds must be an integer from 0 to 86400")
        with self.db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            now = _now()
            timestamp = _stamp(now)
            row = connection.execute(
                """SELECT status,attempts,max_attempts FROM development_jobs
                   WHERE id=? AND worker_id=? AND lease_token=? AND status IN ('leased','running')
                     AND lease_expires_at>?""",
                (job_id, worker_id, lease_token, timestamp),
            ).fetchone()
            if row is None:
                raise DevelopmentJobConflict("failure rejected: lease is missing, expired, or fenced")
            exhausted = row["attempts"] >= row["max_attempts"]
            if not retryable or exhausted:
                status, retry_after = "quarantined", None
            else:
                delay = retry_delay_seconds
                if delay is None:
                    delay = min(3600, 30 * (2 ** max(0, row["attempts"] - 1)))
                status, retry_after = "retry_wait", _stamp(now + timedelta(seconds=delay))
            connection.execute(
                """UPDATE development_jobs SET status=?,worker_id=NULL,lease_token=NULL,
                   lease_expires_at=NULL,retry_after=?,result_summary=?,updated_at=? WHERE id=?""",
                (status, retry_after, error.strip()[:4000], timestamp, job_id),
            )
            self._event(connection, job_id, "failed", row["status"], status, worker_id,
                        {"error": error.strip()[:4000], "retryable": retryable,
                         "retry_after": retry_after}, timestamp)
            connection.commit()
        return self.get(job_id)

    def events(self, job_id, limit=100):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("limit must be an integer from 1 to 500")
        with self.db() as connection:
            if connection.execute("SELECT 1 FROM development_jobs WHERE id=?", (job_id,)).fetchone() is None:
                raise DevelopmentJobNotFound("job not found")
            rows = connection.execute(
                """SELECT * FROM development_job_events WHERE job_id=?
                   ORDER BY id DESC LIMIT ?""", (job_id, limit)
            ).fetchall()
            return [dict(row) | {"details": json.loads(row["details_json"])}
                    for row in reversed(rows)]

    def touch_worker(self, worker_id, hostname=None, current_job_id=None):
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise ValueError("worker_id is required")
        if hostname is not None and not isinstance(hostname, str):
            raise ValueError("hostname must be a string")
        if current_job_id is not None and not isinstance(current_job_id, str):
            raise ValueError("current_job_id must be a string")
        worker_id = worker_id.strip()
        timestamp = _stamp(_now())
        with self.db() as connection:
            connection.execute(
                """INSERT INTO development_workers
                   (worker_id,hostname,status,current_job_id,started_at,last_seen_at,stopped_at)
                   VALUES(?,?, 'online', ?,?,?,NULL)
                   ON CONFLICT(worker_id) DO UPDATE SET
                     hostname=COALESCE(excluded.hostname,development_workers.hostname),
                     status='online',current_job_id=excluded.current_job_id,
                     last_seen_at=excluded.last_seen_at,stopped_at=NULL""",
                (worker_id, hostname, current_job_id, timestamp, timestamp),
            )
        return self.get_worker(worker_id)

    def stop_worker(self, worker_id):
        timestamp = _stamp(_now())
        with self.db() as connection:
            cursor = connection.execute(
                """UPDATE development_workers SET status='offline',
                   current_job_id=NULL,last_seen_at=?,stopped_at=? WHERE worker_id=?""",
                (timestamp, timestamp, worker_id),
            )
            return cursor.rowcount > 0

    def get_worker(self, worker_id):
        with self.db() as connection:
            row = connection.execute(
                "SELECT * FROM development_workers WHERE worker_id=?", (worker_id,)
            ).fetchone()
            return dict(row) if row else None

    def list_workers(self, online_within_seconds=90):
        if isinstance(online_within_seconds, bool) or not isinstance(online_within_seconds, int) or online_within_seconds < 1:
            raise ValueError("online_within_seconds must be a positive integer")
        cutoff = _stamp(_now() - timedelta(seconds=online_within_seconds))
        with self.db() as connection:
            rows = connection.execute(
                "SELECT * FROM development_workers ORDER BY last_seen_at DESC,worker_id"
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["is_online"] = item["status"] == "online" and item["last_seen_at"] >= cutoff
            result.append(item)
        return result

    def summary(self):
        with self.db() as connection:
            counts = {row["status"]: row["count"] for row in connection.execute(
                "SELECT status,COUNT(*) AS count FROM development_jobs GROUP BY status"
            )}
            now = _stamp(_now())
            lease_counts = connection.execute(
                """SELECT
                     SUM(CASE WHEN status IN ('leased','running') AND lease_expires_at>? THEN 1 ELSE 0 END) AS active,
                     SUM(CASE WHEN status IN ('leased','running') AND
                         (lease_expires_at IS NULL OR lease_expires_at<=?) THEN 1 ELSE 0 END) AS expired
                   FROM development_jobs""",
                (now, now),
            ).fetchone()
            latest = connection.execute(
                """SELECT updated_at FROM development_jobs
                   ORDER BY updated_at DESC,id DESC LIMIT 1"""
            ).fetchone()
            latest_validation = connection.execute(
                """SELECT validation_ref FROM development_jobs
                   WHERE status IN ('review_pending','completed') AND validation_ref IS NOT NULL
                   ORDER BY updated_at DESC,id DESC LIMIT 1"""
            ).fetchone()
            worker_cutoff = _stamp(_now() - timedelta(seconds=90))
            worker_counts = connection.execute(
                """SELECT
                     SUM(CASE WHEN status='online' AND last_seen_at>=? THEN 1 ELSE 0 END) AS online,
                     COUNT(*) AS total
                   FROM development_workers""",
                (worker_cutoff,),
            ).fetchone()
            return {"total": sum(counts.values()), "by_status": counts,
                    "ready": counts.get("ready", 0), "running": counts.get("running", 0),
                    "blocked": counts.get("blocked", 0), "retry_wait": counts.get("retry_wait", 0),
                    "quarantined": counts.get("quarantined", 0),
                    "review_pending": counts.get("review_pending", 0),
                    "completed": counts.get("completed", 0),
                    "active_leases": lease_counts["active"] or 0,
                    "expired_leases": lease_counts["expired"] or 0,
                    "latest_updated_at": latest["updated_at"] if latest else None,
                    "latest_validation_ref": latest_validation["validation_ref"] if latest_validation else None,
                    "online_workers": worker_counts["online"] or 0,
                    "known_workers": worker_counts["total"] or 0}
