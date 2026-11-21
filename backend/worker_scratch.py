"""Lease-fenced per-job scratch directories for production workers."""
import hashlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path


class ScratchWorkspaceError(RuntimeError):
    pass


def _digest(value):
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


class WorkerScratchWorkspace:
    """Private job-scoped temp directory whose cleanup is fenced by its lease token."""

    def __init__(self, job_id, worker_id, lease_token, root=None, lease_seconds=300,
                 grace_seconds=3600, clock=None):
        self.root = Path(root or os.getenv("NEXUS_WORKER_SCRATCH_DIR", "data/worker-scratch")).absolute()
        self.job_id = str(job_id)
        self.worker_id = str(worker_id)
        self.lease_token_hash = _digest(lease_token)
        self.lease_seconds = max(30, int(lease_seconds))
        self.grace_seconds = max(300, int(grace_seconds))
        self.clock = clock or time.time
        self.path = self.root / (
            "job-" + _digest(self.job_id)[:24] + "-" +
            _digest(self.worker_id)[:12] + "-" + self.lease_token_hash[:16]
        )
        self.marker = self.path / ".nexus-lease.json"
        self._previous = None

    def _write_lease(self):
        payload = {
            "version": 1,
            "job_id_sha256": _digest(self.job_id),
            "worker_id": self.worker_id,
            "lease_token_sha256": self.lease_token_hash,
            "lease_expires_at": self.clock() + self.lease_seconds,
        }
        # mkstemp uses exclusive creation and unpredictable names. Never open a
        # predictable temp path with mode "w": a job subprocess could plant a
        # symlink there and redirect the worker's lease write outside scratch.
        fd, temporary_name = tempfile.mkstemp(
            prefix=".nexus-lease-update-", dir=str(self.path)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, self.marker)
        finally:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass

    def start(self):
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink() or not self.root.is_dir():
            raise ScratchWorkspaceError("Scratch root must be a real directory")
        self.path.mkdir(mode=0o700, parents=False, exist_ok=False)
        try:
            self._write_lease()
            self._previous = (
                os.environ.get("TMPDIR"), tempfile.tempdir,
                os.environ.get("NEXUS_MEDIA_STAGING_TEMP_DIR"),
            )
            os.environ["TMPDIR"] = str(self.path)
            os.environ["NEXUS_MEDIA_STAGING_TEMP_DIR"] = str(self.path)
            tempfile.tempdir = str(self.path)
        except Exception:
            shutil.rmtree(self.path, ignore_errors=True)
            raise
        return self

    def heartbeat(self):
        if not self._owns_directory():
            raise ScratchWorkspaceError("Scratch lease ownership could not be verified")
        self._write_lease()

    def _owns_directory(self):
        try:
            if self.path.is_symlink() or self.marker.is_symlink():
                return False
            if self.path.parent.resolve() != self.root or self.path.resolve().parent != self.root:
                return False
            data = json.loads(self.marker.read_text(encoding="utf-8"))
            return (
                data.get("version") == 1
                and data.get("job_id_sha256") == _digest(self.job_id)
                and data.get("worker_id") == self.worker_id
                and data.get("lease_token_sha256") == self.lease_token_hash
            )
        except (OSError, ValueError, TypeError):
            return False

    def close(self):
        if self._previous is not None:
            previous_tmpdir, previous_cached, previous_media_temp = self._previous
            if previous_tmpdir is None:
                os.environ.pop("TMPDIR", None)
            else:
                os.environ["TMPDIR"] = previous_tmpdir
            if previous_media_temp is None:
                os.environ.pop("NEXUS_MEDIA_STAGING_TEMP_DIR", None)
            else:
                os.environ["NEXUS_MEDIA_STAGING_TEMP_DIR"] = previous_media_temp
            tempfile.tempdir = previous_cached
            self._previous = None
        if not self._owns_directory():
            return False
        shutil.rmtree(self.path)
        return not self.path.exists()

    @classmethod
    def prune_expired(cls, root=None, grace_seconds=3600, now=None):
        """Remove only direct-child job directories with valid, expired lease metadata."""
        root_path = Path(root or os.getenv("NEXUS_WORKER_SCRATCH_DIR", "data/worker-scratch")).absolute()
        grace = max(300, int(grace_seconds))
        current = time.time() if now is None else float(now)
        removed = []
        if root_path.is_symlink() or not root_path.is_dir():
            return {"removed": [], "count": 0}
        for candidate in root_path.iterdir():
            try:
                if (candidate.is_symlink() or not candidate.is_dir()
                        or not candidate.name.startswith("job-")
                        or candidate.parent.resolve() != root_path):
                    continue
                marker = candidate / ".nexus-lease.json"
                if marker.is_symlink() or not marker.is_file():
                    continue
                data = json.loads(marker.read_text(encoding="utf-8"))
                expires = data.get("lease_expires_at")
                if (data.get("version") != 1
                        or not isinstance(expires, (int, float))
                        or isinstance(expires, bool)
                        or expires + grace > current
                        or not isinstance(data.get("job_id_sha256"), str)
                        or len(data["job_id_sha256"]) != 64
                        or not isinstance(data.get("worker_id"), str)
                        or not isinstance(data.get("lease_token_sha256"), str)
                        or len(data["lease_token_sha256"]) != 64):
                    continue
                shutil.rmtree(candidate)
                removed.append(candidate.name)
            except (OSError, ValueError, TypeError):
                continue
        return {"removed": removed, "count": len(removed)}
