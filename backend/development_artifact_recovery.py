"""Restore validated source snapshots after a failed Draft-PR publication attempt."""
import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path


class DevelopmentArtifactError(RuntimeError):
    """A persisted source snapshot cannot be safely restored."""


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _safe_relative(value):
    if not isinstance(value, str) or not value.strip():
        raise DevelopmentArtifactError("artifact manifest contains an invalid path")
    path = value.strip()
    if path.startswith("/") or "\\" in path or any(part in ("", ".", "..") for part in path.split("/")):
        raise DevelopmentArtifactError("artifact manifest contains an unsafe path")
    return path


def restore_pending_artifacts(store, repo_root, artifact_root=None):
    """Restore only review-pending files whose checkout base still matches the saved snapshot."""
    repository = Path(repo_root).resolve()
    configured = artifact_root or os.environ.get("NEXUS_DEVELOPMENT_ARTIFACT_DIR")
    if configured:
        root = Path(configured).expanduser().resolve()
    else:
        local = os.environ.get("LOCALAPPDATA")
        base = Path(local) if local else Path.home() / ".local" / "share"
        root = (base / "NexusStudioPro" / "shorts" / "artifacts").resolve()
    try:
        root.relative_to(repository)
    except ValueError:
        pass
    else:
        raise DevelopmentArtifactError("development artifact directory must be outside the checkout")

    pending = store.list(statuses=["review_pending"], limit=500)
    restored = []
    for job in pending:
        artifact = Path(job.get("artifact_path") or "").expanduser().resolve()
        try:
            artifact.relative_to(root)
        except ValueError as error:
            raise DevelopmentArtifactError("pending artifact path is outside the persistent artifact directory") from error
        if artifact.is_symlink() or not artifact.is_file():
            raise DevelopmentArtifactError("pending source artifact is missing; refusing to rerun or complete the job")
        if _sha256(artifact.read_bytes()) != job.get("artifact_sha256"):
            raise DevelopmentArtifactError("pending source artifact SHA-256 mismatch")

        with zipfile.ZipFile(artifact, "r") as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or "manifest.json" not in names:
                raise DevelopmentArtifactError("pending source artifact has a malformed archive manifest")
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            if manifest.get("version") != 1 or manifest.get("job_id") != job.get("id"):
                raise DevelopmentArtifactError("pending source artifact identity/version mismatch")
            entries = manifest.get("files")
            if not isinstance(entries, list) or not entries:
                raise DevelopmentArtifactError("pending source artifact contains no files")
            manifest_paths = [_safe_relative(item.get("path")) for item in entries]
            if sorted(manifest_paths) != sorted(job.get("changed_files") or []):
                raise DevelopmentArtifactError("pending source artifact file list does not match the job record")
            expected_names = {"manifest.json"} | {"files/" + path for path in manifest_paths}
            if set(names) != expected_names:
                raise DevelopmentArtifactError("pending source artifact contains unexpected entries")

            staged = []
            for entry in entries:
                relative = _safe_relative(entry.get("path"))
                if not any(
                    relative == scope.rstrip("/")
                    or (not Path(scope).suffix and relative.startswith(scope.rstrip("/") + "/"))
                    for scope in (job.get("scope") or [])
                ):
                    raise DevelopmentArtifactError("pending artifact path is outside the approved job scope")
                destination = repository / relative
                resolved = destination.resolve()
                try:
                    resolved.relative_to(repository)
                except ValueError as error:
                    raise DevelopmentArtifactError("pending artifact destination escapes the checkout") from error
                if destination.is_symlink():
                    raise DevelopmentArtifactError("refusing to overwrite a symlink in the checkout")
                data = archive.read("files/" + relative)
                if _sha256(data) != entry.get("content_sha256"):
                    raise DevelopmentArtifactError("pending artifact content digest mismatch")
                current_sha = _sha256(destination.read_bytes()) if destination.is_file() else None
                if current_sha == entry.get("content_sha256"):
                    continue
                base_sha = entry.get("base_sha256")
                if base_sha is None:
                    if destination.exists():
                        raise DevelopmentArtifactError("new-file restore conflicts with an existing checkout file")
                elif current_sha != base_sha:
                    raise DevelopmentArtifactError("base file changed since validation; refusing to overwrite it")
                staged.append((destination, data))

        temporary_files = []
        try:
            for destination, data in staged:
                destination.parent.mkdir(parents=True, exist_ok=True)
                handle = tempfile.NamedTemporaryFile(
                    mode="wb", prefix=".nexus-restore-", suffix=".tmp",
                    dir=destination.parent, delete=False,
                )
                try:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                finally:
                    handle.close()
                temporary_files.append((Path(handle.name), destination))
            for temporary, destination in temporary_files:
                os.replace(temporary, destination)
        except Exception:
            for temporary, _ in temporary_files:
                try:
                    temporary.unlink()
                except OSError:
                    pass
            raise
        restored.append(job["id"])
    return restored
