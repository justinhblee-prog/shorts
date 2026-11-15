"""Human review workflow with append-only decision audit.

Approval is an explicit operator action. This module never uploads or publishes media.
"""
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from policy_engine import evaluate_content_policy


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
            CREATE TABLE IF NOT EXISTS policy_evidence_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              job_id TEXT NOT NULL,
              reviewer_id TEXT NOT NULL,
              declarations_json TEXT NOT NULL,
              report_json TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_policy_evidence_job
              ON policy_evidence_events(job_id,id);
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

    def update_policy_evidence(self, job_id, reviewer_id, declarations):
        """Persist explicit operator attestations and recompute the policy report."""
        reviewer_id = str(reviewer_id or "").strip()
        if not reviewer_id or len(reviewer_id) > 128:
            raise ValueError("reviewer_id is required (max 128 characters)")
        if not isinstance(declarations, dict) or not declarations:
            raise ValueError("policy declarations are required")

        allowed = {
            "rights", "synthetic_media_status", "platform_disclosures", "platforms",
            "risk_flags", "factual_claims_verified", "originality_notes",
            "claim_evidence_notes", "source_urls", "transformative_contribution",
            "commercial_relationship_disclosed", "child_safety_review_confirmed",
        }
        unknown = sorted(set(declarations) - allowed)
        if unknown:
            raise ValueError("Unsupported policy declaration fields: " + ", ".join(unknown))

        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            run = c.execute(
                "SELECT status FROM production_runs WHERE job_id=?", (job_id,)
            ).fetchone()
            if run is None:
                raise ReviewNotFound(job_id)
            if run["status"] != "review_pending":
                raise ReviewConflict("Policy evidence can only be updated while review is pending")
            has_queue = c.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='pipeline_jobs'"
            ).fetchone()
            if not has_queue:
                raise ReviewConflict("Durable queue payload is unavailable for policy evidence")
            job = c.execute(
                "SELECT payload_json,status FROM pipeline_jobs WHERE id=? AND job_type='short_video_production'",
                (job_id,),
            ).fetchone()
            if job is None or job["status"] != "review_pending":
                raise ReviewConflict("Queue job is not in review_pending state")
            try:
                payload = json.loads(job["payload_json"])
            except (TypeError, ValueError) as exc:
                raise ReviewConflict("Production payload is not valid JSON") from exc
            if not isinstance(payload, dict):
                raise ReviewConflict("Production payload must be an object")

            updated_payload = dict(payload)
            for key, value in declarations.items():
                updated_payload[key] = value
            report = evaluate_content_policy(updated_payload)

            artifact = c.execute("""
              SELECT id,metadata_json FROM production_artifacts
              WHERE job_id=? AND stage='script' AND artifact_type='text'
              ORDER BY created_at DESC,id DESC LIMIT 1
            """, (job_id,)).fetchone()
            if artifact is None:
                raise ReviewConflict("Script artifact is required before policy evidence can be updated")
            try:
                metadata = json.loads(artifact["metadata_json"])
            except (TypeError, ValueError) as exc:
                raise ReviewConflict("Script artifact metadata is invalid") from exc
            if not isinstance(metadata, dict):
                raise ReviewConflict("Script artifact metadata must be an object")
            metadata["policy_preflight"] = report
            timestamp = _now()
            c.execute(
                "UPDATE production_artifacts SET metadata_json=? WHERE id=?",
                (json.dumps(metadata, ensure_ascii=False), artifact["id"]),
            )
            updated_payload["policy_report"] = report
            c.execute(
                "UPDATE pipeline_jobs SET payload_json=?,updated_at=? WHERE id=?",
                (json.dumps(updated_payload, ensure_ascii=False), timestamp, job_id),
            )
            cursor = c.execute("""
              INSERT INTO policy_evidence_events
                (job_id,reviewer_id,declarations_json,report_json,created_at)
              VALUES(?,?,?,?,?)
            """, (
                job_id, reviewer_id,
                json.dumps(declarations, ensure_ascii=False),
                json.dumps(report, ensure_ascii=False), timestamp,
            ))
            c.commit()
            return {
                "job_id": job_id,
                "reviewer_id": reviewer_id,
                "event_id": cursor.lastrowid,
                "policy_preflight": report,
                "created_at": timestamp,
            }

    def policy_evidence_history(self, job_id):
        with self.db() as c:
            exists = c.execute(
                "SELECT 1 FROM production_runs WHERE job_id=?", (job_id,)
            ).fetchone()
            if exists is None:
                raise ReviewNotFound(job_id)
            rows = c.execute("""
              SELECT id,job_id,reviewer_id,declarations_json,report_json,created_at
              FROM policy_evidence_events WHERE job_id=? ORDER BY id
            """, (job_id,)).fetchall()
            return [{
                "id": row["id"], "job_id": row["job_id"],
                "reviewer_id": row["reviewer_id"],
                "declarations": json.loads(row["declarations_json"]),
                "policy_preflight": json.loads(row["report_json"]),
                "created_at": row["created_at"],
            } for row in rows]

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
                approval_blockers = policy_report.get("approval_blockers") or []
                if approval_blockers:
                    raise ReviewConflict(
                        "Policy approval blockers must be resolved before approval: "
                        + ", ".join(sorted(str(item) for item in approval_blockers))
                    )
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
