"""Approval-to-artifact integrity checks shared by platform publishers."""
import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path


def approval_snapshot_matches_current_artifacts(connection, job_id, snapshot_json):
    """Return (matches, reason) for the exact artifact set reviewed by a human.

    The comparison covers stage, type, URL and parsed metadata, including ordering.
    A missing, malformed, added, removed or modified artifact invalidates approval.
    """
    try:
        approved = json.loads(snapshot_json) if isinstance(snapshot_json, str) else snapshot_json
        if not isinstance(approved, list) or not approved:
            return False, "Approval artifact snapshot is missing or invalid"
        current_rows = connection.execute(
            """SELECT stage,artifact_type,artifact_url,metadata_json
               FROM production_artifacts WHERE job_id=? ORDER BY created_at,id""",
            (job_id,),
        ).fetchall()
        current = []
        for row in current_rows:
            metadata = json.loads(row["metadata_json"])
            if not isinstance(metadata, (dict, list, str, int, float, bool)) and metadata is not None:
                return False, "Current artifact metadata is invalid"
            current.append({
                "stage": row["stage"],
                "artifact_type": row["artifact_type"],
                "artifact_url": row["artifact_url"],
                "metadata": metadata,
            })
        if not current:
            return False, "Current production artifacts are missing"
        canonical = lambda value: json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        if canonical(approved) != canonical(current):
            return False, "Production artifacts changed after human approval; return to review"
        return True, None
    except (TypeError, ValueError, KeyError, json.JSONDecodeError):
        return False, "Approval or current artifact snapshot is malformed"



def verify_staged_media_hash(media_path, approved_sha256, approved_size_bytes):
    """Verify staged bytes exactly match the media fingerprint captured at approval."""
    try:
        if not isinstance(approved_sha256, str) or len(approved_sha256) != 64:
            return False, "Approved staged-media SHA-256 is missing or invalid"
        int(approved_sha256, 16)
        if isinstance(approved_size_bytes, bool) or not isinstance(approved_size_bytes, int) or approved_size_bytes <= 0:
            return False, "Approved staged-media size is missing or invalid"
        candidate = Path(media_path)
        if candidate.is_symlink():
            return False, "Staged media cannot be a symbolic link"
        if not candidate.is_file():
            return False, "Approved staged media file is missing"
        digest = hashlib.sha256()
        total = 0
        with candidate.open("rb") as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                digest.update(chunk)
        if total != approved_size_bytes or digest.hexdigest() != approved_sha256:
            return False, "Staged media bytes changed after human approval; return to review"
        return True, None
    except (OSError, TypeError, ValueError):
        return False, "Staged media could not be verified against the approval fingerprint"



def create_verified_media_snapshot(media_path, approved_sha256, approved_size_bytes):
    """Copy approved bytes through a no-follow file descriptor into a private upload snapshot.

    The returned temporary file is detached from the mutable staging pathname.
    Callers must unlink it in a finally block after the remote upload attempt.
    """
    if not isinstance(approved_sha256, str) or len(approved_sha256) != 64:
        raise ValueError("Approved staged-media SHA-256 is missing or invalid")
    try:
        int(approved_sha256, 16)
    except ValueError as exc:
        raise ValueError("Approved staged-media SHA-256 is malformed") from exc
    if (isinstance(approved_size_bytes, bool)
            or not isinstance(approved_size_bytes, int) or approved_size_bytes <= 0):
        raise ValueError("Approved staged-media size is missing or invalid")

    source = Path(media_path)
    snapshot_path = None
    fd = None
    try:
        if source.is_symlink():
            raise ValueError("Staged media cannot be a symbolic link")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(str(source), flags)
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            raise ValueError("Staged media must be a regular file")
        current = os.stat(str(source), follow_symlinks=False)
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise ValueError("Staged media path changed while opening the approved file")
        digest = hashlib.sha256()
        total = 0
        with tempfile.NamedTemporaryFile(prefix="nexus-approved-", suffix=source.suffix,
                                         delete=False) as snapshot:
            snapshot_path = snapshot.name
            with os.fdopen(fd, "rb", closefd=True) as stream:
                fd = None
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > approved_size_bytes:
                        raise ValueError("Staged media bytes changed after human approval")
                    digest.update(chunk)
                    snapshot.write(chunk)
            snapshot.flush()
            os.fsync(snapshot.fileno())
        if total != approved_size_bytes or digest.hexdigest() != approved_sha256:
            raise ValueError("Staged media bytes changed after human approval; return to review")
        os.chmod(snapshot_path, 0o400)
        return snapshot_path, total
    except Exception:
        if snapshot_path:
            try:
                os.unlink(snapshot_path)
            except OSError:
                pass
        raise
    finally:
        if fd is not None:
            os.close(fd)
