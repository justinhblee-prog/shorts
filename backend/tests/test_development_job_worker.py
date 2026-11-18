import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from development_jobs import DevelopmentJobStore
from development_job_worker import DevelopmentJobWorker, NonRetryableDevelopmentJobError


class DevelopmentJobWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = DevelopmentJobStore(os.path.join(self.tmp.name, "jobs.sqlite3"), lease_seconds=10)

    def tearDown(self):
        self.tmp.cleanup()

    def _evidence(self, path, validation_ref):
        artifact = Path(self.tmp.name) / "worker-artifact.zip"
        artifact.write_bytes(b"validated worker source snapshot")
        return {
            "changed_files": [path],
            "tests_passed": True,
            "validation_ref": validation_ref,
            "artifact_path": str(artifact),
            "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "result_summary": "implemented",
        }

    def test_worker_stages_validated_job_for_review_publication(self):
        job = self.store.create("Worker completion", scope=["backend/example.py"])
        worker = DevelopmentJobWorker(
            self.store, "worker-a",
            lambda _: self._evidence("backend/example.py", "ci://run/42"),
        )
        self.assertEqual(worker.run_once(), "review_pending")
        pending = self.store.get(job["id"])
        self.assertEqual(pending["status"], "review_pending")
        self.assertIsNone(pending["completed_at"])
        self.assertTrue(pending["artifact_path"])

    def test_worker_rejects_noop_and_schedules_retry(self):
        job = self.store.create("No-op must not pass", scope=["backend/example.py"])
        worker = DevelopmentJobWorker(
            self.store, "worker-a",
            lambda _: {"changed_files": [], "tests_passed": True,
                       "validation_ref": "ci://run/43"},
        )
        self.assertEqual(worker.run_once(), "retry_wait")
        self.assertEqual(self.store.get(job["id"])["status"], "retry_wait")

    def test_worker_records_executor_exception(self):
        job = self.store.create("Executor error", scope=["backend/example.py"])
        def broken(_):
            raise RuntimeError("simulated worker failure")
        worker = DevelopmentJobWorker(self.store, "worker-a", broken)
        self.assertEqual(worker.run_once(), "retry_wait")
        self.assertIn("RuntimeError", self.store.get(job["id"])["result_summary"])

    def test_non_retryable_worker_error_quarantines_job(self):
        job = self.store.create("Unsafe scope", scope=["backend/example.py"])
        def rejected(_):
            raise NonRetryableDevelopmentJobError("scope validation failed")
        worker = DevelopmentJobWorker(self.store, "worker-a", rejected)
        self.assertEqual(worker.run_once(), "quarantined")
        self.assertEqual(self.store.get(job["id"])["status"], "quarantined")

    def test_worker_requires_callable_executor(self):
        with self.assertRaisesRegex(ValueError, "executor"):
            DevelopmentJobWorker(self.store, "worker-a", None)


    def test_run_once_registers_worker_and_clears_current_job(self):
        job = self.store.create("Worker presence", scope=["backend/example.py"])
        worker = DevelopmentJobWorker(
            self.store, "runner-a",
            lambda _: self._evidence("backend/example.py", "ci://run/44"),
        )
        self.assertEqual(worker.run_once(), "review_pending")
        presence = self.store.get_worker("runner-a")
        self.assertEqual(presence["status"], "online")
        self.assertIsNone(presence["current_job_id"])
        self.assertEqual(self.store.summary()["online_workers"], 1)

    def test_run_until_idle_marks_worker_offline_on_exit(self):
        worker = DevelopmentJobWorker(self.store, "runner-idle", lambda _: {})
        result = worker.run_until_idle(idle_seconds=1)
        self.assertEqual(result["processed"], 0)
        self.assertEqual(self.store.get_worker("runner-idle")["status"], "offline")


if __name__ == "__main__":
    unittest.main()
