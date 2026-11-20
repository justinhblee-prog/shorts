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
            media = metadata.get("media_metadata")
            if media is not None and not media.get("has_video"):
                raise SnapshotError("video clips must reference a probed video asset")
            if clip["source_out_ms"] > metadata.get("duration_ms", float("inf")):
                raise EDLValidationError("source trim exceeds registered media duration")
        for track in normalized["audio_tracks"]:
            metadata = self.assets.get_asset(workspace_id, principal_id, track["asset_id"])
            if metadata["scan_status"] != "clean":
                raise SnapshotError("all referenced audio assets must pass malware scanning")
            media = metadata.get("media_metadata")
            if media is not None and not media.get("has_audio"):
                raise SnapshotError("audio tracks must reference a probed audio asset")
            if track["source_out_ms"] > metadata.get("duration_ms", float("inf")):
                raise EDLValidationError("audio source trim exceeds registered media duration")

        serialized = json.dumps(normalized, ensure_ascii=False, sort_keys=True,
                                separators=(",", ":"), allow_nan=False)
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
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
            with self._db() as db:
                db.execute("BEGIN IMMEDIATE")
                existing = db.execute("""
                    SELECT * FROM timeline_edl_snapshots
                    WHERE workspace_id=? AND idempotency_key=?
                """, (workspace_id, idempotency_key)).fetchone()
                if existing:
                    existing = dict(existing)
                    if existing["payload_sha256"] != digest:
                        raise SnapshotConflict(
                            "idempotency key was already used for a different EDL"
                        )
                    db.commit()
                    return self._public(existing, replayed=True)

                job = self.queue.enqueue(
                    "timeline_render", job_payload, idempotency_key=job_key,
                    workspace_id=workspace_id, max_attempts=3, connection=db,
                )
                db.execute("""
                    INSERT INTO timeline_edl_snapshots
                    (id,workspace_id,creator_principal_id,idempotency_key,payload_json,
                     payload_sha256,render_job_id,created_at)
                    VALUES(?,?,?,?,?,?,?,?)
                """, (snapshot_id, workspace_id, principal_id, idempotency_key,
                      serialized, digest, job["id"], now))
                db.commit()
        except IdempotencyConflict as exc:
            raise SnapshotConflict(
                "render idempotency key conflicts with an existing queue job"
            ) from exc
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
