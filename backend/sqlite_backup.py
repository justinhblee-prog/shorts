"""Safe online SQLite backups with optional authenticated encryption and safe restore."""
from __future__ import annotations

import argparse
import base64
import json
import os
import sqlite3
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

BACKUP_PREFIX = "nexus-"
BACKUP_SUFFIX = ".sqlite3"
ENCRYPTED_BACKUP_SUFFIX = ".sqlite3.enc"
ENCRYPTED_MAGIC = b"NEXUSBK1"
ENCRYPTED_NONCE_BYTES = 12
ENCRYPTED_TAG_BYTES = 16
CHUNK_BYTES = 1024 * 1024


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
        return {"path": str(path.resolve()), "integrity_check": "ok",
                "size_bytes": path.stat().st_size}
    finally:
        connection.close()


def verify_database(path: str | Path) -> dict:
    """Run SQLite integrity_check on a plaintext database without modifying it."""
    return _check_database(Path(path))


def _encryption_key_bytes(key: str | bytes | None) -> bytes:
    if key is None:
        raise ValueError("NEXUS_BACKUP_ENCRYPTION_KEY is required for encrypted backup operations")
    try:
        raw = key.encode("ascii") if isinstance(key, str) else bytes(key)
        decoded = base64.urlsafe_b64decode(raw)
    except (UnicodeEncodeError, ValueError, TypeError) as exc:
        raise ValueError("Backup encryption key must be a URL-safe base64 32-byte key") from exc
    if len(decoded) != 32:
        raise ValueError("Backup encryption key must decode to exactly 32 bytes")
    return decoded


def _is_encrypted_backup(path: Path) -> bool:
    return path.name.endswith(ENCRYPTED_BACKUP_SUFFIX)


def _encrypt_file(source: Path, destination: Path, key: str | bytes) -> None:
    """Stream AES-256-GCM encryption; publish only after the authentication tag is written."""
    key_bytes = _encryption_key_bytes(key)
    source = Path(source)
    destination = Path(destination)
    if source.is_symlink() or not source.is_file():
        raise ValueError("Encryption source must be a regular file")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Encryption destination already exists: {destination}")
    nonce = os.urandom(ENCRYPTED_NONCE_BYTES)
    encryptor = Cipher(algorithms.AES(key_bytes), modes.GCM(nonce)).encryptor()
    created = False
    try:
        with source.open("rb") as input_file, destination.open("xb") as output_file:
            created = True
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


def _decrypt_file(source: Path, destination: Path, key: str | bytes) -> None:
    """Stream authenticated decryption; delete all plaintext if tag verification fails."""
    key_bytes = _encryption_key_bytes(key)
    source = Path(source)
    destination = Path(destination)
    if source.is_symlink() or not source.is_file():
        raise ValueError("Encrypted backup must be a regular non-symlink file")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Decryption destination already exists: {destination}")
    minimum_size = len(ENCRYPTED_MAGIC) + ENCRYPTED_NONCE_BYTES + ENCRYPTED_TAG_BYTES
    size = source.stat().st_size
    if size < minimum_size:
        raise ValueError("Encrypted backup is truncated")
    created = False
    try:
        with source.open("rb") as input_file:
            magic = input_file.read(len(ENCRYPTED_MAGIC))
            if magic != ENCRYPTED_MAGIC:
                raise ValueError("Encrypted backup format or version is invalid")
            nonce = input_file.read(ENCRYPTED_NONCE_BYTES)
            input_file.seek(-ENCRYPTED_TAG_BYTES, os.SEEK_END)
            tag = input_file.read(ENCRYPTED_TAG_BYTES)
            ciphertext_bytes = size - minimum_size
            input_file.seek(len(ENCRYPTED_MAGIC) + ENCRYPTED_NONCE_BYTES)
            decryptor = Cipher(algorithms.AES(key_bytes), modes.GCM(nonce, tag)).decryptor()
            with destination.open("xb") as output_file:
                created = True
                remaining = ciphertext_bytes
                while remaining:
                    chunk = input_file.read(min(CHUNK_BYTES, remaining))
                    if not chunk:
                        raise ValueError("Encrypted backup ciphertext is truncated")
                    remaining -= len(chunk)
                    output_file.write(decryptor.update(chunk))
                try:
                    output_file.write(decryptor.finalize())
                except InvalidTag as exc:
                    raise ValueError("Encrypted backup authentication failed; key or data is invalid") from exc
                output_file.flush()
                os.fsync(output_file.fileno())
    except Exception:
        if created:
            destination.unlink(missing_ok=True)
        raise


def verify_backup(path: str | Path, encryption_key: str | bytes | None = None) -> dict:
    """Verify plaintext or encrypted backup content without leaving decrypted data behind."""
    path = Path(path)
    if not _is_encrypted_backup(path):
        result = verify_database(path)
        result["encrypted"] = False
        return result
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Encrypted backup is not a regular file: {path}")
    with tempfile.TemporaryDirectory(prefix=".nexus-verify-", dir=path.parent) as directory:
        plaintext = Path(directory) / "verified.sqlite3"
        _decrypt_file(path, plaintext, encryption_key)
        _check_database(plaintext)
    return {"path": str(path.resolve()), "integrity_check": "ok",
            "size_bytes": path.stat().st_size, "encrypted": True}


def _copy_snapshot(source: Path, destination: Path) -> None:
    source_connection = sqlite3.connect(_readonly_uri(source), uri=True, timeout=30)
    destination_connection = sqlite3.connect(str(destination), timeout=30)
    try:
        source_connection.backup(destination_connection)
        result = destination_connection.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            detail = result[0] if result else "no integrity result"
            raise sqlite3.DatabaseError(f"Backup integrity check failed: {detail}")
        mode = destination_connection.execute("PRAGMA journal_mode=DELETE").fetchone()
        if not mode or str(mode[0]).lower() != "delete":
            raise sqlite3.DatabaseError("Backup could not be normalized to a standalone DELETE-journal database")
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


def _remove_sqlite_sidecars(path: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        Path(str(path) + suffix).unlink(missing_ok=True)


def _prune_backups(directory: Path, keep: int) -> list[str]:
    candidates = [
        path for path in directory.iterdir()
        if path.name.startswith(BACKUP_PREFIX)
        and (path.name.endswith(BACKUP_SUFFIX) or path.name.endswith(ENCRYPTED_BACKUP_SUFFIX))
        and not path.is_symlink() and path.is_file()
    ]
    candidates.sort(key=lambda item: (item.stat().st_mtime_ns, item.name), reverse=True)
    removed = []
    for path in candidates[keep:]:
        path.unlink()
        _remove_sqlite_sidecars(path)
        removed.append(path.name)
    return removed


def create_backup(source: str | Path, backup_dir: str | Path, keep: int = 14,
                  encryption_key: str | bytes | None = None) -> dict:
    """Create a consistent online backup, optionally encrypt it with AES-256-GCM."""
    source = Path(source)
    backup_dir = Path(backup_dir)
    if keep < 1:
        raise ValueError("keep must be at least 1")
    if encryption_key is not None:
        _encryption_key_bytes(encryption_key)
    _check_database(source)
    backup_dir.mkdir(parents=True, exist_ok=True)
    if backup_dir.is_symlink() or not backup_dir.is_dir():
        raise ValueError(f"Backup destination is not a real directory: {backup_dir}")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    unique = uuid.uuid4().hex[:12]
    suffix = ENCRYPTED_BACKUP_SUFFIX if encryption_key is not None else BACKUP_SUFFIX
    filename = f"{BACKUP_PREFIX}{timestamp}-{unique}{suffix}"
    target = backup_dir / filename
    snapshot = backup_dir / f".{filename}.snapshot.tmp"
    temporary = backup_dir / f".{filename}.tmp{ENCRYPTED_BACKUP_SUFFIX}"
    try:
        _copy_snapshot(source, snapshot)
        os.chmod(snapshot, 0o600)
        if encryption_key is not None:
            _encrypt_file(snapshot, temporary, encryption_key)
            os.chmod(temporary, 0o600)
            verification = verify_backup(temporary, encryption_key)
            os.replace(temporary, target)
            snapshot.unlink(missing_ok=True)
        else:
            os.replace(snapshot, target)
            verification = _check_database(target)
        _fsync_directory(backup_dir)
        removed = _prune_backups(backup_dir, keep)
        _fsync_directory(backup_dir)
        retained = sum(1 for item in backup_dir.iterdir()
                       if item.is_file() and not item.is_symlink()
                       and item.name.startswith(BACKUP_PREFIX)
                       and (item.name.endswith(BACKUP_SUFFIX) or item.name.endswith(ENCRYPTED_BACKUP_SUFFIX)))
        return {"backup_path": str(target.resolve()),
                "integrity_check": verification["integrity_check"],
                "size_bytes": verification["size_bytes"],
                "encrypted": encryption_key is not None,
                "retained": retained, "removed": removed}
    finally:
        snapshot.unlink(missing_ok=True)
        temporary.unlink(missing_ok=True)


def restore_backup(backup: str | Path, target: str | Path,
                   encryption_key: str | bytes | None = None) -> dict:
    """Restore into a new file only; encrypted sources require their original key."""
    backup = Path(backup)
    target = Path(target)
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"Restore target already exists; refusing to overwrite: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    decrypted = None
    source = backup
    temporary = target.parent / f".{target.name}.{uuid.uuid4().hex}.restore"
    try:
        if _is_encrypted_backup(backup):
            decrypted = target.parent / f".{target.name}.{uuid.uuid4().hex}.decrypted.tmp"
            _decrypt_file(backup, decrypted, encryption_key)
            os.chmod(decrypted, 0o600)
            _check_database(decrypted)
            source = decrypted
        else:
            _check_database(backup)
        _copy_snapshot(source, temporary)
        os.chmod(temporary, 0o600)
        os.link(temporary, target)
        temporary.unlink()
        _fsync_directory(target.parent)
        return _check_database(target)
    finally:
        temporary.unlink(missing_ok=True)
        if decrypted is not None:
            decrypted.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    backup_parser = commands.add_parser("backup", help="create and verify an online backup")
    backup_parser.add_argument("--source", default=os.getenv("NEXUS_DB_PATH", "data/nexus.sqlite3"))
    backup_parser.add_argument("--backup-dir", default=os.getenv("NEXUS_BACKUP_DIR", "backups"))
    backup_parser.add_argument("--keep", type=int, default=14)
    backup_parser.add_argument("--encryption-key", default=os.getenv("NEXUS_BACKUP_ENCRYPTION_KEY"))
    verify_parser = commands.add_parser("verify", help="verify a plaintext or encrypted backup")
    verify_parser.add_argument("--path", required=True)
    verify_parser.add_argument("--encryption-key", default=os.getenv("NEXUS_BACKUP_ENCRYPTION_KEY"))
    restore_parser = commands.add_parser("restore", help="restore to a new, non-existing file")
    restore_parser.add_argument("--backup", required=True)
    restore_parser.add_argument("--target", required=True)
    restore_parser.add_argument("--encryption-key", default=os.getenv("NEXUS_BACKUP_ENCRYPTION_KEY"))
    args = parser.parse_args(argv)
    try:
        if args.command == "backup":
            result = create_backup(args.source, args.backup_dir, args.keep, args.encryption_key)
        elif args.command == "verify":
            result = verify_backup(args.path, args.encryption_key)
        else:
            result = restore_backup(args.backup, args.target, args.encryption_key)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"sqlite_backup_error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
