"""Workspace-owned source asset registration for the NEXUS timeline renderer.

Assets are stored under opaque workspace namespaces. Public EDL payloads carry only
asset IDs; paths are resolved here after the API authenticates workspace membership.
"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from media_scanner import ClamAVScanner


class RenderAssetError(RuntimeError):
    pass


class RenderAssetNotFound(RenderAssetError):
    pass


_WORKSPACE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_OWNER_ID = re.compile(r"^[^\x00-\x1f\x7f]{1,128}$")
_ALLOWED_TYPES = {"video/mp4": ("video", ".mp4"), "audio/mp4": ("audio", ".m4a")}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _clean_name(value):
    if not isinstance(value, str):
        return "uploaded-media"
    name = value.replace("\\", "/").split("/")[-1].strip()
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name)[:128].strip(" .")
    if not name or name in {".", ".."}:
        return "uploaded-media"
    return name


class RenderAssetStore:
    def __init__(
        self,
        db_path=None,
        media_dir=None,
        scanner=None,
        scan_enabled=None,
        max_video_bytes=None,
        max_audio_bytes=None,
    ):
        self.db_path = str(db_path or os.getenv("NEXUS_DB_PATH", "data/nexus.sqlite3"))
        self.media_root = Path(
            media_dir or os.getenv("NEXUS_MEDIA_DIR", "data/media")
        ).resolve()
        self.max_video_bytes = int(
            max_video_bytes or os.getenv("NEXUS_RENDER_MAX_VIDEO_ASSET_BYTES", str(512 * 1024 * 1024))
        )
        self.max_audio_bytes = int(
            max_audio_bytes or os.getenv("NEXUS_RENDER_MAX_AUDIO_ASSET_BYTES", str(128 * 1024 * 1024))
        )
        if not (12 <= self.max_video_bytes <= 2 * 1024 * 1024 * 1024):
            raise ValueError("video asset limit must be between 12 bytes and 2 GiB")
        if not (12 <= self.max_audio_bytes <= 2 * 1024 * 1024 * 1024):
            raise ValueError("audio asset limit must be between 12 bytes and 2 GiB")
        if scan_enabled is None:
            raw = os.getenv("NEXUS_MEDIA_SCAN_ENABLED", "false").strip().lower()
            scan_enabled = raw in {"1", "true", "yes", "on"} or raw not in {"0", "false", "no", "off", ""}
        elif isinstance(scan_enabled, str):
            raw = scan_enabled.strip().lower()
            scan_enabled = raw in {"1", "true", "yes", "on"} or raw not in {"0", "false", "no", "off", ""}
        self.scan_enabled = bool(scan_enabled)
        self.scanner = scanner
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS render_assets(
                    asset_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    asset_type TEXT NOT NULL CHECK(asset_type IN ('video','audio')),
                    content_type TEXT NOT NULL,
                    original_name TEXT NOT NULL,
                    relative_path TEXT NOT NULL UNIQUE,
                    size_bytes INTEGER NOT NULL CHECK(size_bytes > 0),
                    sha256 TEXT NOT NULL,
                    scan_status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    deleted_at TEXT
                )
            """)
            connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_render_assets_workspace_created
                ON render_assets(workspace_id, deleted_at, created_at)
            """)

    def db(self):
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        return _DatabaseContext(connection)

    @staticmethod
    def _validate_scope(workspace_id, owner_id):
        if not isinstance(workspace_id, str) or not _WORKSPACE_ID.fullmatch(workspace_id):
            raise RenderAssetError("An explicit valid workspace is required for render assets")
        if not isinstance(owner_id, str) or not _OWNER_ID.fullmatch(owner_id.strip()):
            raise RenderAssetError("Authenticated asset owner is invalid")

    def _asset_directory(self, workspace_id):
        namespace = hashlib.sha256(workspace_id.encode("utf-8")).hexdigest()
        workspace_dir = self.media_root / namespace
        directory = workspace_dir / "render-assets"
        if workspace_dir.is_symlink() or directory.is_symlink():
            raise RenderAssetError("Workspace render asset directory must not be a symlink")
        try:
            self.media_root.mkdir(parents=True, exist_ok=True)
            resolved = directory.resolve(strict=False)
            resolved.relative_to(self.media_root)
            resolved.mkdir(parents=True, exist_ok=True)
            if directory.is_symlink() or resolved.is_symlink():
                raise RenderAssetError("Workspace render asset directory must not be a symlink")
            resolved = resolved.resolve(strict=True)
            resolved.relative_to(self.media_root)
        except RenderAssetError:
            raise
        except (OSError, ValueError) as exc:
            raise RenderAssetError("Workspace render asset directory escaped media storage") from exc
        return resolved

    async def register_stream(
        self, workspace_id, owner_id, content_type, original_name, chunks, declared_length=None
    ):
        """Stream an upload to quarantine, hash and scan it, then atomically register it."""
        self._validate_scope(workspace_id, owner_id)
        media_type = (content_type or "").split(";", 1)[0].strip().lower()
        definition = _ALLOWED_TYPES.get(media_type)
        if definition is None:
            raise RenderAssetError("Only MP4 video and M4A/MP4 audio assets are accepted")
        asset_type, extension = definition
        max_bytes = self.max_video_bytes if asset_type == "video" else self.max_audio_bytes
        if declared_length is not None:
            try:
                declared_length = int(declared_length)
            except (TypeError, ValueError) as exc:
                raise RenderAssetError("Upload Content-Length is invalid") from exc
            if declared_length < 1 or declared_length > max_bytes:
                raise RenderAssetError("Upload exceeds the configured asset size limit")

        directory = self._asset_directory(workspace_id)
        temporary_path = None
        destination = None
        total = 0
        prefix = b""
        digest = hashlib.sha256()
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=directory, prefix=".nexus-render-asset-", suffix=".part", delete=False
            ) as output:
                temporary_path = Path(output.name)
                async for chunk in chunks:
                    if not isinstance(chunk, (bytes, bytearray)):
                        raise RenderAssetError("Upload stream returned non-binary data")
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > max_bytes:
                        raise RenderAssetError("Upload exceeds the configured asset size limit")
                    if len(prefix) < 12:
                        prefix += bytes(chunk[:12 - len(prefix)])
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())

            if total < 12 or prefix[4:8] != b"ftyp":
                raise RenderAssetError("Uploaded asset does not contain an MP4-family signature")
            if declared_length is not None and declared_length != total:
                raise RenderAssetError("Upload byte count does not match Content-Length")

            scan_status = "disabled"
            if self.scan_enabled:
                try:
                    scanner = self.scanner or ClamAVScanner(max_bytes=max_bytes)
                    scan = scanner.scan(temporary_path)
                except Exception as exc:
                    raise RenderAssetError("Malware scanner could not confirm a clean asset") from exc
                if not isinstance(scan, dict) or scan.get("status") != "clean":
                    raise RenderAssetError("Malware scanner did not explicitly confirm a clean asset")
                scan_status = "clean"

            asset_id = uuid.uuid4().hex
            destination = directory / (asset_id + extension)
            os.replace(temporary_path, destination)
            temporary_path = None
            if os.name == "posix":
                directory_fd = os.open(directory, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            relative_path = destination.relative_to(self.media_root).as_posix()
            created_at = _now()
            with self.db() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("""
                    INSERT INTO render_assets(
                        asset_id,workspace_id,owner_id,asset_type,content_type,
                        original_name,relative_path,size_bytes,sha256,scan_status,created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    asset_id, workspace_id, owner_id.strip(), asset_type, media_type,
                    _clean_name(original_name), relative_path, total, digest.hexdigest(),
                    scan_status, created_at,
                ))
            return {
                "asset_id": asset_id,
                "asset_type": asset_type,
                "content_type": media_type,
                "original_name": _clean_name(original_name),
                "size_bytes": total,
                "sha256": digest.hexdigest(),
                "scan_status": scan_status,
                "render_ready": scan_status == "clean",
                "created_at": created_at,
            }
        except Exception:
            if destination is not None:
                destination.unlink(missing_ok=True)
            raise
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def workspace_render_output_dir(self, workspace_id):
        if not isinstance(workspace_id, str) or not _WORKSPACE_ID.fullmatch(workspace_id):
            raise RenderAssetError("An explicit valid workspace is required for render output")
        asset_directory = self._asset_directory(workspace_id)
        directory = asset_directory.parent / "render-outputs"
        if directory.is_symlink():
            raise RenderAssetError("Workspace render output directory must not be a symlink")
        try:
            resolved = directory.resolve(strict=False)
            resolved.relative_to(self.media_root)
            resolved.mkdir(parents=True, exist_ok=True)
            if directory.is_symlink():
                raise RenderAssetError("Workspace render output directory must not be a symlink")
            resolved = resolved.resolve(strict=True)
            resolved.relative_to(self.media_root)
            return resolved
        except RenderAssetError:
            raise
        except (OSError, ValueError) as exc:
            raise RenderAssetError("Workspace render output directory escaped media storage") from exc

    def list_assets(self, workspace_id, limit=100):
        if not isinstance(workspace_id, str) or not _WORKSPACE_ID.fullmatch(workspace_id):
            raise RenderAssetError("An explicit valid workspace is required for render assets")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ValueError("asset list limit must be between 1 and 200")
        with self.db() as connection:
            rows = connection.execute("""
                SELECT asset_id,asset_type,content_type,original_name,size_bytes,
                       sha256,scan_status,created_at
                FROM render_assets
                WHERE workspace_id=? AND deleted_at IS NULL
                ORDER BY created_at DESC,asset_id DESC LIMIT ?
            """, (workspace_id, limit)).fetchall()
        return [dict(row) for row in rows]

    def resolve_asset_paths(self, workspace_id, asset_ids, require_clean_scan=True, expected_asset_type=None):
        """Resolve IDs only inside one workspace and verify the stored bytes on every use."""
        if not isinstance(workspace_id, str) or not _WORKSPACE_ID.fullmatch(workspace_id):
            raise RenderAssetError("An explicit valid workspace is required for render assets")
        if not isinstance(asset_ids, list) or not 1 <= len(asset_ids) <= 21:
            raise RenderAssetError("One to 21 registered asset IDs are required")
        if any(not isinstance(item, str) or not re.fullmatch(r"[0-9a-f]{32}", item) for item in asset_ids):
            raise RenderAssetError("Render asset ID is invalid")
        unique_ids = list(dict.fromkeys(asset_ids))
        placeholders = ",".join("?" for _ in unique_ids)
        with self.db() as connection:
            rows = connection.execute(
                f"""SELECT asset_id,asset_type,relative_path,size_bytes,sha256,scan_status
                    FROM render_assets
                    WHERE workspace_id=? AND deleted_at IS NULL
                      AND asset_id IN ({placeholders})""",
                [workspace_id, *unique_ids],
            ).fetchall()
        by_id = {row["asset_id"]: row for row in rows}
        if len(by_id) != len(unique_ids):
            raise RenderAssetNotFound("One or more render assets do not belong to this workspace")
        resolved = {}
        for asset_id in unique_ids:
            row = by_id[asset_id]
            if require_clean_scan and row["scan_status"] != "clean":
                raise RenderAssetError("Render asset has not passed the required malware scan")
            if expected_asset_type is not None and row["asset_type"] != expected_asset_type:
                raise RenderAssetError("Render asset type does not match the EDL clip type")
            candidate = self.media_root / row["relative_path"]
            if candidate.is_symlink() or not candidate.is_file():
                raise RenderAssetError("Registered render asset is missing or is a symlink")
            try:
                path = candidate.resolve(strict=True)
                path.relative_to(self.media_root)
                namespace = hashlib.sha256(workspace_id.encode("utf-8")).hexdigest()
                workspace_asset_root = (self.media_root / namespace / "render-assets").resolve(strict=True)
                workspace_asset_root.relative_to(self.media_root)
                path.relative_to(workspace_asset_root)
            except (OSError, ValueError) as exc:
                raise RenderAssetError("Registered render asset escaped its workspace namespace") from exc
            digest = hashlib.sha256()
            size = 0
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    size += len(block)
                    digest.update(block)
            if size != row["size_bytes"] or digest.hexdigest() != row["sha256"]:
                raise RenderAssetError("Registered render asset checksum verification failed")
            resolved[asset_id] = path
        return resolved


class _DatabaseContext:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, exc_type, exc, traceback):
        try:
            if exc_type is None:
                self.connection.commit()
            else:
                self.connection.rollback()
        finally:
            self.connection.close()
        return False
