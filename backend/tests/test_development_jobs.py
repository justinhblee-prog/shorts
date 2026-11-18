import hashlib
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from development_jobs import (
    DevelopmentJobConflict, DevelopmentJobNotFound, DevelopmentJobStore,
)


class DevelopmentJobStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = DevelopmentJobStore(os.path.join(self.tmp.name, "jobs.sqlite3"), lease_seconds=30)

    def tearDown(self):
        self.tmp.cleanup()

    def _prepare(self, job_id, worker_id, lease_token, changed_files, tests_passed, validation_ref):
        artifact = Path(self.tmp.name) / ("artifact-" + hashlib.sha256(job_id.encode("utf-8")).hexdigest() + ".zip")
        artifact.write_bytes(("validated source for " + job_id).encode("utf-8"))
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        return self.store.prepare_review(
            job_id, worker_id, lease_token, changed_files, tests_passed,
            validation_ref, str(artifact), digest,
        )

    def _publish(self, files):
        sha = "a" * 40
        result = self.store.publish_review(
            "https://github.com/acme/app/pull/123", sha, files, expected_head_sha=sha,
        )
        self.assertEqual(result["pending_job_ids"], [])
        return result

    def test_create_and_claim_ready_job(self):
        job = self.store.create("Add job registry", scope=["backend/development_jobs.py"],
                                acceptance=["persistent", "audited"])
        claimed = self.store.claim_ready("worker-a")
        self.assertEqual(claimed["id"], job["id"])
        self.assertEqual(claimed["status"], "leased")
        self.assertEqual(claimed["attempts"], 1)
        self.assertTrue(claimed["lease_token"])
        self.assertIsNone(self.store.claim_ready("worker-b"))

    def test_dependency_blocks_until_parent_completed(self):
        parent = self.store.create("Parent", scope=["backend/module.py"])
        child = self.store.create("Child")
        self.store.add_dependency(child["id"], parent["id"])
        self.assertEqual(self.store.get(child["id"])["status"], "blocked")
        claim = self.store.claim_ready("worker-a")
        self.assertEqual(claim["id"], parent["id"])
        self.store.heartbeat(parent["id"], "worker-a", claim["lease_token"])
        prepared = self._prepare(parent["id"], "worker-a", claim["lease_token"],
                                 ["backend/module.py"], True, "ci://run/123")
        self.assertEqual(prepared["status"], "review_pending")
        self.assertEqual(self.store.get(child["id"])["status"], "blocked")
        self._publish(["backend/module.py"])
        next_job = self.store.claim_ready("worker-b")
        self.assertEqual(next_job["id"], child["id"])

    def test_dependency_cycle_is_rejected(self):
        first = self.store.create("First")
        second = self.store.create("Second")
        self.store.add_dependency(second["id"], first["id"])
        with self.assertRaises(DevelopmentJobConflict):
            self.store.add_dependency(first["id"], second["id"])

    def test_missing_dependency_is_rejected(self):
        job = self.store.create("Job")
        with self.assertRaises(DevelopmentJobNotFound):
            self.store.add_dependency(job["id"], "missing")

    def test_completion_gate_rejects_noop_and_test_only(self):
        job = self.store.create("Must change code")
        claim = self.store.claim_ready("worker-a")
        with self.assertRaisesRegex(ValueError, "changed file"):
            self._prepare(job["id"], "worker-a", claim["lease_token"],
                                [], True, "ci://run/1")
        with self.assertRaisesRegex(ValueError, "tests_passed"):
            self._prepare(job["id"], "worker-a", claim["lease_token"],
                                ["backend/file.py"], False, "ci://run/1")
        self.assertEqual(self.store.get(job["id"])["status"], "leased")

    def test_completion_requires_evidence_and_valid_fence(self):
        job = self.store.create("Completion", scope=["backend/file.py"])
        claim = self.store.claim_ready("worker-a")
        with self.assertRaisesRegex(ValueError, "validation evidence"):
            self._prepare(job["id"], "worker-a", claim["lease_token"],
                                ["backend/file.py"], True, "")
        with self.assertRaises(DevelopmentJobConflict):
            self._prepare(job["id"], "worker-b", claim["lease_token"],
                                ["backend/file.py"], True, "ci://run/2")
        completed = self._prepare(job["id"], "worker-a", claim["lease_token"],
                                        ["backend/file.py"], True, "ci://run/2")
        self.assertEqual(completed["status"], "review_pending")
        self.assertEqual(completed["changed_files"], ["backend/file.py"])
        self.assertTrue(completed["tests_passed"])
        self._publish(["backend/file.py"])
        completed = self.store.get(job["id"])
        self.assertEqual(completed["status"], "completed")


    def test_publication_rejects_head_sha_mismatch_and_missing_changed_files(self):
        job = self.store.create("Publication evidence", scope=["backend/file.py"])
        claim = self.store.claim_ready("worker-a")
        self._prepare(job["id"], "worker-a", claim["lease_token"],
                      ["backend/file.py"], True, "ci://run/88")
        with self.assertRaises(DevelopmentJobConflict):
            self.store.publish_review(
                "https://github.com/acme/app/pull/123", "b" * 40,
                ["backend/file.py"], expected_head_sha="c" * 40,
            )
        missing = self.store.publish_review(
            "https://github.com/acme/app/pull/123", "b" * 40,
            ["backend/other.py"], expected_head_sha="b" * 40,
        )
        self.assertEqual(missing["completed_job_ids"], [])
        self.assertEqual(missing["pending_job_ids"], [job["id"]])
        self.assertEqual(self.store.get(job["id"])["status"], "review_pending")

    def test_publication_is_idempotent_after_exact_pr_head_is_recorded(self):
        job = self.store.create("Published once", scope=["backend/file.py"])
        claim = self.store.claim_ready("worker-a")
        self._prepare(job["id"], "worker-a", claim["lease_token"],
                      ["backend/file.py"], True, "ci://run/89")
        first = self._publish(["backend/file.py"])
        second = self._publish(["backend/file.py"])
        self.assertEqual(first["completed_job_ids"], [job["id"]])
        self.assertEqual(second["completed_job_ids"], [])
        self.assertEqual(len([e for e in self.store.events(job["id"]) if e["event_type"] == "review_published"]), 1)

    def test_event_history_is_append_only(self):
        job = self.store.create("Audit")
        with self.store.db() as connection:
            event_id = connection.execute(
                "SELECT id FROM development_job_events WHERE job_id=? LIMIT 1",
                (job["id"],),
            ).fetchone()["id"]
            with self.assertRaisesRegex(sqlite3.IntegrityError,
                                        "development job events are immutable"):
                connection.execute("UPDATE development_job_events SET actor='tampered' WHERE id=?",
                                   (event_id,))

    def test_retry_wait_is_reclaimed_and_non_retryable_failure_quarantines(self):
        job = self.store.create("Retry", max_attempts=3)
        first = self.store.claim_ready("worker-a")
        waiting = self.store.fail(job["id"], "worker-a", first["lease_token"],
                                  "temporary provider error", retry_delay_seconds=0)
        self.assertEqual(waiting["status"], "retry_wait")
        second = self.store.claim_ready("worker-b")
        self.assertEqual(second["id"], job["id"])
        self.assertEqual(second["attempts"], 2)
        quarantined = self.store.fail(job["id"], "worker-b", second["lease_token"],
                                      "permanent validation error", retryable=False)
        self.assertEqual(quarantined["status"], "quarantined")
        self.assertIsNone(self.store.claim_ready("worker-c"))

    def test_overlapping_file_scope_serializes_jobs(self):
        first = self.store.create("Writer A", scope=["backend/shared.py"])
        second = self.store.create("Writer B", scope=["backend/shared.py"])
        claim = self.store.claim_ready("worker-a")
        self.assertEqual(claim["id"], first["id"])
        self.assertIsNone(self.store.claim_ready("worker-b"))
        self._prepare(first["id"], "worker-a", claim["lease_token"],
                      ["backend/shared.py"], True, "ci://run/1")
        self.assertIsNone(self.store.claim_ready("worker-b"))
        self._publish(["backend/shared.py"])
        next_claim = self.store.claim_ready("worker-b")
        self.assertEqual(next_claim["id"], second["id"])

    def test_parent_child_path_scopes_conflict(self):
        self.assertTrue(self.store._scopes_conflict(["backend"], ["backend/api.py"]))
        self.assertFalse(self.store._scopes_conflict(["backend/api.py"], ["frontend/app.js"]))
        self.assertTrue(self.store._scopes_conflict([], ["frontend/app.js"]))

    def test_attempt_limit_quarantines_job(self):
        job = self.store.create("One attempt only", max_attempts=1)
        claim = self.store.claim_ready("worker-a")
        result = self.store.fail(job["id"], "worker-a", claim["lease_token"], "failed")
        self.assertEqual(result["status"], "quarantined")

    def test_expired_lease_is_reclaimed_and_old_worker_is_fenced(self):
        job = self.store.create("Lease recovery")
        first = self.store.claim_ready("worker-a")
        with self.store.db() as connection:
            connection.execute(
                "UPDATE development_jobs SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",
                (job["id"],),
            )
        second = self.store.claim_ready("worker-b")
        self.assertEqual(second["id"], job["id"])
        self.assertNotEqual(first["lease_token"], second["lease_token"])
        with self.assertRaises(DevelopmentJobConflict):
            self._prepare(job["id"], "worker-a", first["lease_token"],
                                ["backend/file.py"], True, "ci://run/stale")
        self.assertEqual(self.store.get(job["id"])["worker_id"], "worker-b")

    def test_parallel_workers_claim_distinct_jobs(self):
        from concurrent.futures import ThreadPoolExecutor
        jobs = [self.store.create("Job " + str(i), scope=["backend/module_" + str(i) + ".py"]) for i in range(4)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            claimed = list(pool.map(lambda i: self.store.claim_ready("worker-" + str(i)), range(4)))
        ids = [item["id"] for item in claimed if item]
        self.assertEqual(len(ids), 4)
        self.assertEqual(len(set(ids)), 4)


    def test_completion_rejects_changed_files_outside_declared_scope(self):
        job = self.store.create("Scoped completion", scope=["backend/allowed.py"])
        claim = self.store.claim_ready("worker-a")
        with self.assertRaisesRegex(ValueError, "outside the declared scope"):
            self._prepare(job["id"], "worker-a", claim["lease_token"],
                                ["backend/other.py"], True, "ci://run/3")
        self.assertEqual(self.store.get(job["id"])["status"], "leased")

    def test_completion_rejects_unsafe_and_duplicate_paths(self):
        job = self.store.create("Safe paths", scope=["backend"])
        claim = self.store.claim_ready("worker-a")
        for paths in (["../outside.py"], ["backend\\\\secret.py"], ["backend/a.py", "backend/a.py"]):
            with self.subTest(paths=paths):
                with self.assertRaises(ValueError):
                    self._prepare(job["id"], "worker-a", claim["lease_token"],
                                        paths, True, "ci://run/4")
        self.assertEqual(self.store.get(job["id"])["status"], "leased")


    def test_summary_reports_active_expired_leases_and_latest_validation(self):
        active = self.store.create("Active lease", scope=["backend/active.py"])
        claim = self.store.claim_ready("worker-a")
        completed = self.store.create("Completed work", scope=["backend/done.py"])
        done_claim = self.store.claim_ready("worker-b")
        self._prepare(completed["id"], "worker-b", done_claim["lease_token"],
                      ["backend/done.py"], True, "ci://run/42")
        self._publish(["backend/done.py"])
        expired = self.store.create("Expired lease", scope=["backend/expired.py"])
        expired_claim = self.store.claim_ready("worker-c")
        with self.store.db() as connection:
            connection.execute(
                "UPDATE development_jobs SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",
                (expired["id"],),
            )
        summary = self.store.summary()
        self.assertEqual(summary["active_leases"], 1)
        self.assertEqual(summary["expired_leases"], 1)
        self.assertEqual(summary["latest_validation_ref"], "ci://run/42")
        self.assertTrue(summary["latest_updated_at"])


    def test_worker_presence_lifecycle_and_summary(self):
        worker = self.store.touch_worker("runner-a", hostname="WINNER", current_job_id="DEV-1")
        self.assertEqual(worker["status"], "online")
        self.assertEqual(worker["hostname"], "WINNER")
        self.assertEqual(worker["current_job_id"], "DEV-1")
        listed = self.store.list_workers()
        self.assertEqual(len(listed), 1)
        self.assertTrue(listed[0]["is_online"])
        self.assertEqual(self.store.summary()["online_workers"], 1)
        self.assertTrue(self.store.stop_worker("runner-a"))
        stopped = self.store.get_worker("runner-a")
        self.assertEqual(stopped["status"], "offline")
        self.assertIsNone(stopped["current_job_id"])
        self.assertEqual(self.store.summary()["online_workers"], 0)

    def test_worker_presence_rejects_invalid_identity(self):
        with self.assertRaises(ValueError):
            self.store.touch_worker("")
        with self.assertRaises(ValueError):
            self.store.list_workers(online_within_seconds=0)



if __name__ == "__main__":
    unittest.main()
