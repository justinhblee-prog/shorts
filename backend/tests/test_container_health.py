import os
import tempfile
import unittest
from pathlib import Path

from container_health import backup_marker_is_fresh, process_matches


class ContainerHealthTests(unittest.TestCase):
    def test_process_probe_matches_pid_one_script_argument(self):
        self.assertTrue(process_matches("worker.py", b"/usr/local/bin/python\0worker.py\0"))
        self.assertTrue(process_matches("metrics_collector.py", b"python\0metrics_collector.py\0"))

    def test_process_probe_rejects_wrong_or_unsafe_process_names(self):
        self.assertFalse(process_matches("worker.py", b"python\0scheduler.py\0"))
        self.assertFalse(process_matches("../worker.py", b"python\0../worker.py\0"))
        self.assertFalse(process_matches("", b"python\0worker.py\0"))

    def test_backup_marker_accepts_fresh_success_timestamp(self):
        with tempfile.TemporaryDirectory() as temp:
            marker = Path(temp) / ".last-success"
            marker.write_text("success", encoding="utf-8")
            os.utime(marker, (990, 990))
            self.assertTrue(backup_marker_is_fresh(marker, 20, now=1000))

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
