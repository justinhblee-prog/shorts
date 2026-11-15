import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from sqlite_backup import create_backup, restore_backup, verify_database


class SQLiteBackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / "nexus.sqlite3"
        with sqlite3.connect(self.source) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("CREATE TABLE events(id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
            connection.execute("INSERT INTO events(value) VALUES('committed in WAL')")
            connection.commit()
        self.backups = self.root / "backups"

    def tearDown(self):
        self.tmp.cleanup()

    def rows(self, path):
        with sqlite3.connect(path) as connection:
            return connection.execute("SELECT value FROM events ORDER BY id").fetchall()

    def test_online_backup_includes_committed_wal_data_and_passes_integrity(self):
        result = create_backup(self.source, self.backups)
        backup = Path(result["backup_path"])
        self.assertTrue(backup.is_file())
        self.assertEqual(result["integrity_check"], "ok")
        self.assertEqual(self.rows(backup), [("committed in WAL",)])
        self.assertEqual(verify_database(backup)["integrity_check"], "ok")
        if os.name != "nt":
            self.assertEqual(backup.stat().st_mode & 0o777, 0o600)

    def test_restore_creates_verified_new_database_without_overwriting(self):
        backup = Path(create_backup(self.source, self.backups)["backup_path"])
        restored = self.root / "restored.sqlite3"
        result = restore_backup(backup, restored)
        self.assertEqual(result["integrity_check"], "ok")
        self.assertEqual(self.rows(restored), [("committed in WAL",)])
        with self.assertRaises(FileExistsError):
            restore_backup(backup, restored)
        self.assertEqual(self.rows(restored), [("committed in WAL",)])

    def test_retention_keeps_only_newest_requested_backups(self):
        created = [create_backup(self.source, self.backups, keep=2) for _ in range(3)]
        files = list(self.backups.glob("nexus-*.sqlite3"))
        self.assertEqual(len(files), 2)
        self.assertTrue(Path(created[-1]["backup_path"]).exists())
        self.assertEqual(len(created[-1]["removed"]), 1)

    def test_corrupt_source_fails_without_leaving_partial_backup(self):
        corrupt = self.root / "corrupt.sqlite3"
        corrupt.write_bytes(b"not a sqlite database")
        with self.assertRaises(sqlite3.DatabaseError):
            create_backup(corrupt, self.backups)
        self.assertFalse(self.backups.exists())

    def test_backup_directory_symlink_is_rejected(self):
        real = self.root / "real-backups"
        real.mkdir()
        link = self.root / "linked-backups"
        try:
            link.symlink_to(real, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("directory symlinks are unavailable")
        with self.assertRaises(ValueError):
            create_backup(self.source, link)


if __name__ == "__main__":
    unittest.main()
