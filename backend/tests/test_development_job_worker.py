import os
import tempfile
import threading
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

    def test_worker_redacts_secrets_before_persisting_executor_errors(self):
        job = self.store.create("Secret-bearing executor failure", scope=["backend/example.py"])
        secret_values = (
            "abc.def", "ghp_123456789012345678901234567890",
            "postgres://user:password@db.example/nexus", "private-key-material",
            "firebase-private-secret",
        )

        def broken(_):
            raise RuntimeError(
                "Bearer abc.def GITHUB_TOKEN=ghp_123456789012345678901234567890 "
                "DATABASE_URL=postgres://user:password@db.example/nexus "
                "PRIVATE_KEY=private-key-material "
                'FIREBASE_SERVICE_ACCOUNT={\\n  "type": "service_account",\\n  "private_key": "firebase-private-secret"\\n}'
            )

        worker = DevelopmentJobWorker(self.store, "worker-redaction", broken)
        self.assertEqual(worker.run_once(), "retry_wait")
        summary = self.store.get(job["id"])["result_summary"]
        for secret in secret_values:
            with self.subTest(secret=secret):
                self.assertNotIn(secret, summary)
        self.assertIn("[REDACTED]", summary)

    def test_worker_redacts_pem_and_database_url(self):
        job = self.store.create("PEM and database diagnostic failure", scope=["backend/example.py"])
        pem = "-----BEGIN OPENSSH PRIVATE KEY-----\\nprivate-key-body\\n-----END OPENSSH PRIVATE KEY-----"
        mongo_url = "mongodb://user:password@db.example/nexus"

        def broken(_):
            raise RuntimeError(f"{pem} {mongo_url}")

        worker = DevelopmentJobWorker(self.store, "worker-pem-redaction", broken)
        self.assertEqual(worker.run_once(), "retry_wait")
        summary = self.store.get(job["id"])["result_summary"]
        for secret in (pem, "private-key-body", mongo_url, "password"):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, summary)
        self.assertIn("[REDACTED]", summary)

    def test_worker_redacts_successful_summary_and_validation_reference(self):
        job = self.store.create("Secret in successful evidence", scope=["backend/example.py"])
        secret = "ghp_123456789012345678901234567890"
        worker = DevelopmentJobWorker(
            self.store, "worker-success-redaction",
            lambda _: {
                "changed_files": ["backend/example.py"],
                "tests_passed": True,
                "validation_ref": f"https://ci.example/run/1?DATABASE_URL=postgres://user:password@db.example/{secret}",
                "result_summary": f"completed with DATABASE_URL=postgres://user:password@db.example/{secret}",
            },
        )
        self.assertEqual(worker.run_once(), "review_pending")
        saved = self.store.get(job["id"])
        self.assertNotIn(secret, saved["result_summary"])
        self.assertNotIn(secret, saved["validation_ref"])
        self.assertIn("[REDACTED]", saved["result_summary"])
        self.assertIn("[REDACTED]", saved["validation_ref"])

    def test_worker_redacts_multiline_service_account_json(self):
        job = self.store.create("Service account diagnostic", scope=["backend/example.py"])

        def broken(_):
            raise RuntimeError(
                'FIREBASE_SERVICE_ACCOUNT={\n'
                '  "type": "service_account",\n'
                '  "private_key": "firebase-private-secret"\n}'
            )

        worker = DevelopmentJobWorker(self.store, "worker-service-account-redaction", broken)
        self.assertEqual(worker.run_once(), "retry_wait")
        summary = self.store.get(job["id"])["result_summary"]
        self.assertNotIn("firebase-private-secret", summary)
        self.assertNotIn('"type": "service_account"', summary)
        self.assertIn("[REDACTED]", summary)

    def test_non_retryable_worker_error_quarantines_job(self):
        job = self.store.create("Unsafe scope", scope=["backend/example.py"])
        def rejected(_):
            raise NonRetryableDevelopmentJobError("scope validation failed")
        worker = DevelopmentJobWorker(self.store, "worker-a", rejected)
        self.assertEqual(worker.run_once(), "quarantined")
        self.assertEqual(self.store.get(job["id"])["status"], "quarantined")

    def test_worker_stops_executor_when_heartbeat_call_blocks_past_lease_budget(self):
        job = self.store.create("Heartbeat storage stall", scope=["backend/example.py"])
        self.store.lease_seconds = 4
        heartbeat_started = threading.Event()

        def stalled_heartbeat(*args, **kwargs):
            heartbeat_started.set()
            threading.Event().wait(timeout=3.5)
            raise OSError("database busy timeout")

        def wait_for_fence(claimed):
            self.assertTrue(heartbeat_started.wait(timeout=3))
            self.assertTrue(claimed["_lease_lost_event"].wait(timeout=3))
            return {
                "changed_files": ["backend/example.py"],
                "tests_passed": True,
                "validation_ref": "ci://must-not-be-recorded",
            }

        worker = DevelopmentJobWorker(self.store, "worker-heartbeat-stall", wait_for_fence)
        original_heartbeat = self.store.heartbeat
        self.store.heartbeat = stalled_heartbeat
        try:
            self.assertEqual(worker.run_once(), "lease_lost")
        finally:
            self.store.heartbeat = original_heartbeat
        saved = self.store.get(job["id"])
        self.assertEqual(saved["status"], "leased")
        self.assertIsNone(saved["validation_ref"])


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
            with open(os.path.join(self.tmp.name, "partial.py"), "w", encoding="utf-8") as partial:
                partial.write("unvalidated partial change")
            raise RuntimeError("validation failed after partial edit")

        worker = DevelopmentJobWorker(self.store, "runner-failed-once", execute, poll_seconds=1)
        result = worker.run_until_idle(idle_seconds=1)
        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["outcomes"], {"retry_wait": 1})
        self.assertEqual(calls, [first["id"]])
        self.assertEqual(self.store.get(first["id"])["status"], "retry_wait")
        self.assertEqual(self.store.get(second["id"])["status"], "ready")

    def test_run_forever_returns_after_one_claimed_job(self):
        first = self.store.create("First daemon job", scope=["backend/first.py"])
        second = self.store.create("Second daemon job", scope=["backend/second.py"])
        calls = []

        def execute(job):
            calls.append(job["id"])
            return {
                "changed_files": [job["scope"][0]],
                "tests_passed": True,
                "validation_ref": "ci://run/daemon",
            }

        worker = DevelopmentJobWorker(self.store, "runner-daemon", execute, poll_seconds=1)
        worker.run_forever()
        self.assertEqual(calls, [first["id"]])
        self.assertEqual(self.store.get(first["id"])["status"], "review_pending")
        self.assertEqual(self.store.get(second["id"])["status"], "ready")
        self.assertEqual(self.store.get_worker("runner-daemon")["status"], "offline")

    def test_run_until_idle_marks_worker_offline_on_exit(self):
        worker = DevelopmentJobWorker(self.store, "runner-idle", lambda _: {})
        result = worker.run_until_idle(idle_seconds=1)
        self.assertEqual(result["processed"], 0)
        self.assertEqual(self.store.get_worker("runner-idle")["status"], "offline")


if __name__ == "__main__":
    unittest.main()
