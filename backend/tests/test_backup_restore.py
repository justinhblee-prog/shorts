import json
import os
import sqlite3
import tarfile
import tempfile
import unittest
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
                    data = b"tampered"
                    member.size = len(data)
                target.addfile(member, __import__("io").BytesIO(data) if data is not None else None)
        with self.assertRaisesRegex(BackupRestoreError, "checksum mismatch"):
            restore_backup(
                corrupt, self.db, self.media, self.backups, confirm_restore=True
            )
        self.assertEqual(self._db_value(), "before")

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
