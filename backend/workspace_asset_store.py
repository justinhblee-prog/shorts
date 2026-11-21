"""Workspace-owned private media asset staging and metadata registry.

This is a storage primitive, not an upload API. Callers must pass an authenticated
principal; assets remain quarantined until an external scanner/probe marks them
ready. Filesystem isolation and quotas still belong to the worker/container layer.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from workspace_store import WorkspaceDenied, WorkspaceStore

_ASSET_ID = re.compile(r"^asset_[a-f0-9]{32}$")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_. -]{0,127}$")
_ALLOWED_ROLES = {"owner", "admin", "editor"}


class AssetError(RuntimeError):
    """Asset registration or access failed."""


class AssetNotFound(AssetError):
    """Asset does not exist in the requested workspace."""


class AssetConflict(AssetError):
    """Asset content or identifier conflicts with an existing record."""


def _utcnow():
    return datetime.now(timezone.utc)


def _safe_root(value):
    root = Path(value)
    if not root.is_absolute():
        raise ValueError("asset storage root must be absolute")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("asset storage root must be a real directory")
    return root.resolve(strict=True)


class WorkspaceAssetStore:
    """Persist private, hash-verified assets scoped to durable workspace members."""

    def __init__(self, db_path=None, storage_root=None, workspace_store=None,
                 max_asset_bytes=256 * 1024 * 1024,
                 max_workspace_bytes=2 * 1024**3):
        if isinstance(max_asset_bytes, bool) or not isinstance(max_asset_bytes, int) or not 1 <= max_asset_bytes <= 2 * 1024**3:
            raise ValueError("max_asset_bytes must be between 1 byte and 2 GiB")
        self.db_path = str(db_path or os.getenv("NEXUS_DB_PATH") or "data/nexus.sqlite3")
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        configured_root = storage_root or os.getenv("NEXUS_PRIVATE_MEDIA_ROOT")
        if not configured_root:
            raise ValueError("NEXUS_PRIVATE_MEDIA_ROOT or storage_root is required")
        self.storage_root = _safe_root(configured_root)
        if (isinstance(max_workspace_bytes, bool)
                or not isinstance(max_workspace_bytes, int)
                or not max_asset_bytes <= max_workspace_bytes <= 20 * 1024**4):
            raise ValueError("max_workspace_bytes must be between max_asset_bytes and 20 TiB")
        self.max_asset_bytes = max_asset_bytes
        self.max_workspace_bytes = max_workspace_bytes
        self.workspaces = workspace_store or WorkspaceStore(self.db_path)
        with self.db() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS workspace_media_assets (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
                    owner_principal_id TEXT NOT NULL,
                    original_name TEXT NOT NULL,
                    byte_size INTEGER NOT NULL CHECK(byte_size > 0),
                    sha256 TEXT NOT NULL CHECK(length(sha256) = 64),
                    storage_name TEXT NOT NULL UNIQUE,
                    scan_status TEXT NOT NULL CHECK(scan_status IN ('pending','clean','rejected')),
                    status TEXT NOT NULL CHECK(status IN ('active','deleted')),
                    created_at TEXT NOT NULL,
                    retention_until TEXT NOT NULL,
                    duration_ms INTEGER,
                    media_metadata_json TEXT,
                    probed_at TEXT,
                    UNIQUE(workspace_id, sha256)
                )
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(workspace_media_assets)")}
            for name, declaration in (
                ("duration_ms", "INTEGER"),
                ("media_metadata_json", "TEXT"),
                ("probed_at", "TEXT"),
            ):
                if name not in columns:
                    db.execute(f"ALTER TABLE workspace_media_assets ADD COLUMN {name} {declaration}")
            db.execute("""CREATE INDEX IF NOT EXISTS idx_workspace_assets_owner
                          ON workspace_media_assets(workspace_id, owner_principal_id, status)""")
            db.execute("""
                CREATE TABLE IF NOT EXISTS workspace_asset_upload_reservations (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    byte_size INTEGER NOT NULL CHECK(byte_size > 0),
                    expires_at TEXT NOT NULL
                )
            """)
            db.execute("""CREATE INDEX IF NOT EXISTS idx_workspace_asset_reservations
                          ON workspace_asset_upload_reservations(workspace_id, expires_at)""")

    @contextmanager
    def db(self):
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

    def _workspace_dir(self, workspace_id):
        target = self.storage_root / workspace_id
        target.mkdir(mode=0o700, exist_ok=True)
        if target.is_symlink() or not target.is_dir():
            raise AssetError("workspace storage directory is unsafe")
        resolved = target.resolve(strict=True)
        if resolved.parent != self.storage_root:
            raise AssetError("workspace storage escaped private root")
        return resolved

    def register_stream(self, workspace_id, principal_id, stream, original_name,
                        *, retention_days=30):
        """Stage a binary stream and atomically reserve workspace storage capacity."""
        self.workspaces.require_membership(
            workspace_id, principal_id, minimum_roles=_ALLOWED_ROLES
        )
        if not isinstance(original_name, str) or not _SAFE_NAME.fullmatch(original_name):
            raise ValueError("asset filename is invalid")
        if (isinstance(retention_days, bool) or not isinstance(retention_days, int)
                or not 1 <= retention_days <= 3650):
            raise ValueError("retention_days must be between 1 and 3650")
        if not hasattr(stream, "read"):
            raise TypeError("asset source must be a readable binary stream")

        workspace_dir = self._workspace_dir(workspace_id)
        fd, temp_name = tempfile.mkstemp(prefix=".upload-", dir=str(workspace_dir))
        temp_path = Path(temp_name)
        digest = hashlib.sha256()
        size = 0
        asset_id = "asset_" + uuid.uuid4().hex
        storage_name = asset_id + ".blob"
        final_path = workspace_dir / storage_name
        reservation_id = "reservation_" + uuid.uuid4().hex
        adopted_path = None
        reserved = False
        try:
            with os.fdopen(fd, "wb") as output:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    if not isinstance(chunk, (bytes, bytearray)):
                        raise TypeError("asset stream must return bytes")
                    size += len(chunk)
                    if size > self.max_asset_bytes:
                        raise AssetError("asset exceeds configured byte limit")
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if size == 0:
                raise AssetError("empty assets are not accepted")

            now = _utcnow()
            now_iso = now.isoformat()
            expires_at = (now + timedelta(minutes=10)).isoformat()
            # SQLite's write lock serializes reservations. The active asset bytes
            # and all unexpired reservations are counted in the same transaction,
            # so simultaneous uploads cannot overcommit the workspace quota.
            with self.db() as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    "DELETE FROM workspace_asset_upload_reservations WHERE expires_at<=?",
                    (now_iso,),
                )
                active = db.execute("""
                    SELECT COALESCE(SUM(byte_size),0) AS total
                    FROM workspace_media_assets
                    WHERE workspace_id=? AND status='active'
                """, (workspace_id,)).fetchone()["total"]
                pending = db.execute("""
                    SELECT COALESCE(SUM(byte_size),0) AS total
                    FROM workspace_asset_upload_reservations
                    WHERE workspace_id=?
                """, (workspace_id,)).fetchone()["total"]
                if active + pending + size > self.max_workspace_bytes:
                    db.rollback()
                    raise AssetError("workspace storage quota exceeded")
                db.execute("""
                    INSERT INTO workspace_asset_upload_reservations
                    (id,workspace_id,byte_size,expires_at) VALUES(?,?,?,?)
                """, (reservation_id, workspace_id, size, expires_at))
                db.commit()
                reserved = True

            try:
                os.link(temp_path, final_path)
            except FileExistsError as exc:
                raise AssetConflict("asset storage identifier collision") from exc
            adopted_path = final_path
            retention_until = now + timedelta(days=retention_days)
            with self.db() as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("""
                    INSERT INTO workspace_media_assets
                    (id,workspace_id,owner_principal_id,original_name,byte_size,sha256,
                     storage_name,scan_status,status,created_at,retention_until)
                    VALUES(?,?,?,?,?,?,?,'pending','active',?,?)
                """, (asset_id, workspace_id, principal_id, original_name, size,
                      digest.hexdigest(), storage_name, now_iso,
                      retention_until.isoformat()))
                released = db.execute("""
                    DELETE FROM workspace_asset_upload_reservations
                    WHERE id=? AND workspace_id=?
                """, (reservation_id, workspace_id))
                if released.rowcount != 1:
                    raise AssetError("workspace upload reservation expired before commit")
                db.commit()
                reserved = False
            return {
                "asset_id": asset_id, "workspace_id": workspace_id,
                "owner_principal_id": principal_id, "original_name": original_name,
                "size_bytes": size, "sha256": digest.hexdigest(),
                "scan_status": "pending", "status": "active",
                "retention_until": retention_until.isoformat(),
            }
        except sqlite3.IntegrityError as exc:
            if adopted_path is not None:
                adopted_path.unlink(missing_ok=True)
            raise AssetConflict("identical content is already registered in this workspace") from exc
        except Exception:
            if adopted_path is not None:
                adopted_path.unlink(missing_ok=True)
            raise
        finally:
            temp_path.unlink(missing_ok=True)
            if reserved:
                try:
                    with self.db() as db:
                        db.execute("BEGIN IMMEDIATE")
                        db.execute(
                            "DELETE FROM workspace_asset_upload_reservations WHERE id=?",
                            (reservation_id,),
                        )
                        db.commit()
                except sqlite3.Error:
                    # The short reservation expires automatically if cleanup cannot
                    # reach SQLite (for example, a process or database interruption).
                    pass

    def get_asset(self, workspace_id, principal_id, asset_id):
        self.workspaces.require_membership(workspace_id, principal_id)
        if not isinstance(asset_id, str) or not _ASSET_ID.fullmatch(asset_id):
            raise ValueError("invalid asset ID")
        with self.db() as db:
            row = db.execute("""
                SELECT id,workspace_id,owner_principal_id,original_name,byte_size,
                       sha256,scan_status,status,created_at,retention_until,
                       duration_ms,media_metadata_json,probed_at
                FROM workspace_media_assets
                WHERE id=? AND workspace_id=? AND status='active'
            """, (asset_id, workspace_id)).fetchone()
        if row is None:
            raise AssetNotFound("asset not found in this workspace")
        result = dict(row)
        raw_metadata = result.pop("media_metadata_json", None)
        try:
            result["media_metadata"] = json.loads(raw_metadata) if raw_metadata else None
        except (TypeError, ValueError):
            raise AssetError("stored media probe metadata is invalid")
        return result

    def path_for_scan(self, workspace_id, principal_id, asset_id):
        """Resolve a pending private asset for an internal scanner/probe only."""
        metadata = self.get_asset(workspace_id, principal_id, asset_id)
        if metadata["scan_status"] != "pending":
            raise AssetError("only pending assets may be scanned")
        path = self._workspace_dir(workspace_id) / (asset_id + ".blob")
        if path.is_symlink() or not path.is_file():
            raise AssetNotFound("asset binary is unavailable")
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                size += len(chunk)
                digest.update(chunk)
        if size != metadata["byte_size"] or digest.hexdigest() != metadata["sha256"]:
            raise AssetError("asset integrity verification failed before scanning")
        return path

    def open_clean_asset(self, workspace_id, principal_id, asset_id):
        """Return a private file handle only for clean, active, workspace-owned media."""
        metadata = self.get_asset(workspace_id, principal_id, asset_id)
        if metadata["scan_status"] != "clean":
            raise AssetError("asset is quarantined until malware scanning succeeds")
        path = self._workspace_dir(workspace_id) / (asset_id + ".blob")
        if path.is_symlink() or not path.is_file():
            raise AssetNotFound("asset binary is unavailable")
        handle = path.open("rb")
        try:
            digest = hashlib.sha256()
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
            if digest.hexdigest() != metadata["sha256"]:
                raise AssetError("asset integrity verification failed")
            handle.seek(0)
            return handle
        except Exception:
            handle.close()
            raise

    def mark_scan_result(self, workspace_id, principal_id, asset_id, clean,
                         *, media_metadata=None, scanner_verified=False):
        """Record scanner/probe outcome; external callers cannot self-certify clean assets."""
        if not isinstance(clean, bool) or not isinstance(scanner_verified, bool):
            raise ValueError("clean and scanner_verified must be booleans")
        minimum_roles = {"owner", "admin", "editor"} if scanner_verified else {"owner", "admin"}
        self.workspaces.require_membership(
            workspace_id, principal_id, minimum_roles=minimum_roles
        )
        duration_ms = None
        serialized_metadata = None
        probed_at = None
        if clean and media_metadata is not None:
            if not isinstance(media_metadata, dict):
                raise ValueError("media_metadata must be an object")
            duration_ms = media_metadata.get("duration_ms")
            asset_before = self.get_asset(workspace_id, principal_id, asset_id)
            video_streams = media_metadata.get("video_streams")
            audio_streams = media_metadata.get("audio_streams")
            has_video = media_metadata.get("has_video")
            has_audio = media_metadata.get("has_audio")
            if (isinstance(duration_ms, bool) or not isinstance(duration_ms, int)
                    or not 1 <= duration_ms <= 3_600_000
                    or media_metadata.get("byte_size") != asset_before["byte_size"]
                    or not isinstance(has_video, bool) or not isinstance(has_audio, bool)
                    or not isinstance(video_streams, list) or not isinstance(audio_streams, list)
                    or has_video != bool(video_streams) or has_audio != bool(audio_streams)):
                raise ValueError("verified media metadata is invalid or does not match asset bytes")
            serialized_metadata = json.dumps(
                media_metadata, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"), allow_nan=False,
            )
            probed_at = _utcnow().isoformat()
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute("""
                UPDATE workspace_media_assets
                SET scan_status=?,duration_ms=?,media_metadata_json=?,probed_at=?
                WHERE id=? AND workspace_id=? AND status='active' AND scan_status='pending'
            """, ("clean" if clean else "rejected", duration_ms,
                  serialized_metadata, probed_at, asset_id, workspace_id))
            if cursor.rowcount != 1:
                db.rollback()
                raise AssetNotFound("pending asset not found in this workspace")
            db.commit()
        return self.get_asset(workspace_id, principal_id, asset_id)

    def resolve_clean_asset_path(self, workspace_id, principal_id, asset_id):
        """Resolve a clean, workspace-authorized asset to its verified private path.

        Intended for a trusted local render worker. Callers must still run the
        renderer in an isolated process/container with read-only source access.
        """
        metadata = self.get_asset(workspace_id, principal_id, asset_id)
        if metadata["scan_status"] != "clean":
            raise AssetError("asset is quarantined until malware scanning succeeds")
        path = self._workspace_dir(workspace_id) / (asset_id + ".blob")
        if path.is_symlink() or not path.is_file():
            raise AssetNotFound("asset binary is unavailable")
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                size += len(chunk)
                digest.update(chunk)
        if digest.hexdigest() != metadata["sha256"] or size != metadata["byte_size"]:
            raise AssetError("asset integrity verification failed")
        return path.resolve(strict=True)

    def scan_pending_asset(self, workspace_id, asset_id, scanner):
        """Run a trusted scanner and record only its explicit clean attestation.

        This is an internal service operation, not an HTTP-facing trust decision.
        Scanner errors leave the asset quarantined.
        """
        if not callable(getattr(scanner, "scan", None)):
            raise TypeError("trusted scanner with scan(path) is required")
        if not isinstance(asset_id, str) or not _ASSET_ID.fullmatch(asset_id):
            raise ValueError("invalid asset ID")
        path = self._workspace_dir(workspace_id) / (asset_id + ".blob")
        if path.is_symlink() or not path.is_file():
            raise AssetNotFound("pending asset binary is unavailable")
        with self.db() as db:
            row = db.execute("""
                SELECT owner_principal_id,byte_size,sha256,scan_status
                FROM workspace_media_assets
                WHERE id=? AND workspace_id=? AND status='active'
            """, (asset_id, workspace_id)).fetchone()
        if row is None or row["scan_status"] != "pending":
            raise AssetNotFound("pending asset not found in this workspace")
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                size += len(chunk)
                digest.update(chunk)
        if size != row["byte_size"] or digest.hexdigest() != row["sha256"]:
            raise AssetError("asset integrity verification failed before malware scan")
        attestation = scanner.scan(path)
        if not isinstance(attestation, dict) or attestation.get("status") != "clean":
            raise AssetError("trusted scanner did not attest that the asset is clean")
        engine = attestation.get("engine")
        if not isinstance(engine, str) or not engine or len(engine) > 64:
            raise AssetError("trusted scanner identity is invalid")
        now = _utcnow().isoformat()
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute("""
                UPDATE workspace_media_assets SET scan_status='clean'
                WHERE id=? AND workspace_id=? AND status='active' AND scan_status='pending'
            """, (asset_id, workspace_id))
            if cursor.rowcount != 1:
                db.rollback()
                raise AssetConflict("asset scan state changed before scanner result was recorded")
            db.execute("""
                INSERT INTO workspace_audit_events
                (workspace_id,actor_principal_id,subject_principal_id,event_type,details,created_at)
                VALUES(?,?,?,?,?,?)
            """, (workspace_id, "system:" + engine, row["owner_principal_id"],
                  "asset.scan_clean", json.dumps({"asset_id": asset_id, "engine": engine},
                                                 sort_keys=True), now))
            db.commit()
        with self.db() as db:
            clean_row = db.execute("""
                SELECT id,workspace_id,owner_principal_id,original_name,byte_size,
                       sha256,scan_status,status,created_at,retention_until
                FROM workspace_media_assets WHERE id=? AND workspace_id=?
            """, (asset_id, workspace_id)).fetchone()
        return dict(clean_row)
