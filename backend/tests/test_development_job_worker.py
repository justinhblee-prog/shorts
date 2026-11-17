import os
import tempfile
import unittest

from development_jobs import DevelopmentJobStore
from development_job_worker import DevelopmentJobWorker, NonRetryableDevelopmentJobError


class DevelopmentJobWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = DevelopmentJobStore(os.path.join(self.tmp.name, "jobs.sqlite3"), lease_seconds=10)

    def tearDown(self):
        self.tmp.cleanup()

    def test_worker_completes_job_with_evidence(self):
        job = self.store.create("Worker completion", scope=["backend/example.py"])
        worker = DevelopmentJobWorker(
            self.store, "worker-a",
            lambda _: {"changed_files": ["backend/example.py"], "tests_passed": True,
                       "validation_ref": "ci://run/42", "result_summary": "implemented"},
        )
        self.assertEqual(worker.run_once(), "completed")
        self.assertEqual(self.store.get(job["id"])["status"], "completed")

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


if __name__ == "__main__":
    unittest.main()
