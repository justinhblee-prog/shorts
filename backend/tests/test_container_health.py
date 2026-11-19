import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from container_health import backup_archive_is_fresh, backup_marker_is_fresh, main, process_matches


class ContainerHealthTests(unittest.TestCase):
    def test_process_probe_matches_pid_one_script_argument(self):
        self.assertTrue(process_matches("worker.py", b"/usr/local/bin/python\0worker.py\0"))
        self.assertTrue(process_matches("metrics_collector.py", b"python\0metrics_collector.py\0"))

    def test_process_probe_rejects_wrong_or_unsafe_process_names(self):
        self.assertFalse(process_matches("worker.py", b"python\0scheduler.py\0"))
        self.assertFalse(process_matches("../worker.py", b"python\0../worker.py\0"))
        self.assertFalse(process_matches("", b"python\0worker.py\0"))


    def test_compose_healthchecks_cover_workers_collector_and_backup_freshness(self):
        root = Path(__file__).resolve().parents[2]
        compose = (root / "compose.yaml").read_text(encoding="utf-8")
        example = (root / ".env.example").read_text(encoding="utf-8")
        workflow = (root / ".github" / "workflows" / "compose-smoke.yml").read_text(encoding="utf-8")
        for process in ("worker.py", "scheduler.py", "metrics_collector.py"):
            self.assertIn('container_health.py","process","' + process, compose)
        self.assertIn('container_health.py","backup","/backups/.last-success', compose)
        self.assertIn("NEXUS_BACKUP_HEALTH_MAX_AGE_SECONDS=", example)
        self.assertIn('docker inspect --format', workflow)
        self.assertIn('docker compose exec -T backup test -s /backups/.last-success', workflow)

    def test_backup_marker_accepts_fresh_success_timestamp(self):
        with tempfile.TemporaryDirectory() as temp:
            marker = Path(temp) / ".last-success"
            marker.write_text("success", encoding="utf-8")
            os.utime(marker, (990, 990))
            self.assertTrue(backup_marker_is_fresh(marker, 20, now=1000))

    def test_backup_archive_health_requires_a_recent_retained_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "nexus-backup-20261119T100000Z.tar.gz.enc"
            archive.write_bytes(b"encrypted")
            os.utime(archive, (990, 990))
            self.assertTrue(backup_archive_is_fresh(root, 20, now=1000))
            archive.unlink()
            self.assertFalse(backup_archive_is_fresh(root, 20, now=1000))
            archive.write_bytes(b"old")
            os.utime(archive, (900, 900))
            self.assertFalse(backup_archive_is_fresh(root, 20, now=1000))

    def test_backup_archive_health_fails_closed_for_symlink_and_future_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            target.write_bytes(b"encrypted")
            archive = root / "nexus-backup-20261119T100000Z.tar.gz.enc"
            try:
                archive.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are not supported in this environment")
            self.assertFalse(backup_archive_is_fresh(root, 200, now=1000))
            archive.unlink()
            archive.write_bytes(b"future")
            os.utime(archive, (1100, 1100))
            self.assertFalse(backup_archive_is_fresh(root, 200, now=1000))

    def test_encryption_required_health_rejects_plaintext_only_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plain = root / "nexus-backup-20261119T100000Z.tar.gz"
            plain.write_bytes(b"plaintext")
            os.utime(plain, (990, 990))
            self.assertTrue(backup_archive_is_fresh(root, 20, now=1000))
            self.assertFalse(
                backup_archive_is_fresh(root, 20, now=1000, encryption_required=True)
            )
            encrypted = root / "nexus-backup-20261119T100001Z.tar.gz.enc"
            encrypted.write_bytes(b"encrypted")
            os.utime(encrypted, (990, 990))
            self.assertTrue(
                backup_archive_is_fresh(root, 20, now=1000, encryption_required=True)
            )

    def test_backup_health_cli_requires_marker_and_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            marker = root / ".last-success"
            archive = root / "nexus-backup-current.tar.gz.enc"
            marker.write_text("success", encoding="utf-8")
            archive.write_bytes(b"encrypted")
            with patch.dict(os.environ, {
                "NEXUS_BACKUP_HEALTH_MAX_AGE_SECONDS": "300",
                "NEXUS_BACKUP_ENCRYPTION_REQUIRED": "true",
            }):
                self.assertEqual(main(["backup", str(marker)]), 0)
                archive.unlink()
                self.assertEqual(main(["backup", str(marker)]), 1)
                archive.write_bytes(b"plaintext")
                self.assertEqual(main(["backup", str(marker)]), 1)
                archive.unlink()
                archive = root / "nexus-backup-current.tar.gz.enc"
                archive.write_bytes(b"encrypted")
                self.assertEqual(main(["backup", str(marker)]), 0)

    def test_backup_marker_rejects_stale_future_symlink_and_invalid_age(self):
        with tempfile.TemporaryDirectory() as temp:
            marker = Path(temp) / ".last-success"
            target = Path(temp) / "target"
            target.write_text("success", encoding="utf-8")
            marker.write_text("success", encoding="utf-8")
            os.utime(marker, (900, 900))
            self.assertFalse(backup_marker_is_fresh(marker, 20, now=1000))
            os.utime(marker, (1100, 1100))
            self.assertFalse(backup_marker_is_fresh(marker, 20, now=1000))
            marker.unlink()
            try:
                marker.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are not supported in this environment")
            self.assertFalse(backup_marker_is_fresh(marker, 200, now=1000))
            self.assertFalse(backup_marker_is_fresh(target, 0, now=1000))


if __name__ == "__main__":
    unittest.main()
