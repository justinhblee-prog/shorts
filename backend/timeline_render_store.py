"""Immutable, workspace-owned EDL snapshots connected to the durable render queue.

This service deliberately creates queue records only. It does not claim that a
render worker consumes timeline_render jobs or that an MP4 has been produced.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from queue_store import JobQueue, IdempotencyConflict
from timeline_edl import validate_edl, EDLValidationError
from workspace_asset_store import WorkspaceAssetStore, AssetError, AssetNotFound
from workspace_store import WorkspaceStore

_SNAPSHOT_ID = re.compile(r"^edl_[a-f0-9]{32}$")


class SnapshotError(RuntimeError):
    pass


class SnapshotConflict(SnapshotError):
    pass


class TimelineRenderStore:
    def __init__(self, db_path, asset_store: WorkspaceAssetStore,
                 workspace_store: WorkspaceStore, queue: JobQueue | None = None):
        self.db_path = str(db_path)
        self.assets = asset_store
        self.workspaces = workspace_store
        self.queue = queue or JobQueue(self.db_path)
        with self._db() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS timeline_edl_snapshots (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
                    creator_principal_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
                    render_job_id TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    UNIQUE(workspace_id,idempotency_key)
                )
            """)
            db.execute("""CREATE TRIGGER IF NOT EXISTS timeline_edl_snapshots_no_update
                BEFORE UPDATE ON timeline_edl_snapshots
                BEGIN SELECT RAISE(ABORT,'EDL snapshots are immutable'); END""")
            db.execute("""CREATE TRIGGER IF NOT EXISTS timeline_edl_snapshots_no_delete
                BEFORE DELETE ON timeline_edl_snapshots
                BEGIN SELECT RAISE(ABORT,'EDL snapshots are immutable'); END""")
            db.execute("""
                CREATE TABLE IF NOT EXISTS timeline_render_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_id TEXT NOT NULL REFERENCES timeline_edl_snapshots(id) ON DELETE RESTRICT,
                    workspace_id TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    reviewer_id TEXT NOT NULL,
                    decision TEXT NOT NULL CHECK(decision IN ('approved','rejected','revision_requested')),
                    comment TEXT NOT NULL DEFAULT '',
                    artifact_sha256 TEXT NOT NULL CHECK(length(artifact_sha256)=64),
                    created_at TEXT NOT NULL,
                    UNIQUE(snapshot_id)
                )
            """)
            db.execute("""CREATE TRIGGER IF NOT EXISTS timeline_render_reviews_no_update
                BEFORE UPDATE ON timeline_render_reviews
                BEGIN SELECT RAISE(ABORT,'timeline render reviews are immutable'); END""")
            db.execute("""CREATE TRIGGER IF NOT EXISTS timeline_render_reviews_no_delete
                BEFORE DELETE ON timeline_render_reviews
                BEGIN SELECT RAISE(ABORT,'timeline render reviews are immutable'); END""")

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=30000")
        try:
            yield db
        except Exception:
            if db.in_transaction:
                db.rollback()
            raise
        finally:
            db.close()

    def submit(self, workspace_id, principal_id, payload, idempotency_key):
        self.workspaces.require_membership(
            workspace_id, principal_id, minimum_roles={"owner", "admin", "editor"}
        )
        if (not isinstance(idempotency_key, str) or
                not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}", idempotency_key)):
            raise ValueError("idempotency_key must contain 8 to 128 safe characters")
        normalized = validate_edl(payload)
        for clip in normalized["clips"]:
            if clip["type"] != "video":
                continue
            metadata = self.assets.get_asset(workspace_id, principal_id, clip["asset_id"])
            if metadata["scan_status"] != "clean":
                raise SnapshotError("all referenced assets must pass malware scanning")
            if clip["source_out_ms"] > metadata.get("duration_ms", float("inf")):
                raise EDLValidationError("source trim exceeds registered media duration")

        serialized = json.dumps(normalized, ensure_ascii=False, sort_keys=True,
                                separators=(",", ":"), allow_nan=False)
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        existing = self._existing(workspace_id, idempotency_key)
        if existing:
            if existing["payload_sha256"] != digest:
                raise SnapshotConflict("idempotency key was already used for a different EDL")
            return self._public(existing, replayed=True)

        snapshot_id = "edl_" + uuid.uuid4().hex
        job_key = "timeline:" + workspace_id + ":" + idempotency_key
        now = datetime.now(timezone.utc).isoformat()
        job_payload = {
            "snapshot_id": snapshot_id,
            "snapshot_sha256": digest,
            "creator_principal_id": principal_id,
            "edl": normalized,
        }
        try:
            job = self.queue.enqueue(
                "timeline_render", job_payload, idempotency_key=job_key,
                workspace_id=workspace_id, max_attempts=3,
            )
        except IdempotencyConflict as exc:
            raise SnapshotConflict("render idempotency key conflicts with an existing queue job") from exc
        try:
            with self._db() as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("""
                    INSERT INTO timeline_edl_snapshots
                    (id,workspace_id,creator_principal_id,idempotency_key,payload_json,
                     payload_sha256,render_job_id,created_at)
                    VALUES(?,?,?,?,?,?,?,?)
                """, (snapshot_id, workspace_id, principal_id, idempotency_key,
                      serialized, digest, job["id"], now))
                db.commit()
        except sqlite3.IntegrityError as exc:
            raise SnapshotConflict("snapshot idempotency key already exists") from exc
        return {
            "snapshot_id": snapshot_id, "workspace_id": workspace_id,
            "render_job_id": job["id"], "payload_sha256": digest,
            "status": job["status"], "replayed": False,
        }

    def _existing(self, workspace_id, idempotency_key):
        with self._db() as db:
            row = db.execute("""
                SELECT * FROM timeline_edl_snapshots
                WHERE workspace_id=? AND idempotency_key=?
            """, (workspace_id, idempotency_key)).fetchone()
        return dict(row) if row else None

    def get(self, workspace_id, principal_id, snapshot_id):
        self.workspaces.require_membership(workspace_id, principal_id)
        if not isinstance(snapshot_id, str) or not _SNAPSHOT_ID.fullmatch(snapshot_id):
            raise ValueError("invalid snapshot ID")
        with self._db() as db:
            row = db.execute("""
                SELECT * FROM timeline_edl_snapshots
                WHERE id=? AND workspace_id=?
            """, (snapshot_id, workspace_id)).fetchone()
        if row is None:
            raise SnapshotError("snapshot not found")
        result = dict(row)
        actual = hashlib.sha256(result["payload_json"].encode("utf-8")).hexdigest()
        if actual != result["payload_sha256"]:
            raise SnapshotError("immutable snapshot integrity check failed")
        result["payload"] = json.loads(result.pop("payload_json"))
        return result

    @staticmethod
    def _public(row, replayed):
        return {
            "snapshot_id": row["id"], "workspace_id": row["workspace_id"],
            "render_job_id": row["render_job_id"],
            "payload_sha256": row["payload_sha256"],
            "status": "queued", "replayed": replayed,
        }


    def list_pending_reviews(self, workspace_id, principal_id, limit=50):
        self.workspaces.require_membership(workspace_id, principal_id)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        with self._db() as db:
            rows = db.execute("""
                SELECT s.id AS snapshot_id,s.render_job_id,s.payload_sha256,
                       s.creator_principal_id,s.created_at,
                       a.artifact_id,a.artifact_sha256,a.byte_size,a.duration_ms,
                       a.video_width,a.video_height,a.audio_streams
                FROM timeline_edl_snapshots s
                JOIN pipeline_jobs j ON j.id=s.render_job_id
                JOIN render_artifacts a ON a.job_id=s.render_job_id
                    AND a.workspace_id=s.workspace_id
                LEFT JOIN timeline_render_reviews r ON r.snapshot_id=s.id
                WHERE s.workspace_id=? AND j.status='review_pending' AND r.id IS NULL
                ORDER BY s.created_at ASC LIMIT ?
            """, (workspace_id, limit)).fetchall()
        return [{
            **dict(row),
            "preview_url": f"/api/timeline/artifacts/{row['artifact_id']}/preview",
            "status": "review_pending",
        } for row in rows]

    def review_status(self, workspace_id, principal_id, snapshot_id):
        self.workspaces.require_membership(workspace_id, principal_id)
        snapshot = self.get(workspace_id, principal_id, snapshot_id)
        with self._db() as db:
            row = db.execute("""
                SELECT reviewer_id,decision,comment,artifact_sha256,created_at
                FROM timeline_render_reviews WHERE snapshot_id=? AND workspace_id=?
            """, (snapshot_id, workspace_id)).fetchone()
        if row is None:
            return {"status": "review_pending", "decision": None}
        return {"status": row["decision"], **dict(row)}

    def review_decide(self, workspace_id, reviewer_id, snapshot_id, decision, comment=""):
        self.workspaces.require_membership(workspace_id, reviewer_id)
        if not isinstance(decision, str) or decision not in {
            "approved", "rejected", "revision_requested"
        }:
            raise ValueError("unsupported timeline review decision")
        if not isinstance(comment, str) or len(comment) > 4000:
            raise ValueError("review comment must be at most 4000 characters")
        if any((ord(ch) < 32 and ch not in "\n\t") or ord(ch) == 127 for ch in comment):
            raise ValueError("review comment contains unsupported control characters")
        timestamp = datetime.now(timezone.utc).isoformat()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            snapshot = db.execute("""
                SELECT id,render_job_id,payload_sha256 FROM timeline_edl_snapshots
                WHERE id=? AND workspace_id=?
            """, (snapshot_id, workspace_id)).fetchone()
            if snapshot is None:
                raise SnapshotError("EDL snapshot not found")
            job = db.execute("""
                SELECT status FROM pipeline_jobs
                WHERE id=? AND workspace_id=? AND job_type='timeline_render'
            """, (snapshot["render_job_id"], workspace_id)).fetchone()
            if job is None or job["status"] != "review_pending":
                raise SnapshotConflict("render output is not awaiting review")
            artifact = db.execute("""
                SELECT artifact_sha256 FROM render_artifacts
                WHERE job_id=? AND workspace_id=? AND snapshot_id=?
                  AND snapshot_sha256=?
            """, (snapshot["render_job_id"], workspace_id, snapshot_id,
                  snapshot["payload_sha256"])).fetchone()
            if artifact is None:
                raise SnapshotConflict("verified render artifact is not available for review")
            try:
                db.execute("""
                    INSERT INTO timeline_render_reviews
                    (snapshot_id,workspace_id,job_id,reviewer_id,decision,comment,
                     artifact_sha256,created_at)
                    VALUES(?,?,?,?,?,?,?,?)
                """, (snapshot_id,workspace_id,snapshot["render_job_id"],reviewer_id,
                      decision,comment,artifact["artifact_sha256"],timestamp))
            except sqlite3.IntegrityError as exc:
                raise SnapshotConflict("this immutable render snapshot already has a review decision") from exc
            db.commit()
        return {
            "snapshot_id": snapshot_id, "workspace_id": workspace_id,
            "render_job_id": snapshot["render_job_id"], "reviewer_id": reviewer_id,
            "decision": decision, "comment": comment,
            "artifact_sha256": artifact["artifact_sha256"], "created_at": timestamp,
        }
