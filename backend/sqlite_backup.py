"""Safe online SQLite backup, integrity verification, and non-destructive restore tools."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote


BACKUP_PREFIX = "nexus-"
BACKUP_SUFFIX = ".sqlite3"


def _readonly_uri(path: Path) -> str:
    return "file:" + quote(str(path.resolve())) + "?mode=ro"


def _check_database(path: Path) -> dict:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"SQLite database is not a regular file: {path}")
    connection = sqlite3.connect(_readonly_uri(path), uri=True, timeout=30)
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            detail = result[0] if result else "no integrity result"
            raise sqlite3.DatabaseError(f"SQLite integrity check failed: {detail}")
        return {
            "path": str(path.resolve()),
            "integrity_check": "ok",
            "size_bytes": path.stat().st_size,
        }
    finally:
        connection.close()


def verify_database(path: str | Path) -> dict:
    """Run SQLite's full integrity check without modifying the database."""
    return _check_database(Path(path))


def _copy_snapshot(source: Path, destination: Path) -> None:
    source_connection = sqlite3.connect(_readonly_uri(source), uri=True, timeout=30)
    destination_connection = sqlite3.connect(str(destination), timeout=30)
    try:
        source_connection.backup(destination_connection)
        result = destination_connection.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            detail = result[0] if result else "no integrity result"
            raise sqlite3.DatabaseError(f"Backup integrity check failed: {detail}")
        destination_connection.commit()
    finally:
        destination_connection.close()
        source_connection.close()


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _prune_backups(directory: Path, keep: int) -> list[str]:
    candidates = [
        path for path in directory.iterdir()
        if path.name.startswith(BACKUP_PREFIX)
        and path.name.endswith(BACKUP_SUFFIX)
        and not path.is_symlink()
        and path.is_file()
    ]
    candidates.sort(key=lambda item: (item.stat().st_mtime_ns, item.name), reverse=True)
    removed = []
    for path in candidates[keep:]:
        path.unlink()
        removed.append(path.name)
    return removed


def create_backup(
    source: str | Path,
    backup_dir: str | Path,
    keep: int = 14,
) -> dict:
    """Create a consistent online backup and retain only the newest backups."""
    source = Path(source)
    backup_dir = Path(backup_dir)
    if keep < 1:
        raise ValueError("keep must be at least 1")
    _check_database(source)
    backup_dir.mkdir(parents=True, exist_ok=True)
    if backup_dir.is_symlink() or not backup_dir.is_dir():
        raise ValueError(f"Backup destination is not a real directory: {backup_dir}")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    unique = uuid.uuid4().hex[:12]
    filename = f"{BACKUP_PREFIX}{timestamp}-{unique}{BACKUP_SUFFIX}"
    target = backup_dir / filename
    temporary = backup_dir / f".{filename}.tmp"
    try:
        _copy_snapshot(source, temporary)
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
        _fsync_directory(backup_dir)
        verification = _check_database(target)
        removed = _prune_backups(backup_dir, keep)
        _fsync_directory(backup_dir)
        return {
            "backup_path": str(target.resolve()),
            "integrity_check": verification["integrity_check"],
            "size_bytes": verification["size_bytes"],
            "retained": min(keep, len(list(backup_dir.glob(BACKUP_PREFIX + "*" + BACKUP_SUFFIX)))),
            "removed": removed,
        }
    finally:
        if temporary.exists():
            temporary.unlink()


def restore_backup(backup: str | Path, target: str | Path) -> dict:
    """Restore into a new file only; never overwrite an existing database."""
    backup = Path(backup)
    target = Path(target)
    _check_database(backup)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"Restore target already exists; refusing to overwrite: {target}")

    temporary = target.parent / f".{target.name}.{uuid.uuid4().hex}.restore"
    try:
        _copy_snapshot(backup, temporary)
        os.chmod(temporary, 0o600)
        # A hard link provides atomic no-clobber semantics on the same filesystem.
        os.link(temporary, target)
        temporary.unlink()
        _fsync_directory(target.parent)
        return _check_database(target)
    finally:
        if temporary.exists():
            temporary.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    backup_parser = commands.add_parser("backup", help="create and verify an online backup")
    backup_parser.add_argument("--source", default=os.getenv("NEXUS_DB_PATH", "data/nexus.sqlite3"))
    backup_parser.add_argument("--backup-dir", default=os.getenv("NEXUS_BACKUP_DIR", "backups"))
    backup_parser.add_argument("--keep", type=int, default=14)

    verify_parser = commands.add_parser("verify", help="verify a SQLite database or backup")
    verify_parser.add_argument("--path", required=True)

    restore_parser = commands.add_parser("restore", help="restore to a new, non-existing file")
    restore_parser.add_argument("--backup", required=True)
    restore_parser.add_argument("--target", required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "backup":
            result = create_backup(args.source, args.backup_dir, args.keep)
        elif args.command == "verify":
            result = verify_database(args.path)
        else:
            result = restore_backup(args.backup, args.target)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"sqlite_backup_error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
