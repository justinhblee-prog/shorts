"""Small Docker health probes for long-running NEXUS services."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path


def process_matches(expected: str, cmdline: bytes | None = None) -> bool:
    if not isinstance(expected, str) or not expected or "/" in expected or "\\" in expected:
        return False
    if cmdline is None:
        try:
            cmdline = Path("/proc/1/cmdline").read_bytes()
        except OSError:
            return False
    return expected.encode("ascii", "strict") in cmdline.split(b"\0")


def backup_marker_is_fresh(
    marker: str | Path,
    max_age_seconds: int,
    *,
    now: float | None = None,
) -> bool:
    try:
        max_age = int(max_age_seconds)
        if max_age <= 0:
            return False
        path = Path(marker)
        if not path.is_file() or path.is_symlink():
            return False
        modified = path.stat().st_mtime
        current = time.time() if now is None else float(now)
        age = current - modified
        return -60 <= age <= max_age
    except (OSError, TypeError, ValueError):
        return False


def backup_archive_is_fresh(
    directory: str | Path,
    max_age_seconds: int,
    *,
    now: float | None = None,
    encryption_required: bool = False,
) -> bool:
    """Require a retained backup archive as well as a fresh success marker."""
    try:
        if isinstance(max_age_seconds, bool):
            return False
        max_age = int(max_age_seconds)
        if max_age <= 0:
            return False
        root = Path(directory)
        if root.is_symlink() or not root.is_dir():
            return False
        current = time.time() if now is None else float(now)
        suffixes = (".tar.gz.enc",) if encryption_required else (".tar.gz.enc", ".tar.gz")
        for archive in root.glob("nexus-backup-*"):
            if archive.is_symlink() or not archive.is_file():
                continue
            if not archive.name.endswith(suffixes):
                continue
            if archive.name.endswith(".tar.gz.enc"):
                with archive.open("rb") as stream:
                    if stream.read(8) != b"NEXUSBK1":
                        continue
            elif archive.name.endswith(".tar.gz"):
                with archive.open("rb") as stream:
                    if stream.read(2) != b"\x1f\x8b":
                        continue
            age = current - archive.stat().st_mtime
            if -60 <= age <= max_age:
                return True
        return False
    except (OSError, TypeError, ValueError):
        return False


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        return 2
    if args[0] == "process" and len(args) == 2:
        return 0 if process_matches(args[1]) else 1
    if args[0] == "backup" and len(args) == 2:
        maximum_age = os.getenv("NEXUS_BACKUP_HEALTH_MAX_AGE_SECONDS", "172800")
        encryption_required = os.getenv("NEXUS_BACKUP_ENCRYPTION_REQUIRED", "false").strip().lower() in {
            "1", "true", "yes", "on"
        }
        marker = Path(args[1])
        healthy = (
            backup_marker_is_fresh(marker, maximum_age)
            and backup_archive_is_fresh(
                marker.parent, maximum_age, encryption_required=encryption_required
            )
        )
        return 0 if healthy else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
