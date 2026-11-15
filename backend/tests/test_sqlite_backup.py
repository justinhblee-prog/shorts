import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from sqlite_backup import create_backup, restore_backup, verify_database, verify_backup
from cryptography.fernet import Fernet


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

    def test_encrypted_backup_is_authenticated_and_restores_without_plaintext_artifacts(self):
        key = Fernet.generate_key()
        result = create_backup(self.source, self.backups, encryption_key=key)
        encrypted = Path(result["backup_path"])
        self.assertTrue(encrypted.name.endswith(".sqlite3.enc"))
        self.assertTrue(result["encrypted"])
        self.assertEqual(verify_backup(encrypted, key)["integrity_check"], "ok")
        self.assertEqual(len(list(self.backups.glob("*.sqlite3"))), 0)
        restored = self.root / "encrypted-restore.sqlite3"
        restored_result = restore_backup(encrypted, restored, encryption_key=key)
        self.assertEqual(restored_result["integrity_check"], "ok")
        self.assertEqual(self.rows(restored), [("committed in WAL",)])
        self.assertEqual(list(self.root.glob(".*.decrypted.tmp")), [])
        self.assertEqual(list(self.backups.glob(".*.snapshot.tmp")), [])

    def test_encrypted_backup_rejects_wrong_key_and_leaves_no_plaintext_or_target(self):
        key = Fernet.generate_key()
        wrong_key = Fernet.generate_key()
        encrypted = Path(create_backup(self.source, self.backups, encryption_key=key)["backup_path"])
        target = self.root / "must-not-exist.sqlite3"
        with self.assertRaisesRegex(ValueError, "authentication failed"):
            restore_backup(encrypted, target, encryption_key=wrong_key)
        self.assertFalse(target.exists())
        self.assertEqual(list(self.root.glob(".*.decrypted.tmp")), [])

    def test_encrypted_backup_tampering_is_detected_during_verification(self):
        key = Fernet.generate_key()
        encrypted = Path(create_backup(self.source, self.backups, encryption_key=key)["backup_path"])
        payload = bytearray(encrypted.read_bytes())
        payload[-17] ^= 0x01
        encrypted.write_bytes(payload)
        with self.assertRaisesRegex(ValueError, "authentication failed"):
            verify_backup(encrypted, key)
        self.assertEqual(list(self.backups.glob(".nexus-verify-*")), [])

    def test_encrypted_backup_requires_key_for_verify_and_restore(self):
        key = Fernet.generate_key()
        encrypted = Path(create_backup(self.source, self.backups, encryption_key=key)["backup_path"])
        with self.assertRaisesRegex(ValueError, "ENCRYPTION_KEY is required"):
            verify_backup(encrypted)
        with self.assertRaisesRegex(ValueError, "ENCRYPTION_KEY is required"):
            restore_backup(encrypted, self.root / "no-key.sqlite3")

    def test_backup_retention_counts_plaintext_and_encrypted_files_together(self):
        create_backup(self.source, self.backups, keep=5)
        encrypted = create_backup(
            self.source, self.backups, keep=1, encryption_key=Fernet.generate_key()
        )
        files = [p for p in self.backups.iterdir() if p.name.startswith("nexus-")]
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].name.endswith(".sqlite3.enc"))
        self.assertEqual(encrypted["retained"], 1)

    def test_encryption_does_not_delete_a_destination_created_by_another_process(self):
        from sqlite_backup import _encrypt_file, _decrypt_file
        key = Fernet.generate_key()
        source = self.root / "payload.bin"
        source.write_bytes(b"payload")
        destination = self.root / "already-there.bin"
        destination.write_bytes(b"preserve-me")
        with self.assertRaises(FileExistsError):
            _encrypt_file(source, destination, key)
        self.assertEqual(destination.read_bytes(), b"preserve-me")
        encrypted = self.root / "encrypted.bin"
        _encrypt_file(source, encrypted, key)
        decrypted_target = self.root / "already-decrypted.bin"
        decrypted_target.write_bytes(b"preserve-me-too")
        with self.assertRaises(FileExistsError):
            _decrypt_file(encrypted, decrypted_target, key)
        self.assertEqual(decrypted_target.read_bytes(), b"preserve-me-too")


if __name__ == "__main__":
    unittest.main()
