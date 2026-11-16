"""Fail-closed integrity checks for human-approved production artifacts."""
import json
import hashlib
import os
import stat
import tempfile
from pathlib import Path


def approval_snapshot_matches_current_artifacts(connection, job_id, snapshot):
    """Return (matches, reason) for the exact ordered artifact set approved by a human.

    The comparison includes stage, artifact type, URL, and parsed metadata. Added,
    removed, reordered, malformed, or modified artifacts invalidate the approval.
    """
    try:
        approved = json.loads(snapshot) if isinstance(snapshot, str) else snapshot
        if not isinstance(approved, list) or not approved:
            return False, "Approval artifact snapshot is missing or invalid"
        rows = connection.execute(
            """SELECT stage,artifact_type,artifact_url,metadata_json
               FROM production_artifacts WHERE job_id=? ORDER BY created_at,id""",
            (job_id,),
        ).fetchall()
        current = []
        for row in rows:
            metadata = json.loads(row["metadata_json"])
            current.append({
                "stage": row["stage"],
                "artifact_type": row["artifact_type"],
                "artifact_url": row["artifact_url"],
                "metadata": metadata,
            })
        if not current:
            return False, "Current production artifacts are missing"
        canonical = lambda value: json.dumps(
            value, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        )
        if canonical(approved) != canonical(current):
            return False, "Production artifacts changed after human approval; return to review"
        return True, None
    except (TypeError, ValueError, KeyError, json.JSONDecodeError):
        return False, "Approval or current artifact snapshot is malformed"


def create_verified_media_snapshot(media_path, approved_sha256, approved_size_bytes):
    """Copy exact approved bytes to a private immutable snapshot using a no-follow fd."""
    if not isinstance(approved_sha256, str) or len(approved_sha256) != 64:
        raise ValueError("Approved media SHA-256 is missing or invalid")
    try:
        int(approved_sha256, 16)
    except ValueError as exc:
        raise ValueError("Approved media SHA-256 is malformed") from exc
    if (isinstance(approved_size_bytes, bool) or
            not isinstance(approved_size_bytes, int) or approved_size_bytes <= 0):
        raise ValueError("Approved media size is missing or invalid")
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
                        raise ValueError("Staged media changed after human approval")
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
