"""Consistent SQLite + media backup and guarded restore utilities (stdlib only)."""
import argparse
import base64
import binascii
import hashlib
import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


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
ENCRYPTED_MAGIC = b"NEXUSBK1"
ENCRYPTED_NONCE_BYTES = 12
ENCRYPTED_TAG_BYTES = 16
ENCRYPTED_SUFFIX = ".tar.gz.enc"
CHUNK_BYTES = 1024 * 1024
_USE_ENV_KEY = object()


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


def _env_flag(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _effective_encryption_key(value):
    if value is _USE_ENV_KEY:
        value = os.getenv("NEXUS_BACKUP_ENCRYPTION_KEY", "").strip()
    return value or None


def _validate_database_media_paths(db_path, media_dir):
    db_path = Path(db_path).resolve()
    media_dir = Path(media_dir).resolve()
    if db_path == media_dir or media_dir in db_path.parents:
        raise BackupRestoreError(
            "Database path must be outside the media directory"
        )


def _encryption_key_bytes(key):
    if key is None:
        raise BackupRestoreError("NEXUS_BACKUP_ENCRYPTION_KEY is required for encrypted backup operations")
    try:
        raw = key.encode("ascii") if isinstance(key, str) else bytes(key)
        decoded = base64.b64decode(raw, altchars=b"-_", validate=True)
    except (UnicodeEncodeError, ValueError, TypeError, binascii.Error) as exc:
        raise BackupRestoreError(
            "Backup encryption key must be URL-safe base64 encoding of exactly 32 bytes"
        ) from exc
    if len(decoded) != 32:
        raise BackupRestoreError(
            "Backup encryption key must decode to exactly 32 bytes"
        )
    return decoded


def _is_encrypted_archive(path):
    path = Path(path)
    if path.name.endswith(ENCRYPTED_SUFFIX):
        return True
    try:
        with path.open("rb") as stream:
            return stream.read(len(ENCRYPTED_MAGIC)) == ENCRYPTED_MAGIC
    except OSError as exc:
        raise BackupRestoreError("Backup archive cannot be read") from exc


def _encrypt_file(source, destination, key):
    """Stream AES-256-GCM encryption and publish only after the tag is written."""
    key_bytes = _encryption_key_bytes(key)
    source = Path(source)
    destination = Path(destination)
    if source.is_symlink() or not source.is_file():
        raise BackupRestoreError("Backup encryption source must be a regular file")
    if destination.exists() or destination.is_symlink():
        raise BackupRestoreError("Encrypted backup destination already exists")
    nonce = os.urandom(ENCRYPTED_NONCE_BYTES)
    encryptor = Cipher(algorithms.AES(key_bytes), modes.GCM(nonce)).encryptor()
    created = False
    try:
        with source.open("rb") as input_file, destination.open("xb") as output_file:
            created = True
            if os.name != "nt":
                os.chmod(destination, 0o600)
            output_file.write(ENCRYPTED_MAGIC + nonce)
            while True:
                chunk = input_file.read(CHUNK_BYTES)
                if not chunk:
                    break
                output_file.write(encryptor.update(chunk))
            output_file.write(encryptor.finalize())
            output_file.write(encryptor.tag)
            output_file.flush()
            os.fsync(output_file.fileno())
    except Exception:
        if created:
            destination.unlink(missing_ok=True)
        raise


def _decrypt_file(source, destination, key):
    """Authenticate before any extracted content can be used; delete partial plaintext."""
    key_bytes = _encryption_key_bytes(key)
    source = Path(source)
    destination = Path(destination)
    if source.is_symlink() or not source.is_file():
        raise BackupRestoreError("Encrypted backup must be a regular non-symlink file")
    if destination.exists() or destination.is_symlink():
        raise BackupRestoreError("Decryption destination already exists")
    minimum_size = len(ENCRYPTED_MAGIC) + ENCRYPTED_NONCE_BYTES + ENCRYPTED_TAG_BYTES
    size = source.stat().st_size
    if size < minimum_size:
        raise BackupRestoreError("Encrypted backup is truncated")
    created = False
    try:
        with source.open("rb") as input_file:
            if input_file.read(len(ENCRYPTED_MAGIC)) != ENCRYPTED_MAGIC:
                raise BackupRestoreError("Encrypted backup format or version is invalid")
            nonce = input_file.read(ENCRYPTED_NONCE_BYTES)
            input_file.seek(-ENCRYPTED_TAG_BYTES, os.SEEK_END)
            tag = input_file.read(ENCRYPTED_TAG_BYTES)
            ciphertext_bytes = size - minimum_size
            input_file.seek(len(ENCRYPTED_MAGIC) + ENCRYPTED_NONCE_BYTES)
            decryptor = Cipher(
                algorithms.AES(key_bytes), modes.GCM(nonce, tag)
            ).decryptor()
            with destination.open("xb") as output_file:
                created = True
                if os.name != "nt":
                    os.chmod(destination, 0o600)
                remaining = ciphertext_bytes
                while remaining:
                    chunk = input_file.read(min(CHUNK_BYTES, remaining))
                    if not chunk:
                        raise BackupRestoreError("Encrypted backup ciphertext is truncated")
                    remaining -= len(chunk)
                    output_file.write(decryptor.update(chunk))
                try:
                    output_file.write(decryptor.finalize())
                except InvalidTag as exc:
                    raise BackupRestoreError(
                        "Encrypted backup authentication failed; key or data is invalid"
                    ) from exc
                output_file.flush()
                os.fsync(output_file.fileno())
    except Exception:
        if created:
            destination.unlink(missing_ok=True)
        raise


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
    for path in output_dir.iterdir():
        if (
            path.name.startswith(BACKUP_PREFIX)
            and (path.name.endswith(".tar.gz") or path.name.endswith(ENCRYPTED_SUFFIX))
            and not path.is_symlink()
            and path.is_file()
            and path.stat().st_mtime < cutoff
        ):
            path.unlink()
            removed.append(path.name)
    return removed


def create_backup(db_path, media_dir, output_dir, retain_days=14,
                  encryption_key=_USE_ENV_KEY):
    encryption_key = _effective_encryption_key(encryption_key)
    encryption_required = _env_flag("NEXUS_BACKUP_ENCRYPTION_REQUIRED", False)
    if encryption_required and encryption_key is None:
        raise BackupRestoreError(
            "NEXUS_BACKUP_ENCRYPTION_REQUIRED is enabled but NEXUS_BACKUP_ENCRYPTION_KEY is missing"
        )
    if encryption_key is not None:
        _encryption_key_bytes(encryption_key)

    db_path = Path(db_path).resolve()
    media_dir = Path(media_dir).resolve()
    output_dir = Path(output_dir).resolve()
    _validate_database_media_paths(db_path, media_dir)
    if output_dir == media_dir or media_dir in output_dir.parents:
        raise BackupRestoreError("Backup output directory must be outside the media directory")
    output_dir.mkdir(parents=True, exist_ok=True)
    if output_dir.is_symlink() or not output_dir.is_dir():
        raise BackupRestoreError("Backup output directory must be a real directory")
    if not db_path.is_file():
        raise BackupRestoreError("SQLite database does not exist: " + str(db_path))

    stamp = _stamp()
    encrypted = encryption_key is not None
    suffix = ENCRYPTED_SUFFIX if encrypted else ".tar.gz"
    filename = f"{BACKUP_PREFIX}{stamp}{suffix}"
    final_path = output_dir / filename
    if final_path.exists() or final_path.is_symlink():
        raise BackupRestoreError("Backup already exists for this timestamp")
    temporary_encrypted = output_dir / (filename + ".tmp") if encrypted else None
    with tempfile.TemporaryDirectory(prefix="nexus-backup-", dir=output_dir) as temp:
        stage = Path(temp)
        db_snapshot = stage / DATABASE_NAME
        media_snapshot = stage / MEDIA_ROOT
        _sqlite_snapshot(db_path, db_snapshot)
        _copy_media(media_dir, media_snapshot)
        inventory = _media_inventory(media_snapshot)
        media_entry_count = sum(1 for _ in media_snapshot.rglob("*"))
        if media_entry_count > MAX_ARCHIVE_MEMBERS - 2:
            raise BackupRestoreError("Media backup contains too many entries")
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
        temporary_archive = stage / "backup.tar.gz"
        try:
            with tarfile.open(temporary_archive, "w:gz") as archive:
                archive.add(stage / MANIFEST_NAME, arcname=MANIFEST_NAME)
                archive.add(db_snapshot, arcname=DATABASE_NAME)
                archive.add(media_snapshot, arcname=MEDIA_ROOT)
            if encrypted:
                _encrypt_file(temporary_archive, temporary_encrypted, encryption_key)
                os.replace(temporary_encrypted, final_path)
            else:
                if os.name != "nt":
                    os.chmod(temporary_archive, 0o600)
                os.replace(temporary_archive, final_path)
        finally:
            if temporary_encrypted and temporary_encrypted.exists():
                temporary_encrypted.unlink()
    removed = _prune_backups(output_dir, retain_days)
    return {
        "backup_path": str(final_path),
        "size_bytes": final_path.stat().st_size,
        "sha256": _sha256(final_path),
        "encrypted": encrypted,
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
                   confirm_restore=False, retain_days=14,
                   encryption_key=_USE_ENV_KEY):
    if confirm_restore is not True:
        raise BackupRestoreError("Restore requires explicit --confirm-restore")
    encryption_key = _effective_encryption_key(encryption_key)
    encryption_required = _env_flag("NEXUS_BACKUP_ENCRYPTION_REQUIRED", False)
    if encryption_required and encryption_key is None:
        raise BackupRestoreError(
            "NEXUS_BACKUP_ENCRYPTION_REQUIRED is enabled but NEXUS_BACKUP_ENCRYPTION_KEY is missing"
        )
    db_path = Path(db_path).resolve()
    media_dir = Path(media_dir).resolve()
    backup_dir = Path(backup_dir).resolve()
    archive_path = Path(archive_path).resolve()
    _validate_database_media_paths(db_path, media_dir)
    if media_dir == archive_path or media_dir in archive_path.parents:
        raise BackupRestoreError("Backup archive must be outside the media directory")
    if not db_path.parent.exists():
        db_path.parent.mkdir(parents=True, exist_ok=True)
    media_dir.parent.mkdir(parents=True, exist_ok=True)
    if archive_path.is_symlink() or not archive_path.is_file():
        raise BackupRestoreError("Backup archive does not exist or is not a regular file")
    if not db_path.is_file():
        raise BackupRestoreError("Current database must exist for pre-restore backup")
    encrypted = _is_encrypted_archive(archive_path)
    if encryption_required and not encrypted:
        raise BackupRestoreError(
            "Backup encryption is required; refusing to restore a plaintext archive"
        )

    with tempfile.TemporaryDirectory(prefix="nexus-restore-", dir=db_path.parent) as temp:
        stage = Path(temp)
        source_archive = archive_path
        if encrypted:
            decrypted_archive = stage / "backup.tar.gz"
            _decrypt_file(archive_path, decrypted_archive, encryption_key)
            source_archive = decrypted_archive
        extracted = stage / "extracted"
        manifest = _extract_and_verify(source_archive, extracted)
        staged_db = extracted / DATABASE_NAME
        staged_media = extracted / MEDIA_ROOT
        new_db = db_path.parent / (db_path.name + ".restore-" + _stamp())
        new_media = media_dir.parent / (media_dir.name + ".restore-" + _stamp())
        old_db = db_path.parent / (db_path.name + ".pre-restore-" + _stamp())
        old_media = media_dir.parent / (media_dir.name + ".pre-restore-" + _stamp())
        shutil.copy2(staged_db, new_db)
        _copy_media(staged_media, new_media)

        pre_restore = create_backup(
            db_path, media_dir, backup_dir, retain_days=retain_days,
            encryption_key=encryption_key,
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
        "encrypted": encrypted,
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
