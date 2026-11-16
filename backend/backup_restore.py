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
MAX_ARCHIVE_MEMBERS = 100_000
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_DATABASE_BYTES = 8 * 1024 * 1024 * 1024
MAX_MEDIA_BYTES = 200 * 1024 * 1024 * 1024
MAX_ARCHIVE_BYTES = MAX_MANIFEST_BYTES + MAX_DATABASE_BYTES + MAX_MEDIA_BYTES


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
        if len(inventory) > MAX_ARCHIVE_MEMBERS - 2:
            raise BackupRestoreError("Media backup contains too many files")
        media_bytes = sum(item["size"] for item in inventory)
        if media_bytes > MAX_MEDIA_BYTES:
            raise BackupRestoreError("Media backup exceeds the supported size")
        if db_snapshot.stat().st_size > MAX_DATABASE_BYTES:
            raise BackupRestoreError("SQLite backup exceeds the supported size")
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
    if not isinstance(name, str) or not name or "\\" in name or "\x00" in name:
        raise BackupRestoreError("Archive contains an invalid path")
    pure = PurePosixPath(name)
    if pure.is_absolute() or ".." in pure.parts or "." in pure.parts or not pure.parts:
        raise BackupRestoreError("Archive contains an unsafe path")
    if pure.parts[0] not in {MANIFEST_NAME, DATABASE_NAME, MEDIA_ROOT}:
        raise BackupRestoreError("Archive contains an unexpected path")
    if pure.parts[0] in {MANIFEST_NAME, DATABASE_NAME} and len(pure.parts) != 1:
        raise BackupRestoreError("Archive contains a nested control-file path")
    return pure


def _validate_manifest(manifest):
    if not isinstance(manifest, dict):
        raise BackupRestoreError("Backup manifest must be a JSON object")
    if manifest.get("format_version") != FORMAT_VERSION:
        raise BackupRestoreError("Unsupported backup format version")
    database_hash = manifest.get("database_sha256")
    if not isinstance(database_hash, str) or len(database_hash) != 64 or any(
        character not in "0123456789abcdef" for character in database_hash.lower()
    ):
        raise BackupRestoreError("Backup manifest database checksum is invalid")
    entries = manifest.get("media_files")
    if not isinstance(entries, list):
        raise BackupRestoreError("Backup manifest media_files must be a list")
    if len(entries) > MAX_ARCHIVE_MEMBERS:
        raise BackupRestoreError("Backup manifest contains too many media files")
    seen = set()
    total_size = 0
    for item in entries:
        if not isinstance(item, dict):
            raise BackupRestoreError("Backup manifest contains an invalid media entry")
        relative = item.get("path")
        size = item.get("size")
        digest = item.get("sha256")
        if not isinstance(relative, str) or len(relative) > 1024:
            raise BackupRestoreError("Backup manifest contains an invalid media path")
        pure = _validate_member_name(MEDIA_ROOT + "/" + relative)
        if len(pure.parts) < 2:
            raise BackupRestoreError("Backup manifest contains an empty media path")
        normalized = PurePosixPath(*pure.parts[1:]).as_posix()
        if normalized in seen:
            raise BackupRestoreError("Backup manifest contains duplicate media paths")
        seen.add(normalized)
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise BackupRestoreError("Backup manifest contains an invalid media size")
        if not isinstance(digest, str) or len(digest) != 64 or any(
            character not in "0123456789abcdef" for character in digest.lower()
        ):
            raise BackupRestoreError("Backup manifest contains an invalid media checksum")
        total_size += size
        if total_size > MAX_MEDIA_BYTES:
            raise BackupRestoreError("Backup media exceeds the supported restore size")
    return entries, total_size


def _extract_and_verify(archive_path, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    try:
        archive = tarfile.open(archive_path, "r:gz")
    except (tarfile.TarError, OSError) as exc:
        raise BackupRestoreError("Backup archive cannot be opened") from exc
    with archive:
        members = archive.getmembers()
        if len(members) > MAX_ARCHIVE_MEMBERS:
            raise BackupRestoreError("Backup archive contains too many entries")
        file_members = {}
        directory_names = set()
        total_size = 0
        for member in members:
            pure = _validate_member_name(member.name)
            if member.issym() or member.islnk() or member.isdev() or member.isfifo():
                raise BackupRestoreError("Archive contains a link or special file")
            if not (member.isfile() or member.isdir()):
                raise BackupRestoreError("Archive contains an unsupported member")
            if member.name in file_members or member.name.rstrip("/") in directory_names:
                raise BackupRestoreError("Backup archive contains duplicate paths")
            if member.isfile():
                if member.size < 0:
                    raise BackupRestoreError("Backup archive contains an invalid file size")
                if member.name == MANIFEST_NAME and member.size > MAX_MANIFEST_BYTES:
                    raise BackupRestoreError("Backup manifest exceeds the supported size")
                if member.name == DATABASE_NAME and member.size > MAX_DATABASE_BYTES:
                    raise BackupRestoreError("Backup database exceeds the supported size")
                total_size += member.size
                if total_size > MAX_ARCHIVE_BYTES:
                    raise BackupRestoreError("Backup archive exceeds the supported uncompressed size")
                file_members[member.name] = member
            else:
                if pure.parts[0] != MEDIA_ROOT:
                    raise BackupRestoreError("Backup archive contains an unexpected directory")
                directory_names.add(member.name.rstrip("/"))

        if MANIFEST_NAME not in file_members or DATABASE_NAME not in file_members:
            raise BackupRestoreError("Backup archive is missing its manifest or database")
        manifest_stream = archive.extractfile(file_members[MANIFEST_NAME])
        try:
            manifest = json.loads(manifest_stream.read(MAX_MANIFEST_BYTES + 1).decode("utf-8"))
        except (AttributeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BackupRestoreError("Backup manifest is not valid UTF-8 JSON") from exc
        entries, manifest_media_size = _validate_manifest(manifest)
        if manifest_media_size > MAX_MEDIA_BYTES:
            raise BackupRestoreError("Backup media exceeds the supported restore size")
        if file_members[DATABASE_NAME].size > MAX_DATABASE_BYTES:
            raise BackupRestoreError("Backup database exceeds the supported restore size")
        expected_media = {MEDIA_ROOT + "/" + str(item["path"]) for item in entries}
        expected_files = {MANIFEST_NAME, DATABASE_NAME} | expected_media
        if set(file_members) != expected_files:
            raise BackupRestoreError("Backup archive contents do not match the manifest")
        expected_directories = {MEDIA_ROOT}
        for name in expected_media:
            parts = PurePosixPath(name).parts
            for index in range(1, len(parts)):
                expected_directories.add("/".join(parts[:index]))
        if not expected_directories.issubset(directory_names):
            raise BackupRestoreError("Backup archive is missing required media directories")
        for name in sorted(directory_names, key=lambda value: (value.count("/"), value)):
            target = destination.joinpath(*PurePosixPath(name).parts)
            target.mkdir(parents=True, exist_ok=True)

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
    if _sha256(database) != manifest.get("database_sha256", "").lower():
        raise BackupRestoreError("Backup database checksum mismatch")
    with sqlite3.connect(str(database), timeout=30) as connection:
        result = connection.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise BackupRestoreError("Backup database failed integrity_check")
    for item in entries:
        relative = PurePosixPath(item["path"])
        path = destination / MEDIA_ROOT / Path(*relative.parts)
        if not path.is_file() or path.stat().st_size != item["size"]:
            raise BackupRestoreError("Backup media file is missing or has the wrong size")
        if _sha256(path) != item["sha256"].lower():
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
