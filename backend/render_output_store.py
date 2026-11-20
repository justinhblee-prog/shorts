"""Durable, workspace-scoped render output adoption and human review state."""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class RenderOutputError(RuntimeError):
    pass


class RenderOutputNotFound(RenderOutputError):
    pass


class RenderOutputLeaseConflict(RenderOutputError):
    pass


_JOB_ID = re.compile(r"^[0-9a-f-]{36}$")
_WORKSPACE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_RENDER_ID = re.compile(r"^[0-9a-f]{32}$")


def _now():
    return datetime.now(timezone.utc).isoformat()


class RenderOutputStore:
    def __init__(self, db_path=None, media_dir=None):
        self.db_path = str(db_path or os.getenv("NEXUS_DB_PATH", "data/nexus.sqlite3"))
        self.media_root = Path(
            media_dir or os.getenv("NEXUS_MEDIA_DIR", "data/media")
        ).resolve()
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS render_outputs(
                    job_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    worker_id TEXT NOT NULL,
                    lease_token TEXT NOT NULL,
                    render_id TEXT NOT NULL UNIQUE,
                    relative_path TEXT NOT NULL UNIQUE,
                    size_bytes INTEGER NOT NULL CHECK(size_bytes > 0),
                    sha256 TEXT NOT NULL,
                    duration_seconds REAL NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    audio_track_present INTEGER NOT NULL DEFAULT 0,
                    review_status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(review_status IN ('pending','approved','rejected')),
                    reviewed_by TEXT,
                    reviewed_at TEXT,
                    review_note TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_render_outputs_workspace_review
                ON render_outputs(workspace_id,review_status,created_at)
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS render_output_events(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    reviewer_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    note TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_render_output_events_job
                ON render_output_events(job_id,id)
            """)
            connection.execute("""
                CREATE TRIGGER IF NOT EXISTS render_output_events_no_update
                BEFORE UPDATE ON render_output_events
                BEGIN SELECT RAISE(ABORT,'render output events are immutable'); END
            """)
            connection.execute("""
                CREATE TRIGGER IF NOT EXISTS render_output_events_no_delete
                BEFORE DELETE ON render_output_events
                BEGIN SELECT RAISE(ABORT,'render output events are immutable'); END
            """)

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            yield connection
            if connection.in_transaction:
                connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def _verified_file(self, relative_path, expected_size, expected_sha256, workspace_id):
        if not isinstance(relative_path, str) or not relative_path or Path(relative_path).is_absolute():
            raise RenderOutputError("Render output path is invalid")
        candidate = self.media_root / relative_path
        if candidate.is_symlink() or not candidate.is_file():
            raise RenderOutputError("Render output is missing or is a symlink")
        try:
            path = candidate.resolve(strict=True)
            path.relative_to(self.media_root)
            namespace = hashlib.sha256(workspace_id.encode("utf-8")).hexdigest()
            namespace_dir = self.media_root / namespace
            workspace_output_candidate = namespace_dir / "render-outputs"
            if namespace_dir.is_symlink() or workspace_output_candidate.is_symlink():
                raise RenderOutputError("Workspace output namespace must not be a symlink")
            workspace_output_root = workspace_output_candidate.resolve(strict=True)
            workspace_output_root.relative_to(self.media_root)
            path.relative_to(workspace_output_root)
        except (OSError, ValueError) as exc:
            raise RenderOutputError("Render output escaped workspace namespace media storage") from exc
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                size += len(block)
                digest.update(block)
        if size != expected_size or digest.hexdigest() != expected_sha256:
            raise RenderOutputError("Render output checksum verification failed")
        return path

    def adopt(self, job_id, workspace_id, worker_id, lease_token, attempt, result):
        if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id):
            raise RenderOutputError("Render job ID is invalid")
        if not isinstance(workspace_id, str) or not _WORKSPACE_ID.fullmatch(workspace_id):
            raise RenderOutputError("Render workspace ID is invalid")
        if not isinstance(worker_id, str) or not worker_id or len(worker_id) > 128:
            raise RenderOutputError("Render worker ID is invalid")
        if not isinstance(lease_token, str) or not lease_token:
            raise RenderOutputError("Render worker lease token is required")
        if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
            raise RenderOutputError("Render job attempt is invalid")
        if not isinstance(result, dict) or not _RENDER_ID.fullmatch(str(result.get("render_id", ""))):
            raise RenderOutputError("Render result identity is invalid")
        required = ("media_path", "size_bytes", "sha256", "duration_seconds", "width", "height")
        if any(key not in result for key in required):
            raise RenderOutputError("Render result metadata is incomplete")
        if result["width"] != 1080 or result["height"] != 1920:
            raise RenderOutputError("Render result dimensions are invalid")
        if isinstance(result["size_bytes"], bool) or not isinstance(result["size_bytes"], int) or result["size_bytes"] <= 0:
            raise RenderOutputError("Render result size is invalid")
        if not isinstance(result["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", result["sha256"]):
            raise RenderOutputError("Render result checksum is invalid")
        duration = result["duration_seconds"]
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not 0 < duration <= 180:
            raise RenderOutputError("Render result duration is invalid")
        path = self._verified_file(result["media_path"], result["size_bytes"], result["sha256"], workspace_id)
        relative_path = path.relative_to(self.media_root).as_posix()
        created_at = _now()
        with self.db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = connection.execute("""
                SELECT status,workspace_id,worker_id,lease_token,lease_expires_at,attempt
                FROM pipeline_jobs WHERE id=?
            """, (job_id,)).fetchone()
            if (
                job is None or job["status"] != "running"
                or job["workspace_id"] != workspace_id
                or job["worker_id"] != worker_id
                or job["lease_token"] != lease_token
                or job["attempt"] != attempt
                or not job["lease_expires_at"]
                or job["lease_expires_at"] <= created_at
            ):
                raise RenderOutputLeaseConflict("Render output adoption rejected by the current queue lease")
            connection.execute("""
                INSERT INTO render_outputs(
                    job_id,workspace_id,attempt,worker_id,lease_token,render_id,
                    relative_path,size_bytes,sha256,duration_seconds,width,height,
                    audio_track_present,review_status,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'pending',?)
                ON CONFLICT(job_id) DO UPDATE SET
                    workspace_id=excluded.workspace_id,attempt=excluded.attempt,
                    worker_id=excluded.worker_id,lease_token=excluded.lease_token,
                    render_id=excluded.render_id,relative_path=excluded.relative_path,
                    size_bytes=excluded.size_bytes,sha256=excluded.sha256,
                    duration_seconds=excluded.duration_seconds,width=excluded.width,
                    height=excluded.height,audio_track_present=excluded.audio_track_present,
                    review_status='pending',reviewed_by=NULL,reviewed_at=NULL,
                    review_note=NULL,created_at=excluded.created_at
            """, (
                job_id, workspace_id, attempt, worker_id, lease_token,
                result["render_id"], relative_path, result["size_bytes"],
                result["sha256"], float(duration), result["width"], result["height"],
                int(bool(result.get("audio_track_present"))), created_at,
            ))
        return {
            "job_id": job_id,
            "render_id": result["render_id"],
            "size_bytes": result["size_bytes"],
            "sha256": result["sha256"],
            "duration_seconds": float(duration),
            "width": result["width"],
            "height": result["height"],
            "audio_track_present": bool(result.get("audio_track_present")),
            "review_status": "pending",
            "created_at": created_at,
        }

    def discard_if_stale(self, job_id, workspace_id, attempt, lease_token):
        """Remove an adopted artifact only when its queue attempt is no longer reviewable."""
        stale_path = None
        with self.db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = connection.execute(
                "SELECT status,attempt FROM pipeline_jobs WHERE id=? AND workspace_id=?",
                (job_id,workspace_id),
            ).fetchone()
            output = connection.execute(
                """SELECT relative_path,attempt,lease_token FROM render_outputs
                   WHERE job_id=? AND workspace_id=?""",
                (job_id,workspace_id),
            ).fetchone()
            if (
                output is None or output["attempt"] != attempt
                or output["lease_token"] != lease_token
                or (job is not None and job["status"] == "review_pending" and job["attempt"] == attempt)
            ):
                return False
            stale_path = output["relative_path"]
            connection.execute(
                "DELETE FROM render_outputs WHERE job_id=? AND workspace_id=? AND attempt=? AND lease_token=?",
                (job_id,workspace_id,attempt,lease_token),
            )
        try:
            candidate = self.media_root / stale_path
            if not candidate.is_symlink():
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(self.media_root)
                namespace = hashlib.sha256(workspace_id.encode("utf-8")).hexdigest()
                namespace_dir = self.media_root / namespace
                workspace_output_candidate = namespace_dir / "render-outputs"
                if namespace_dir.is_symlink() or workspace_output_candidate.is_symlink():
                    return True
                workspace_output_root = workspace_output_candidate.resolve(strict=True)
                workspace_output_root.relative_to(self.media_root)
                resolved.relative_to(workspace_output_root)
                resolved.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass
        return True

    def get_reviewable(self, job_id, workspace_id):
        if not isinstance(workspace_id, str) or not _WORKSPACE_ID.fullmatch(workspace_id):
            raise RenderOutputNotFound("Render output not found")
        with self.db() as connection:
            row = connection.execute("""
                SELECT o.* FROM render_outputs o
                JOIN pipeline_jobs j ON j.id=o.job_id
                WHERE o.job_id=? AND o.workspace_id=?
                  AND j.workspace_id=o.workspace_id
                  AND j.status='review_pending' AND j.attempt=o.attempt
            """, (job_id, workspace_id)).fetchone()
        if row is None:
            raise RenderOutputNotFound("Render output not found")
        path = self._verified_file(row["relative_path"], row["size_bytes"], row["sha256"], workspace_id)
        return {
            "job_id": row["job_id"],
            "render_id": row["render_id"],
            "path": path,
            "size_bytes": row["size_bytes"],
            "sha256": row["sha256"],
            "duration_seconds": row["duration_seconds"],
            "width": row["width"],
            "height": row["height"],
            "audio_track_present": bool(row["audio_track_present"]),
            "review_status": row["review_status"],
            "reviewed_by": row["reviewed_by"],
            "reviewed_at": row["reviewed_at"],
            "review_note": row["review_note"],
            "created_at": row["created_at"],
        }

    def decide(self, job_id, workspace_id, reviewer_id, decision, note=""):
        if decision not in {"approved", "rejected"}:
            raise ValueError("Review decision must be approved or rejected")
        if not isinstance(reviewer_id, str) or not reviewer_id.strip():
            raise ValueError("Authenticated reviewer is required")
        note = str(note or "")[:2000]
        with self.db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("""
                SELECT o.review_status FROM render_outputs o
                JOIN pipeline_jobs j ON j.id=o.job_id
                WHERE o.job_id=? AND o.workspace_id=?
                  AND j.workspace_id=o.workspace_id
                  AND j.status='review_pending' AND j.attempt=o.attempt
            """, (job_id, workspace_id)).fetchone()
            if row is None:
                raise RenderOutputNotFound("Render output not found")
            if row["review_status"] != "pending":
                raise ValueError("Render output has already received a review decision")
            reviewed_at = _now()
            connection.execute("""
                UPDATE render_outputs
                SET review_status=?,reviewed_by=?,reviewed_at=?,review_note=?
                WHERE job_id=? AND workspace_id=?
            """, (decision, reviewer_id.strip(), reviewed_at, note, job_id, workspace_id))
            connection.execute("""
                INSERT INTO render_output_events(
                    job_id,workspace_id,event_type,reviewer_id,decision,note,created_at
                ) VALUES(?,?,?,?,?,?,?)
            """, (
                job_id,workspace_id,"review_decided",reviewer_id.strip(),
                decision,note,reviewed_at,
            ))
        return self.get_reviewable(job_id, workspace_id)

    def events(self, job_id, workspace_id):
        with self.db() as connection:
            rows = connection.execute("""
                SELECT id,event_type,reviewer_id,decision,note,created_at
                FROM render_output_events
                WHERE job_id=? AND workspace_id=? ORDER BY id
            """, (job_id,workspace_id)).fetchall()
        return [dict(row) for row in rows]
