"""Consistent SQLite + media backup and guarded restore utilities (stdlib only)."""
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


BACKUP_PREFIX = "nexus-backup-"
MANIFEST_NAME = "manifest.json"
DATABASE_NAME = "database.sqlite3"
MEDIA_ROOT = "media"
FORMAT_VERSION = 1


class BackupRestoreError(RuntimeError):
    pass


def _now():
    return datetime.now(timezone.utc)


def _stamp():
    return _now().strftime("%Y%m%dT%H%M%S%fZ")


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sqlite_snapshot(source_path, destination_path):
    source_path = Path(source_path)
    if not source_path.is_file():
        raise BackupRestoreError("SQLite database does not exist: " + str(source_path))
    source = sqlite3.connect(str(source_path), timeout=30)
    destination = sqlite3.connect(str(destination_path), timeout=30)
    try:
        source.execute("PRAGMA busy_timeout=30000")
        source.backup(destination, pages=256, sleep=0.05)
        result = destination.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise BackupRestoreError("SQLite backup failed integrity_check")
        destination.commit()
    finally:
        destination.close()
        source.close()


def _media_inventory(media_dir):
    media_dir = Path(media_dir)
    inventory = []
    if not media_dir.exists():
        return inventory
    if not media_dir.is_dir():
        raise BackupRestoreError("Media path is not a directory")
    for path in sorted(media_dir.rglob("*")):
        if path.is_symlink():
            raise BackupRestoreError("Media backup refuses symbolic links: " + str(path))
        if path.is_file():
            relative = path.relative_to(media_dir).as_posix()
            pure = PurePosixPath(relative)
            if pure.is_absolute() or ".." in pure.parts:
                raise BackupRestoreError("Unsafe media path in backup")
            inventory.append({
                "path": relative,
                "size": path.stat().st_size,
                "sha256": _sha256(path),
            })
    return inventory


def _copy_media(source, destination):
    source = Path(source)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    if source.exists():
        _media_inventory(source)
        for item in source.rglob("*"):
            if item.is_symlink():
                raise BackupRestoreError("Media backup refuses symbolic links: " + str(item))
            relative = item.relative_to(source)
            target = destination / relative
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            elif item.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)


def _prune_backups(output_dir, retain_days):
    output_dir = Path(output_dir)
    cutoff = _now().timestamp() - max(1, int(retain_days)) * 86400
    removed = []
    for path in output_dir.glob(BACKUP_PREFIX + "*.tar.gz"):
        if path.is_file() and path.stat().st_mtime < cutoff:
            path.unlink()
            removed.append(path.name)
    return removed


def create_backup(db_path, media_dir, output_dir, retain_days=14):
    db_path = Path(db_path).resolve()
    media_dir = Path(media_dir).resolve()
    output_dir = Path(output_dir).resolve()
    if output_dir == media_dir or media_dir in output_dir.parents:
        raise BackupRestoreError("Backup output directory must be outside the media directory")
    output_dir.mkdir(parents=True, exist_ok=True)
    if not db_path.is_file():
        raise BackupRestoreError("SQLite database does not exist: " + str(db_path))

    stamp = _stamp()
    filename = f"{BACKUP_PREFIX}{stamp}.tar.gz"
    final_path = output_dir / filename
    if final_path.exists():
        raise BackupRestoreError("Backup already exists for this timestamp")
    with tempfile.TemporaryDirectory(prefix="nexus-backup-", dir=output_dir) as temp:
        stage = Path(temp)
        db_snapshot = stage / DATABASE_NAME
        media_snapshot = stage / MEDIA_ROOT
        _sqlite_snapshot(db_path, db_snapshot)
        _copy_media(media_dir, media_snapshot)
        inventory = _media_inventory(media_snapshot)
        manifest = {
            "format_version": FORMAT_VERSION,
            "created_at": _now().isoformat(),
            "database_sha256": _sha256(db_snapshot),
            "media_files": inventory,
        }
        (stage / MANIFEST_NAME).write_text(
            json.dumps(manifest, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_archive = output_dir / (filename + ".tmp")
        try:
            with tarfile.open(temporary_archive, "w:gz") as archive:
                archive.add(stage / MANIFEST_NAME, arcname=MANIFEST_NAME)
                archive.add(db_snapshot, arcname=DATABASE_NAME)
                archive.add(media_snapshot, arcname=MEDIA_ROOT)
            os.replace(temporary_archive, final_path)
        finally:
            if temporary_archive.exists():
                temporary_archive.unlink()
    removed = _prune_backups(output_dir, retain_days)
    return {
        "backup_path": str(final_path),
        "size_bytes": final_path.stat().st_size,
        "sha256": _sha256(final_path),
        "media_file_count": len(inventory),
        "pruned_backups": removed,
    }


def _validate_member_name(name):
    pure = PurePosixPath(name)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise BackupRestoreError("Archive contains an unsafe path")
    if pure.parts[0] not in {MANIFEST_NAME, DATABASE_NAME, MEDIA_ROOT}:
        raise BackupRestoreError("Archive contains an unexpected path")
    return pure


def _extract_and_verify(archive_path, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    try:
        archive = tarfile.open(archive_path, "r:gz")
    except (tarfile.TarError, OSError) as exc:
        raise BackupRestoreError("Backup archive cannot be opened") from exc
    with archive:
        members = archive.getmembers()
        file_members = {}
        for member in members:
            pure = _validate_member_name(member.name)
            if member.issym() or member.islnk() or member.isdev() or member.isfifo():
                raise BackupRestoreError("Archive contains a link or special file")
            if not (member.isfile() or member.isdir()):
                raise BackupRestoreError("Archive contains an unsupported member")
            if member.isfile():
                if member.name in file_members:
                    raise BackupRestoreError("Archive contains duplicate file paths")
                file_members[member.name] = member
        if MANIFEST_NAME not in file_members or DATABASE_NAME not in file_members:
            raise BackupRestoreError("Backup archive is missing its manifest or database")
        manifest_stream = archive.extractfile(file_members[MANIFEST_NAME])
        manifest = json.loads(manifest_stream.read().decode("utf-8"))
        if manifest.get("format_version") != FORMAT_VERSION:
            raise BackupRestoreError("Unsupported backup format version")
        expected_media = {
            MEDIA_ROOT + "/" + str(item.get("path"))
            for item in manifest.get("media_files", [])
        }
        expected_files = {MANIFEST_NAME, DATABASE_NAME} | expected_media
        if set(file_members) != expected_files:
            raise BackupRestoreError("Backup archive contents do not match the manifest")
        for name, member in file_members.items():
            pure = _validate_member_name(name)
            target = destination.joinpath(*pure.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            stream = archive.extractfile(member)
            if stream is None:
                raise BackupRestoreError("Archive file cannot be read")
            with stream, open(target, "wb") as output:
                shutil.copyfileobj(stream, output)
    database = destination / DATABASE_NAME
    if _sha256(database) != manifest.get("database_sha256"):
        raise BackupRestoreError("Backup database checksum mismatch")
    with sqlite3.connect(str(database), timeout=30) as connection:
        result = connection.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise BackupRestoreError("Backup database failed integrity_check")
    for item in manifest.get("media_files", []):
        relative = PurePosixPath(str(item.get("path", "")))
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise BackupRestoreError("Manifest contains an unsafe media path")
        path = destination / MEDIA_ROOT / Path(*relative.parts)
        if not path.is_file() or path.stat().st_size != item.get("size"):
            raise BackupRestoreError("Backup media file is missing or has the wrong size")
        if _sha256(path) != item.get("sha256"):
            raise BackupRestoreError("Backup media checksum mismatch")
    return manifest


def restore_backup(archive_path, db_path, media_dir, backup_dir,
                   confirm_restore=False, retain_days=14):
    if confirm_restore is not True:
        raise BackupRestoreError("Restore requires explicit --confirm-restore")
    db_path = Path(db_path).resolve()
    media_dir = Path(media_dir).resolve()
    backup_dir = Path(backup_dir).resolve()
    if not db_path.parent.exists():
        db_path.parent.mkdir(parents=True, exist_ok=True)
    media_dir.parent.mkdir(parents=True, exist_ok=True)
    if not Path(archive_path).is_file():
        raise BackupRestoreError("Backup archive does not exist")
    if not db_path.is_file():
        raise BackupRestoreError("Current database must exist for pre-restore backup")

    with tempfile.TemporaryDirectory(prefix="nexus-restore-", dir=db_path.parent) as temp:
        stage = Path(temp)
        manifest = _extract_and_verify(archive_path, stage)
        staged_db = stage / DATABASE_NAME
        staged_media = stage / MEDIA_ROOT
        new_db = db_path.parent / (db_path.name + ".restore-" + _stamp())
        new_media = media_dir.parent / (media_dir.name + ".restore-" + _stamp())
        old_db = db_path.parent / (db_path.name + ".pre-restore-" + _stamp())
        old_media = media_dir.parent / (media_dir.name + ".pre-restore-" + _stamp())
        shutil.copy2(staged_db, new_db)
        _copy_media(staged_media, new_media)

        pre_restore = create_backup(
            db_path, media_dir, backup_dir, retain_days=retain_days
        )["backup_path"]
        moved_old_db = False
        moved_old_media = False
        installed_db = False
        installed_media = False
        try:
            os.replace(db_path, old_db)
            moved_old_db = True
            if media_dir.exists():
                os.replace(media_dir, old_media)
                moved_old_media = True
            os.replace(new_db, db_path)
            installed_db = True
            os.replace(new_media, media_dir)
            installed_media = True
            with sqlite3.connect(str(db_path), timeout=30) as connection:
                result = connection.execute("PRAGMA integrity_check").fetchone()
                if not result or result[0] != "ok":
                    raise BackupRestoreError("Restored database failed integrity_check")
        except Exception:
            if installed_media and media_dir.exists():
                shutil.rmtree(media_dir)
            if moved_old_media and old_media.exists():
                os.replace(old_media, media_dir)
            if installed_db and db_path.exists():
                db_path.unlink()
            if moved_old_db and old_db.exists():
                os.replace(old_db, db_path)
            raise
        else:
            if old_db.exists():
                try:
                    old_db.unlink()
                except OSError:
                    pass
            if old_media.exists():
                try:
                    shutil.rmtree(old_media)
                except OSError:
                    pass
        finally:
            if new_db.exists():
                new_db.unlink()
            if new_media.exists():
                shutil.rmtree(new_media)
    return {
        "restored": True,
        "database": str(db_path),
        "media_directory": str(media_dir),
        "pre_restore_backup": pre_restore,
        "backup_created_at": manifest.get("created_at"),
        "media_file_count": len(manifest.get("media_files", [])),
    }


def main():
    parser = argparse.ArgumentParser(description="NEXUS Studio SQLite and media backup/restore")
    sub = parser.add_subparsers(dest="command", required=True)
    backup = sub.add_parser("backup")
    backup.add_argument("--db", default=os.getenv("NEXUS_DB_PATH", "data/nexus.sqlite3"))
    backup.add_argument("--media-dir", default=os.getenv("NEXUS_MEDIA_DIR", "data/media"))
    backup.add_argument("--output", default=os.getenv("NEXUS_BACKUP_DIR", "data/backups"))
    backup.add_argument("--retain-days", type=int, default=int(os.getenv("NEXUS_BACKUP_RETENTION_DAYS", "14")))
    restore = sub.add_parser("restore")
    restore.add_argument("--archive", required=True)
    restore.add_argument("--db", default=os.getenv("NEXUS_DB_PATH", "data/nexus.sqlite3"))
    restore.add_argument("--media-dir", default=os.getenv("NEXUS_MEDIA_DIR", "data/media"))
    restore.add_argument("--output", default=os.getenv("NEXUS_BACKUP_DIR", "data/backups"))
    restore.add_argument("--retain-days", type=int, default=int(os.getenv("NEXUS_BACKUP_RETENTION_DAYS", "14")))
    restore.add_argument("--confirm-restore", action="store_true")
    args = parser.parse_args()
    if args.command == "backup":
        result = create_backup(args.db, args.media_dir, args.output, args.retain_days)
    else:
        result = restore_backup(
            args.archive, args.db, args.media_dir, args.output,
            confirm_restore=args.confirm_restore, retain_days=args.retain_days,
        )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except BackupRestoreError as exc:
        raise SystemExit("backup_restore_error: " + str(exc))
