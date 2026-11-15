"""Human review workflow with append-only decision audit.

Approval is an explicit operator action. This module never uploads or publishes media.
"""
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class ReviewNotFound(Exception):
    pass


class ReviewConflict(Exception):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat()


class ReviewStore:
    DECISIONS = {"approved", "rejected", "revision_requested"}

    def __init__(self, db_path="data/nexus.sqlite3"):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS review_decisions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              job_id TEXT NOT NULL,
              decision TEXT NOT NULL CHECK(decision IN
                ('approved','rejected','revision_requested')),
              previous_status TEXT NOT NULL,
              reviewer_id TEXT NOT NULL,
              comment TEXT NOT NULL DEFAULT '',
              artifact_snapshot_json TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_review_job ON review_decisions(job_id,id);
            CREATE INDEX IF NOT EXISTS idx_review_decision ON review_decisions(decision,created_at);
            """)

    @contextmanager
    def db(self):
        c = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
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

    def list_pending(self, limit=50):
        limit = max(1, min(int(limit), 200))
        with self.db() as c:
            has_queue = c.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='pipeline_jobs'"
            ).fetchone() is not None
            payload_column = ", j.payload_json AS job_payload_json" if has_queue else ", NULL AS job_payload_json"
            queue_join = " LEFT JOIN pipeline_jobs j ON j.id=r.job_id" if has_queue else ""
            rows = c.execute(
                "SELECT r.*" + payload_column + " FROM production_runs r" + queue_join +
                " WHERE r.status='review_pending' ORDER BY r.updated_at ASC LIMIT ?",
                (limit,)
            ).fetchall()
            return [self._with_job_context(self._with_artifacts(c, dict(row)))
                    for row in rows]

    @staticmethod
    def _with_artifacts(c, run):
        rows = c.execute("""
          SELECT stage,artifact_type,artifact_url,metadata_json,created_at
          FROM production_artifacts WHERE job_id=? ORDER BY created_at,id
        """, (run["job_id"],)).fetchall()
        run["artifacts"] = [{
            "stage": x["stage"], "artifact_type": x["artifact_type"],
            "artifact_url": x["artifact_url"],
            "metadata": json.loads(x["metadata_json"]),
            "created_at": x["created_at"]
        } for x in rows]
        return run


    def list_approved(self, limit=50):
        limit = max(1, min(int(limit), 200))
        with self.db() as c:
            has_queue = c.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='pipeline_jobs'"
            ).fetchone() is not None
            payload_column = ", j.payload_json AS job_payload_json" if has_queue else ", NULL AS job_payload_json"
            queue_join = " LEFT JOIN pipeline_jobs j ON j.id=r.job_id" if has_queue else ""
            rows = c.execute(
                "SELECT r.*" + payload_column + " FROM production_runs r" + queue_join +
                " WHERE r.status='approved' ORDER BY r.updated_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
            return [self._with_job_context(self._with_artifacts(c, dict(row)))
                    for row in rows]

    @staticmethod
    def _with_job_context(run):
        """Expose the immutable brand profile captured when the job was submitted."""
        raw = run.pop("job_payload_json", None)
        profile = None
        if raw:
            try:
                payload = json.loads(raw)
                if isinstance(payload, dict):
                    candidate = payload.get("brand_profile")
                    if isinstance(candidate, dict):
                        profile = {
                            "positioning": candidate.get("positioning"),
                            "audience": candidate.get("audience"),
                            "tone": candidate.get("tone", []),
                            "risk_level": candidate.get("risk_level"),
                            "review_rules": candidate.get("review_rules", []),
                        }
            except (TypeError, ValueError):
                profile = None
        run["brand_profile"] = profile
        return run

    def decide(self, job_id, decision, reviewer_id, comment=""):
        if decision not in self.DECISIONS:
            raise ValueError("Unsupported review decision")
        reviewer_id = str(reviewer_id or "").strip()
        comment = str(comment or "").strip()
        if not reviewer_id or len(reviewer_id) > 128:
            raise ValueError("reviewer_id is required (max 128 characters)")
        if len(comment) > 4000:
            raise ValueError("comment must be 4000 characters or fewer")
        if decision in ("rejected", "revision_requested") and not comment:
            raise ValueError("A comment is required for rejection or revision request")

        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            run = c.execute(
                "SELECT * FROM production_runs WHERE job_id=?", (job_id,)
            ).fetchone()
            if run is None:
                raise ReviewNotFound(job_id)
            if run["status"] != "review_pending":
                raise ReviewConflict(
                    "Only review_pending production runs can receive a decision"
                )
            artifacts = c.execute("""
              SELECT stage,artifact_type,artifact_url,metadata_json
              FROM production_artifacts WHERE job_id=? ORDER BY created_at,id
            """, (job_id,)).fetchall()
            policy_report = None
            for artifact in artifacts:
                if artifact["stage"] == "script" and artifact["artifact_type"] == "text":
                    metadata = json.loads(artifact["metadata_json"])
                    candidate = metadata.get("policy_preflight")
                    if isinstance(candidate, dict):
                        policy_report = candidate
                        break
            if decision == "approved" and policy_report:
                if policy_report.get("status") == "blocked":
                    raise ReviewConflict("Policy-blocked content cannot be approved")
                if policy_report.get("status") == "review_required" and not comment:
                    raise ValueError("Policy review requires an explicit reviewer confirmation note")
            snapshot = [{
                "stage": a["stage"], "artifact_type": a["artifact_type"],
                "artifact_url": a["artifact_url"],
                "metadata": json.loads(a["metadata_json"])
            } for a in artifacts]
            timestamp = _now()
            c.execute("""
              INSERT INTO review_decisions
                (job_id,decision,previous_status,reviewer_id,comment,
                 artifact_snapshot_json,created_at)
              VALUES(?,?,?,?,?,?,?)
            """, (job_id, decision, run["status"], reviewer_id, comment,
                  json.dumps(snapshot, ensure_ascii=False), timestamp))
            updated=c.execute("""
              UPDATE production_runs SET status=?,current_stage='review',
                error=?,updated_at=? WHERE job_id=? AND status='review_pending'
            """, (decision, comment if decision != "approved" else None,
                  timestamp, job_id))
            if updated.rowcount != 1:
                raise ReviewConflict("Review state changed concurrently")
            row = c.execute(
                "SELECT * FROM production_runs WHERE job_id=?", (job_id,)
            ).fetchone()
            decisions = self._history(c, job_id)
            c.commit()
            return {"production": self._with_artifacts(c, dict(row)),
                    "decision": decisions[-1], "history": decisions}

    def history(self, job_id):
        with self.db() as c:
            exists = c.execute(
                "SELECT 1 FROM production_runs WHERE job_id=?", (job_id,)
            ).fetchone()
            if exists is None:
                raise ReviewNotFound(job_id)
            return self._history(c, job_id)

    @staticmethod
    def _history(c, job_id):
        rows = c.execute("""
          SELECT id,job_id,decision,previous_status,reviewer_id,comment,
                 artifact_snapshot_json,created_at
          FROM review_decisions WHERE job_id=? ORDER BY id
        """, (job_id,)).fetchall()
        return [{
            "id": r["id"], "job_id": r["job_id"], "decision": r["decision"],
            "previous_status": r["previous_status"],
            "reviewer_id": r["reviewer_id"], "comment": r["comment"],
            "artifact_snapshot": json.loads(r["artifact_snapshot_json"]),
            "created_at": r["created_at"]
        } for r in rows]


def valid_review_token(provided, expected):
    """Fail closed when no review secret is configured."""
    return bool(provided and expected and secrets.compare_digest(
        str(provided), str(expected)
    ))
