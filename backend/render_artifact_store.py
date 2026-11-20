"""Lease-fenced, checksum-verified adoption of private render artifacts.

The renderer writes only to a private staging directory. Adoption moves a
completed file into the artifact directory while holding the queue's SQLite
write lock and after re-validating the live lease and worker generation.
Artifacts are review-pending outputs, never published media.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from queue_store import LeaseConflict
from ffprobe_validate import probe_media

_ARTIFACT_ID = re.compile(r"^rart_[a-f0-9]{32}$")
_ALLOWED_SUFFIXES = {".mp4", ".m4a", ".aac"}


class ArtifactAdoptionError(RuntimeError):
    """A staged render could not be safely adopted."""


class RenderArtifactStore:
    def __init__(self, queue, staging_root, artifact_root, max_bytes=2_000_000_000,
                 ffprobe_path=None, require_audio=False, max_duration_ms=3_600_000):
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
            raise ValueError("max_bytes must be a positive integer")
        self.queue = queue
        self.staging_root = Path(staging_root).resolve()
        self.artifact_root = Path(artifact_root).resolve()
        self.max_bytes = max_bytes
        if not isinstance(require_audio, bool):
            raise ValueError("require_audio must be boolean")
        if (isinstance(max_duration_ms, bool) or not isinstance(max_duration_ms, int)
                or not 1 <= max_duration_ms <= 3_600_000):
            raise ValueError("max_duration_ms must be between 1 and 3600000")
        self.ffprobe_path = ffprobe_path
        self.require_audio = require_audio
        self.max_duration_ms = max_duration_ms
        self.staging_root.mkdir(parents=True, exist_ok=True)
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        if self.staging_root == self.artifact_root:
            raise ValueError("staging and artifact roots must be distinct")
        with self.queue.db() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS render_artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL UNIQUE REFERENCES pipeline_jobs(id) ON DELETE RESTRICT,
                    workspace_id TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    snapshot_sha256 TEXT NOT NULL CHECK(length(snapshot_sha256)=64),
                    artifact_sha256 TEXT NOT NULL CHECK(length(artifact_sha256)=64),
                    byte_size INTEGER NOT NULL CHECK(byte_size > 0),
                    media_suffix TEXT NOT NULL,
                    storage_key TEXT NOT NULL UNIQUE,
                    probe_json TEXT,
                    duration_ms INTEGER,
                    video_width INTEGER,
                    video_height INTEGER,
                    audio_streams INTEGER,
                    created_at TEXT NOT NULL
                )
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(render_artifacts)")}
            for name, declaration in (
                ("probe_json", "TEXT"),
                ("duration_ms", "INTEGER"),
                ("video_width", "INTEGER"),
                ("video_height", "INTEGER"),
                ("audio_streams", "INTEGER"),
            ):
                if name not in columns:
                    db.execute(f"ALTER TABLE render_artifacts ADD COLUMN {name} {declaration}")
            db.execute("""CREATE TRIGGER IF NOT EXISTS render_artifacts_no_update
                BEFORE UPDATE ON render_artifacts
                BEGIN SELECT RAISE(ABORT,'render artifacts are immutable'); END""")
            db.execute("""CREATE TRIGGER IF NOT EXISTS render_artifacts_no_delete
                BEFORE DELETE ON render_artifacts
                BEGIN SELECT RAISE(ABORT,'render artifacts are immutable'); END""")

    @staticmethod
    def _sha256(path):
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                digest.update(chunk)
        return digest.hexdigest(), size

    def adopt(self, job_id, worker_id, lease_token, generation_token,
              workspace_id, snapshot_id, snapshot_sha256, staged_path):
        if not isinstance(snapshot_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", snapshot_sha256):
            raise ArtifactAdoptionError("snapshot SHA-256 is invalid")
        if not isinstance(snapshot_id, str) or not snapshot_id:
            raise ArtifactAdoptionError("snapshot ID is required")
        candidate = Path(staged_path)
        if candidate.is_symlink():
            raise ArtifactAdoptionError("staged output must not be a symlink")
        try:
            source = candidate.resolve(strict=True)
            source.relative_to(self.staging_root)
        except (OSError, ValueError) as exc:
            raise ArtifactAdoptionError("staged output must be inside the private staging root") from exc
        if not source.is_file():
            raise ArtifactAdoptionError("staged output must be a regular file")
        suffix = source.suffix.lower()
        if suffix not in _ALLOWED_SUFFIXES:
            raise ArtifactAdoptionError("render output extension is not allowed")
        digest, size = self._sha256(source)
        if size < 1 or size > self.max_bytes:
            raise ArtifactAdoptionError("render output size is outside configured limits")
        probe = None
        if self.ffprobe_path is not None:
            probe = probe_media(
                source, self.ffprobe_path, max_duration_ms=self.max_duration_ms,
                max_bytes=self.max_bytes, require_audio=self.require_audio,
            )
            verified_digest, verified_size = self._sha256(source)
            if verified_digest != digest or verified_size != size:
                raise ArtifactAdoptionError("staged media changed during ffprobe validation")
        artifact_id = "rart_" + uuid.uuid4().hex
        storage_key = artifact_id + suffix
        destination = self.artifact_root / storage_key
        if source.stat().st_dev != self.artifact_root.stat().st_dev:
            raise ArtifactAdoptionError("staging and artifact roots must share a filesystem")
        timestamp = datetime.now(timezone.utc).isoformat()

        moved = False
        try:
            with self.queue.db() as db:
                db.execute("BEGIN IMMEDIATE")
                self.queue._assert_worker_generation(db, worker_id, generation_token)
                job = db.execute(
                    "SELECT * FROM pipeline_jobs WHERE id=? AND workspace_id=?",
                    (job_id, workspace_id),
                ).fetchone()
                self.queue.assert_lease(
                    job, worker_id, lease_token, timestamp, workspace_id
                )
                payload = self.queue.decode(job)["payload"]
                if payload.get("snapshot_id") != snapshot_id or payload.get("snapshot_sha256") != snapshot_sha256:
                    raise ArtifactAdoptionError("artifact does not match the claimed EDL snapshot")
                # Re-check after acquiring the write lock, immediately before
                # moving the file. No other worker can reclaim this lease here.
                self.queue.assert_lease(job, worker_id, lease_token, timestamp, workspace_id)
                # Flush file data before rename. Windows requires a writable
                # handle for FlushFileBuffers; the staging file is worker-owned.
                with source.open("rb+") as stream:
                    os.fsync(stream.fileno())
                os.replace(source, destination)
                moved = True
                # POSIX supports fsync on directory descriptors. Windows does
                # not expose equivalent directory handles through os.open.
                if os.name != "nt":
                    dir_fd = os.open(self.artifact_root, os.O_RDONLY)
                    try:
                        os.fsync(dir_fd)
                    finally:
                        os.close(dir_fd)
                db.execute("""
                    INSERT INTO render_artifacts
                    (artifact_id,job_id,workspace_id,snapshot_id,snapshot_sha256,
                     artifact_sha256,byte_size,media_suffix,storage_key,probe_json,
                     duration_ms,video_width,video_height,audio_streams,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (artifact_id, job_id, workspace_id, snapshot_id, snapshot_sha256,
                      digest, size, suffix, storage_key,
                      json.dumps(probe, sort_keys=True) if probe is not None else None,
                      probe["duration_ms"] if probe is not None else None,
                      probe["video_streams"][0]["width"] if probe is not None else None,
                      probe["video_streams"][0]["height"] if probe is not None else None,
                      probe["audio_streams"] if probe is not None else None,
                      timestamp))
                updated = db.execute("""
                    UPDATE pipeline_jobs
                    SET status='review_pending',worker_id=NULL,lease_token=NULL,
                        lease_expires_at=NULL,completed_at=?,updated_at=?
                    WHERE id=? AND status='running' AND worker_id=? AND lease_token=?
                """, (timestamp, timestamp, job_id, worker_id, lease_token))
                if updated.rowcount != 1:
                    raise LeaseConflict("render lease changed before artifact handoff")
                self.queue.event(
                    db, job_id, "completed", "running", "review_pending", worker_id,
                    {"artifact_id": artifact_id, "snapshot_id": snapshot_id,
                     "artifact_sha256": digest, "review_required": True},
                    created_at=timestamp,
                )
                db.commit()
        except Exception:
            if moved:
                try:
                    if destination.exists() and not source.exists():
                        os.replace(destination, source)
                    else:
                        destination.unlink(missing_ok=True)
                except OSError:
                    try:
                        destination.unlink(missing_ok=True)
                    except OSError:
                        pass
            raise
        return {
            "artifact_id": artifact_id,
            "job_id": job_id,
            "workspace_id": workspace_id,
            "snapshot_id": snapshot_id,
            "snapshot_sha256": snapshot_sha256,
            "artifact_sha256": digest,
            "byte_size": size,
            "storage_key": storage_key,
            "status": "review_pending",
        }



    def discard_staged(self, staged_path):
        """Delete a failed or lease-abandoned staged output inside the private root."""
        candidate = Path(staged_path)
        if candidate.is_symlink():
            raise ArtifactAdoptionError("refusing to discard a staged symlink")
        try:
            source = candidate.resolve(strict=False)
            source.relative_to(self.staging_root)
        except (OSError, ValueError) as exc:
            raise ArtifactAdoptionError("staged cleanup path escaped the private staging root") from exc
        if source.exists() and source.is_file():
            source.unlink()
            return True
        return False

    def reconcile_orphaned_files(self, grace_seconds=3600):
        """Remove unindexed generated files after a crash-safe grace period.

        The queue write lock prevents racing an in-flight adoption. Only files
        matching this store's generated key format are eligible for removal.
        """
        if (isinstance(grace_seconds, bool)
                or not isinstance(grace_seconds, (int, float))
                or grace_seconds < 0):
            raise ValueError("grace_seconds must be a non-negative number")
        cutoff = time.time() - grace_seconds
        removed = 0
        removed_bytes = 0
        with self.queue.db() as db:
            db.execute("BEGIN IMMEDIATE")
            known = {
                row["storage_key"]
                for row in db.execute("SELECT storage_key FROM render_artifacts")
            }
            for path in self.artifact_root.iterdir():
                if (path.is_symlink() or not path.is_file()
                        or not re.fullmatch(r"rart_[a-f0-9]{32}\.(mp4|m4a|aac)", path.name)
                        or path.name in known):
                    continue
                try:
                    stat = path.stat()
                    if stat.st_mtime > cutoff:
                        continue
                    path.unlink()
                    removed += 1
                    removed_bytes += stat.st_size
                except FileNotFoundError:
                    continue
            db.commit()
        return {"removed": removed, "removed_bytes": removed_bytes}

    def get(self, artifact_id, workspace_id):
        if not isinstance(artifact_id, str) or not _ARTIFACT_ID.fullmatch(artifact_id):
            raise ValueError("invalid artifact ID")
        with self.queue.db() as db:
            row = db.execute(
                "SELECT * FROM render_artifacts WHERE artifact_id=? AND workspace_id=?",
                (artifact_id, workspace_id),
            ).fetchone()
        if row is None:
            raise ArtifactAdoptionError("artifact not found")
        result = dict(row)
        path = self.artifact_root / result["storage_key"]
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(self.artifact_root)
        except (OSError, ValueError) as exc:
            raise ArtifactAdoptionError("adopted artifact is missing or outside private storage") from exc
        digest, size = self._sha256(resolved)
        if digest != result["artifact_sha256"] or size != result["byte_size"]:
            raise ArtifactAdoptionError("adopted artifact integrity check failed")
        return result
