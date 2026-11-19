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
        self.assertEqual(worker.run_once(), "review_pending")
        self.assertEqual(self.store.get(job["id"])["status"], "review_pending")

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
            lambda _: {"changed_files": ["backend/example.py"], "tests_passed": True,
                       "validation_ref": "ci://run/44"},
        )
        self.assertEqual(worker.run_once(), "review_pending")
        presence = self.store.get_worker("runner-a")
        self.assertEqual(presence["status"], "online")
        self.assertIsNone(presence["current_job_id"])
        self.assertEqual(self.store.summary()["online_workers"], 1)

    def test_run_until_idle_stops_after_one_review_pending_diff(self):
        first = self.store.create("First diff", scope=["backend/first.py"])
        second = self.store.create("Second diff", scope=["backend/second.py"])
        calls = []

        def execute(job):
            calls.append(job["id"])
            return {
                "changed_files": [job["scope"][0]],
                "tests_passed": True,
                "validation_ref": "ci://run/one",
            }

        worker = DevelopmentJobWorker(self.store, "runner-once", execute, poll_seconds=1)
        result = worker.run_until_idle(idle_seconds=1)
        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["outcomes"], {"review_pending": 1})
        self.assertEqual(calls, [first["id"]])
        self.assertEqual(self.store.get(first["id"])["status"], "review_pending")
        self.assertEqual(self.store.get(second["id"])["status"], "ready")

    def test_run_until_idle_stops_after_failed_attempt_with_partial_workspace_changes(self):
        first = self.store.create("First job leaves a partial diff", scope=["backend/first.py"])
        second = self.store.create("Second job must wait", scope=["backend/second.py"])
        calls = []

        def execute(job):
            calls.append(job["id"])
            (self.root if hasattr(self, "root") else Path(self.tmp.name) / "partial.py").write_text(
                "unvalidated partial change", encoding="utf-8"
            )
            raise RuntimeError("validation failed after partial edit")

        worker = DevelopmentJobWorker(self.store, "runner-failed-once", execute, poll_seconds=1)
        result = worker.run_until_idle(idle_seconds=1)
        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["outcomes"], {"retry_wait": 1})
        self.assertEqual(calls, [first["id"]])
        self.assertEqual(self.store.get(first["id"])["status"], "retry_wait")
        self.assertEqual(self.store.get(second["id"])["status"], "ready")

    def test_run_until_idle_marks_worker_offline_on_exit(self):
        worker = DevelopmentJobWorker(self.store, "runner-idle", lambda _: {})
        result = worker.run_until_idle(idle_seconds=1)
        self.assertEqual(result["processed"], 0)
        self.assertEqual(self.store.get_worker("runner-idle")["status"], "offline")


if __name__ == "__main__":
    unittest.main()
