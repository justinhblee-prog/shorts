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


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        return 2
    if args[0] == "process" and len(args) == 2:
        return 0 if process_matches(args[1]) else 1
    if args[0] == "backup" and len(args) == 2:
        maximum_age = os.getenv("NEXUS_BACKUP_HEALTH_MAX_AGE_SECONDS", "172800")
        return 0 if backup_marker_is_fresh(args[1], maximum_age) else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
