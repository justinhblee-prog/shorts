"""Fail-closed behavior for the production worker."""
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
_TEMP = tempfile.TemporaryDirectory()
_PREVIOUS_DB = os.environ.get("NEXUS_DB_PATH")
os.environ["NEXUS_DB_PATH"] = str(Path(_TEMP.name) / "worker-test.sqlite3")
try:
    worker = importlib.import_module("worker")
finally:
    if _PREVIOUS_DB is None:
        os.environ.pop("NEXUS_DB_PATH", None)
    else:
        os.environ["NEXUS_DB_PATH"] = _PREVIOUS_DB

from production_pipeline import ProviderError


class WorkerFailClosedTests(unittest.TestCase):
    def setUp(self):
        worker.stopping.clear()

    def tearDown(self):
        worker.stopping.clear()

    def test_heartbeat_database_error_marks_lease_uncertain_and_stops_worker(self):
        lost_lease = worker.threading.Event()
        heartbeat_stop = worker.threading.Event()
        with (
            mock.patch.object(worker.queue, "heartbeat", side_effect=RuntimeError("db unavailable")),
            mock.patch.object(worker.queue, "pause") as pause,
        ):
            worker.heartbeat_loop("job-1", "token-1", lost_lease, heartbeat_stop, interval=0)
        pause.assert_called_once()
        self.assertTrue(lost_lease.is_set())
        self.assertTrue(worker.stopping.is_set())


    def test_orphaned_lifecycle_record_pauses_before_claiming_work(self):
        report = {
            "orphaned": 1,
            "items": [{
                "record_kind": "queue_without_production",
                "job_id": "orphan-job",
                "classification": "queue_without_production_record",
                "production_status": None,
                "queue_status": "queued",
            }],
        }
        with (
            mock.patch.object(worker.queue, "is_paused", return_value=False),
            mock.patch.object(worker.store, "reconcile_missing_runs"),
            mock.patch.object(worker.store, "reconcile_status_integrity",
                              return_value={"unresolved": 0, "repaired": 0,
                                            "unresolved_jobs": []}),
            mock.patch.object(worker.store, "integrity_report", return_value=report),
            mock.patch.object(worker.queue, "pause") as pause,
            mock.patch.object(worker.queue, "claim") as claim,
        ):
            self.assertFalse(worker.run_once())
        pause.assert_called_once()
        self.assertIn("orphan-job", pause.call_args.args[0])
        claim.assert_not_called()

    def test_worker_renews_lease_while_provider_execution_is_active(self):
        import threading

        job = {
            "id": "job-heartbeat",
            "payload": {"brand": "Brain Glitch", "topic": "test"},
            "lease_token": "lease-heartbeat",
        }
        heartbeat_seen = threading.Event()

        def execute(*args, **kwargs):
            self.assertTrue(
                heartbeat_seen.wait(timeout=2),
                "worker did not renew its lease while provider execution was active",
            )
            self.assertIs(kwargs.get("stop_event"), worker.active_lost_lease_event)
            self.assertFalse(kwargs["stop_event"].is_set())
            return {"artifacts": []}

        with (
            mock.patch.object(worker, "HEARTBEAT_SECONDS", 0.01),
            mock.patch.object(worker.queue, "is_paused", return_value=False),
            mock.patch.object(worker.store, "reconcile_missing_runs"),
            mock.patch.object(worker.store, "reconcile_status_integrity",
                              return_value={"unresolved": 0, "repaired": 0,
                                            "unresolved_jobs": []}),
            mock.patch.object(worker.store, "integrity_report",
                              return_value={"orphaned": 0, "items": []}),
            mock.patch.object(worker.queue, "claim", return_value=job),
            mock.patch.object(worker.queue, "heartbeat",
                              side_effect=lambda *args: heartbeat_seen.set()) as heartbeat,
            mock.patch.object(worker.pipeline, "execute", side_effect=execute) as run_pipeline,
            mock.patch.object(worker.queue, "finish") as finish,
            mock.patch.object(worker.store, "reconcile_review_pending"),
        ):
            self.assertTrue(worker.run_once())

        self.assertGreaterEqual(heartbeat.call_count, 1)
        run_pipeline.assert_called_once()
        finish.assert_called_once_with(
            "job-heartbeat", worker.WORKER_ID, "lease-heartbeat",
            {"production_status": "review_pending", "artifact_count": 0},
        )
        self.assertIsNone(worker.active_job_id)
        self.assertIsNone(worker.active_lost_lease_event)

    def test_provider_error_stops_worker_after_recording_job_failure(self):
        job = {"id": "job-1", "payload": {"topic": "test"}, "lease_token": "token-1"}
        with (
            mock.patch.object(worker.queue, "is_paused", return_value=False),
            mock.patch.object(worker.store, "reconcile_missing_runs"),
            mock.patch.object(worker.store, "reconcile_terminal_jobs"),
            mock.patch.object(worker.store, "reconcile_review_pending"),
            mock.patch.object(worker.queue, "claim", return_value=job) as claim,
            mock.patch.object(worker.queue, "fail") as fail,
            mock.patch.object(worker.queue, "pause") as pause,
            mock.patch.object(worker.pipeline, "execute",
                              side_effect=ProviderError("script", "provider unavailable", True)),
        ):
            self.assertTrue(worker.run_once())
        fail.assert_called_once()
        pause.assert_called_once()
        claim.assert_called_once()
        self.assertTrue(worker.stopping.is_set())

    def test_keyboard_interrupt_terminalizes_ambiguous_job_and_pauses_worker(self):
        job = {"id": "job-ctrl-c", "payload": {"topic": "test"}, "lease_token": "token-ctrl-c"}
        with (
            mock.patch.object(worker.queue, "is_paused", return_value=False),
            mock.patch.object(worker.store, "reconcile_missing_runs"),
            mock.patch.object(worker.store, "reconcile_terminal_jobs"),
            mock.patch.object(worker.store, "reconcile_review_pending"),
            mock.patch.object(worker.queue, "claim", return_value=job),
            mock.patch.object(worker.queue, "fail") as fail,
            mock.patch.object(worker.queue, "pause") as pause,
            mock.patch.object(worker.pipeline, "execute", side_effect=KeyboardInterrupt),
        ):
            with self.assertRaises(KeyboardInterrupt):
                worker.run_once()
        fail.assert_not_called()
        pause.assert_called_once()
        self.assertTrue(worker.stopping.is_set())
    def test_main_registers_once_and_uses_process_generation_on_shutdown(self):
        worker.stopping.clear()
        registration = {"generation_token": "process-generation-1"}

        def stop_after_idle(_timeout):
            worker.stopping.set()
            return True

        with (
            mock.patch.object(worker.signal, "signal"),
            mock.patch.object(worker.queue, "register_worker", return_value=registration) as register,
            mock.patch.object(worker.queue, "is_paused", return_value=False),
            mock.patch.object(worker.stopping, "wait", side_effect=stop_after_idle),
            mock.patch.object(worker.queue, "mark_worker_offline") as offline,
        ):
            worker.main()

        register.assert_called_once_with(worker.WORKER_ID, worker.socket.gethostname())
        offline.assert_called_once_with(worker.WORKER_ID, "process-generation-1")

    def test_main_does_not_claim_another_job_after_stop_flag(self):
        worker.stopping.set()
        with (
            mock.patch.object(worker.queue, "is_paused", return_value=False),
            mock.patch.object(worker, "run_once") as run_once,
        ):
            worker.main()
        run_once.assert_not_called()


if __name__ == "__main__":
    unittest.main()
