import base64
import io
import json
import os
import sqlite3
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from backup_restore import (
    BackupRestoreError, create_backup, restore_backup,
)


class BackupRestoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "data" / "nexus.sqlite3"
        self.db.parent.mkdir(parents=True)
        self.media = self.root / "data" / "media"
        self.media.mkdir()
        self.backups = self.root / "backups"
        self.backups.mkdir()
        self._create_db("before")

    def tearDown(self):
        self.tmp.cleanup()

    def _create_db(self, value):
        with sqlite3.connect(self.db) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS sample(value TEXT)")
            connection.execute("DELETE FROM sample")
            connection.execute("INSERT INTO sample(value) VALUES(?)", (value,))

    def _db_value(self):
        with sqlite3.connect(self.db) as connection:
            return connection.execute("SELECT value FROM sample").fetchone()[0]

    def test_backup_contains_consistent_database_and_media_manifest(self):
        (self.media / "clip.mp4").write_bytes(b"ftyp-test-media")
        (self.media / "nested").mkdir()
        (self.media / "nested" / "caption.srt").write_text("hello", encoding="utf-8")
        result = create_backup(self.db, self.media, self.backups)
        self.assertTrue(Path(result["backup_path"]).is_file())
        self.assertEqual(result["media_file_count"], 2)
        with tarfile.open(result["backup_path"], "r:gz") as archive:
            names = set(archive.getnames())
        self.assertIn("manifest.json", names)
        self.assertIn("database.sqlite3", names)
        self.assertIn("media/clip.mp4", names)
        self.assertIn("media/nested/caption.srt", names)

    def test_restore_requires_explicit_confirmation_and_creates_pre_restore_backup(self):
        (self.media / "clip.mp4").write_bytes(b"old")
        backup = create_backup(self.db, self.media, self.backups)["backup_path"]
        self._create_db("after")
        (self.media / "clip.mp4").write_bytes(b"new")
        (self.media / "new-file.txt").write_text("new", encoding="utf-8")
        with self.assertRaisesRegex(BackupRestoreError, "explicit --confirm-restore"):
            restore_backup(backup, self.db, self.media, self.backups)
        result = restore_backup(
            backup, self.db, self.media, self.backups, confirm_restore=True
        )
        self.assertTrue(result["restored"])
        self.assertEqual(self._db_value(), "before")
        self.assertEqual((self.media / "clip.mp4").read_bytes(), b"old")
        self.assertFalse((self.media / "new-file.txt").exists())
        self.assertTrue(Path(result["pre_restore_backup"]).is_file())

    def test_corrupt_archive_is_rejected_without_changing_current_data(self):
        backup = create_backup(self.db, self.media, self.backups)["backup_path"]
        corrupt = self.backups / "corrupt.tar.gz"
        corrupt.write_bytes(b"not a tar archive")
        with self.assertRaises(BackupRestoreError):
            restore_backup(
                corrupt, self.db, self.media, self.backups, confirm_restore=True
            )
        self.assertEqual(self._db_value(), "before")

    def test_media_checksum_mismatch_is_rejected_before_restore(self):
        (self.media / "clip.mp4").write_bytes(b"source")
        backup = create_backup(self.db, self.media, self.backups)["backup_path"]
        # Repack the archive with a modified media payload but unchanged manifest.
        corrupt = self.backups / "tampered.tar.gz"
        with tarfile.open(backup, "r:gz") as source, tarfile.open(corrupt, "w:gz") as target:
            for member in source.getmembers():
                data = source.extractfile(member).read() if member.isfile() else None
                if member.name == "media/clip.mp4":
                    data = b"tamper"
                    member.size = len(data)
                target.addfile(member, __import__("io").BytesIO(data) if data is not None else None)
        with self.assertRaisesRegex(BackupRestoreError, "checksum mismatch"):
            restore_backup(
                corrupt, self.db, self.media, self.backups, confirm_restore=True
            )
        self.assertEqual(self._db_value(), "before")

    def test_restore_rejects_unsafe_archive_member_before_changing_live_data(self):
        backup = create_backup(self.db, self.media, self.backups)["backup_path"]
        corrupt = self.backups / "unsafe-path.tar.gz"
        with tarfile.open(backup, "r:gz") as source, tarfile.open(corrupt, "w:gz") as target:
            for member in source.getmembers():
                stream = source.extractfile(member) if member.isfile() else None
                target.addfile(member, stream)
            extra = tarfile.TarInfo("media/../escape.txt")
            extra.size = 1
            target.addfile(extra, io.BytesIO(b"x"))
        with self.assertRaisesRegex(BackupRestoreError, "unsafe path"):
            restore_backup(corrupt, self.db, self.media, self.backups, confirm_restore=True)
        self.assertEqual(self._db_value(), "before")

    def test_restore_rejects_malformed_manifest_before_changing_live_data(self):
        backup = create_backup(self.db, self.media, self.backups)["backup_path"]
        corrupt = self.backups / "malformed-manifest.tar.gz"
        with tarfile.open(backup, "r:gz") as source, tarfile.open(corrupt, "w:gz") as target:
            for member in source.getmembers():
                if member.name == "manifest.json":
                    payload = json.dumps({
                        "format_version": 1,
                        "database_sha256": "0" * 64,
                        "media_files": "not-a-list",
                    }).encode("utf-8")
                    replacement = tarfile.TarInfo(member.name)
                    replacement.size = len(payload)
                    target.addfile(replacement, io.BytesIO(payload))
                else:
                    stream = source.extractfile(member) if member.isfile() else None
                    target.addfile(member, stream)
        with self.assertRaisesRegex(BackupRestoreError, "media_files must be a list"):
            restore_backup(corrupt, self.db, self.media, self.backups, confirm_restore=True)
        self.assertEqual(self._db_value(), "before")

    def test_backup_and_restore_preserve_empty_media_directories(self):
        (self.media / "empty" / "nested").mkdir(parents=True)
        backup = create_backup(self.db, self.media, self.backups)["backup_path"]
        (self.media / "empty" / "nested").rmdir()
        (self.media / "empty").rmdir()
        result = restore_backup(
            backup, self.db, self.media, self.backups, confirm_restore=True
        )
        self.assertTrue(result["restored"])
        self.assertTrue((self.media / "empty" / "nested").is_dir())

    def test_encrypted_archive_round_trips_database_and_media_and_encrypts_pre_restore_backup(self):
        key = base64.urlsafe_b64encode(b"k" * 32).decode("ascii")
        (self.media / "clip.mp4").write_bytes(b"original-media")
        with patch.dict(os.environ, {
            "NEXUS_BACKUP_ENCRYPTION_KEY": key,
            "NEXUS_BACKUP_ENCRYPTION_REQUIRED": "true",
        }):
            result = create_backup(self.db, self.media, self.backups)
            encrypted = Path(result["backup_path"])
            self.assertTrue(result["encrypted"])
            self.assertTrue(encrypted.name.endswith(".tar.gz.enc"))
            self.assertEqual(encrypted.read_bytes()[:8], b"NEXUSBK1")
            self.assertFalse(list(self.backups.glob("*.tar.gz")))

            self._create_db("after")
            (self.media / "clip.mp4").write_bytes(b"changed-media")
            restored = restore_backup(
                encrypted, self.db, self.media, self.backups, confirm_restore=True
            )

        self.assertTrue(restored["encrypted"])
        self.assertEqual(self._db_value(), "before")
        self.assertEqual((self.media / "clip.mp4").read_bytes(), b"original-media")
        self.assertTrue(Path(restored["pre_restore_backup"]).name.endswith(".tar.gz.enc"))
        self.assertFalse(list(self.root.glob("nexus-restore-*")))
        if os.name != "nt":
            self.assertEqual(encrypted.stat().st_mode & 0o777, 0o600)

    def test_wrong_key_tamper_and_truncation_fail_before_live_data_changes(self):
        key = base64.urlsafe_b64encode(b"a" * 32).decode("ascii")
        wrong_key = base64.urlsafe_b64encode(b"b" * 32).decode("ascii")
        (self.media / "clip.mp4").write_bytes(b"before")
        with patch.dict(os.environ, {
            "NEXUS_BACKUP_ENCRYPTION_KEY": key,
            "NEXUS_BACKUP_ENCRYPTION_REQUIRED": "true",
        }):
            backup = Path(create_backup(self.db, self.media, self.backups)["backup_path"])
            self._create_db("after")
            (self.media / "clip.mp4").write_bytes(b"after")

            with patch.dict(os.environ, {"NEXUS_BACKUP_ENCRYPTION_KEY": wrong_key}):
                with self.assertRaisesRegex(BackupRestoreError, "authentication failed"):
                    restore_backup(
                        backup, self.db, self.media, self.backups, confirm_restore=True
                    )

            tampered = self.backups / "tampered.tar.gz.enc"
            payload = bytearray(backup.read_bytes())
            payload[-17] ^= 0x01
            tampered.write_bytes(payload)
            with self.assertRaisesRegex(BackupRestoreError, "authentication failed"):
                restore_backup(
                    tampered, self.db, self.media, self.backups, confirm_restore=True
                )

            truncated = self.backups / "truncated.tar.gz.enc"
            truncated.write_bytes(b"NEXUSBK1short")
            with self.assertRaisesRegex(BackupRestoreError, "truncated"):
                restore_backup(
                    truncated, self.db, self.media, self.backups, confirm_restore=True
                )

        self.assertEqual(self._db_value(), "after")
        self.assertEqual((self.media / "clip.mp4").read_bytes(), b"after")
        self.assertFalse(list(self.root.glob("nexus-restore-*")))

    def test_encryption_required_rejects_missing_key_and_plaintext_restore(self):
        with patch.dict(os.environ, {
            "NEXUS_BACKUP_ENCRYPTION_KEY": "",
            "NEXUS_BACKUP_ENCRYPTION_REQUIRED": "true",
        }):
            with self.assertRaisesRegex(BackupRestoreError, "key is missing"):
                create_backup(self.db, self.media, self.backups)

        plain = create_backup(self.db, self.media, self.backups, encryption_key=None)["backup_path"]
        key = base64.urlsafe_b64encode(b"z" * 32).decode("ascii")
        with patch.dict(os.environ, {
            "NEXUS_BACKUP_ENCRYPTION_KEY": key,
            "NEXUS_BACKUP_ENCRYPTION_REQUIRED": "true",
        }):
            with self.assertRaisesRegex(BackupRestoreError, "plaintext archive"):
                restore_backup(
                    plain, self.db, self.media, self.backups, confirm_restore=True
                )

    def test_invalid_encryption_key_is_rejected_before_backup_publication(self):
        with self.assertRaisesRegex(BackupRestoreError, "URL-safe base64"):
            create_backup(
                self.db, self.media, self.backups, encryption_key="not@a-valid-key"
            )
        self.assertEqual(list(self.backups.iterdir()), [])

    def test_backup_refuses_media_symlinks(self):
        target = self.root / "outside.txt"
        target.write_text("secret", encoding="utf-8")
        link = self.media / "link.txt"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are not supported in this environment")
        with self.assertRaisesRegex(BackupRestoreError, "symbolic links"):
            create_backup(self.db, self.media, self.backups)

    def test_sqlite_backup_uses_consistent_snapshot_and_integrity_check(self):
        self._create_db("consistent")
        result = create_backup(self.db, self.media, self.backups)
        self.assertGreater(result["size_bytes"], 0)
        self.assertEqual(len(result["sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
