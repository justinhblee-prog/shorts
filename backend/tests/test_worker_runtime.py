import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from worker_runtime import heartbeat_interval, request_worker_shutdown
from worker_scratch import WorkerScratchWorkspace


class WorkerRuntimeTests(unittest.TestCase):
    def test_scratch_workspace_is_private_and_restores_temp_environment(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            original = os.environ.get("TMPDIR")
            cached = tempfile.tempdir
            workspace = WorkerScratchWorkspace("job-1", "worker-1", "token-1", root=root)
            workspace.start()
            try:
                self.assertTrue(workspace.path.is_dir())
                self.assertEqual(os.environ["TMPDIR"], str(workspace.path))
                self.assertEqual(workspace.path.stat().st_mode & 0o777, 0o700)
                workspace.heartbeat()
            finally:
                self.assertTrue(workspace.close())
            self.assertEqual(os.environ.get("TMPDIR"), original)
            self.assertEqual(tempfile.tempdir, cached)

    def test_scratch_available_bytes_reports_filesystem_capacity(self):
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as root:
            with patch("worker_scratch.shutil.disk_usage", return_value=type("Usage", (), {"free": 12345})()):
                self.assertEqual(WorkerScratchWorkspace.available_bytes(root=root), 12345)

    def test_lease_heartbeat_does_not_follow_planted_temp_symlink(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "victim.txt"
            target.write_text("keep-me", encoding="utf-8")
            workspace = WorkerScratchWorkspace("job", "worker", "token", root=root)
            workspace.start()
            try:
                planted = workspace.path / ".lease-update.tmp"
                planted.symlink_to(target)
                workspace.heartbeat()
                self.assertEqual(target.read_text(encoding="utf-8"), "keep-me")
                self.assertTrue(planted.is_symlink())
            finally:
                self.assertTrue(workspace.close())

    def test_scratch_pruner_removes_only_expired_valid_job_directory(self):
        import hashlib
        import json
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as root:
            expired = Path(root) / "job-expired"
            expired.mkdir()
            (expired / ".nexus-lease.json").write_text(json.dumps({
                "version": 1, "job_id_sha256": hashlib.sha256(b"old").hexdigest(),
                "worker_id": "worker",
                "lease_token_sha256": hashlib.sha256(b"old-token").hexdigest(),
                "lease_expires_at": 100,
            }), encoding="utf-8")
            recent = Path(root) / "job-recent"
            recent.mkdir()
            (recent / ".nexus-lease.json").write_text(json.dumps({
                "version": 1, "job_id_sha256": "a"*64, "worker_id": "worker",
                "lease_token_sha256": "b"*64, "lease_expires_at": 9999,
            }), encoding="utf-8")
            malformed = Path(root) / "job-malformed"
            malformed.mkdir()
            (malformed / ".nexus-lease.json").write_text("{", encoding="utf-8")
            result = WorkerScratchWorkspace.prune_expired(root=root, grace_seconds=300, now=1000)
            self.assertEqual(result["count"], 1)
            self.assertFalse(expired.exists())
            self.assertTrue(recent.exists())
            self.assertTrue(malformed.exists())

    def test_scratch_cleanup_fails_closed_when_lease_marker_is_replaced(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            workspace = WorkerScratchWorkspace("job", "worker", "token", root=root)
            workspace.start()
            workspace.marker.write_text("{}", encoding="utf-8")
            self.assertFalse(workspace.close())
            self.assertTrue(workspace.path.exists())

    def test_default_heartbeat_is_ten_seconds(self):
        self.assertEqual(heartbeat_interval(300), 10)

    def test_heartbeat_is_capped_to_one_third_of_lease(self):
        self.assertEqual(heartbeat_interval(30, 20), 10)
        self.assertEqual(heartbeat_interval(90, 60), 30)

    def test_heartbeat_never_falls_below_five_seconds(self):
        self.assertEqual(heartbeat_interval(30, 1), 5)
        self.assertEqual(heartbeat_interval(10, 2), 5)

    def test_configured_heartbeat_is_respected_below_lease_cap(self):
        self.assertEqual(heartbeat_interval(300, 15), 15)

    def test_sigterm_signals_local_stop_and_pauses_active_production(self):
        import threading

        class Queue:
            def __init__(self):
                self.pauses = []
            def pause(self, reason, job_id):
                self.pauses.append((reason, job_id))

        queue = Queue()
        stopping = threading.Event()
        lost_lease = threading.Event()
        request_worker_shutdown(queue, stopping, "job-1", lost_lease, 15)
        self.assertTrue(stopping.is_set())
        self.assertTrue(lost_lease.is_set())
        self.assertEqual(len(queue.pauses), 1)
        self.assertEqual(queue.pauses[0][1], "job-1")
        self.assertIn("signal 15", queue.pauses[0][0])

    def test_sigterm_still_stops_locally_if_pause_persistence_fails(self):
        import threading

        class BrokenQueue:
            def pause(self, reason, job_id):
                raise OSError("database unavailable")

        stopping = threading.Event()
        lost_lease = threading.Event()
        request_worker_shutdown(BrokenQueue(), stopping, "job-2", lost_lease, 15)
        self.assertTrue(stopping.is_set())
        self.assertTrue(lost_lease.is_set())


if __name__ == "__main__":
    unittest.main()
