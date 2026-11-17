import os
import tempfile
import unittest

from development_jobs import (
    DevelopmentJobConflict, DevelopmentJobNotFound, DevelopmentJobStore,
)


class DevelopmentJobStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = DevelopmentJobStore(os.path.join(self.tmp.name, "jobs.sqlite3"), lease_seconds=30)

    def tearDown(self):
        self.tmp.cleanup()

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
        parent = self.store.create("Parent")
        child = self.store.create("Child")
        self.store.add_dependency(child["id"], parent["id"])
        self.assertEqual(self.store.get(child["id"])["status"], "blocked")
        claim = self.store.claim_ready("worker-a")
        self.assertEqual(claim["id"], parent["id"])
        self.store.heartbeat(parent["id"], "worker-a", claim["lease_token"])
        self.store.complete(parent["id"], "worker-a", claim["lease_token"],
                            ["backend/module.py"], True, "ci://run/123")
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
            self.store.complete(job["id"], "worker-a", claim["lease_token"],
                                [], True, "ci://run/1")
        with self.assertRaisesRegex(ValueError, "tests_passed"):
            self.store.complete(job["id"], "worker-a", claim["lease_token"],
                                ["backend/file.py"], False, "ci://run/1")
        self.assertEqual(self.store.get(job["id"])["status"], "leased")

    def test_completion_requires_evidence_and_valid_fence(self):
        job = self.store.create("Completion")
        claim = self.store.claim_ready("worker-a")
        with self.assertRaisesRegex(ValueError, "validation evidence"):
            self.store.complete(job["id"], "worker-a", claim["lease_token"],
                                ["backend/file.py"], True, "")
        with self.assertRaises(DevelopmentJobConflict):
            self.store.complete(job["id"], "worker-b", claim["lease_token"],
                                ["backend/file.py"], True, "ci://run/2")
        completed = self.store.complete(job["id"], "worker-a", claim["lease_token"],
                                        ["backend/file.py"], True, "ci://run/2")
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["changed_files"], ["backend/file.py"])
        self.assertTrue(completed["tests_passed"])

    def test_event_history_is_append_only(self):
        job = self.store.create("Audit")
        with self.store.db() as connection:
            event_id = connection.execute(
                "SELECT id FROM development_job_events WHERE job_id=? LIMIT 1",
                (job["id"],),
            ).fetchone()["id"]
            with self.assertRaisesRegex(self.store.__class__.__module__ and Exception,
                                        "development job events are immutable"):
                connection.execute("UPDATE development_job_events SET actor='tampered' WHERE id=?",
                                   (event_id,))

    def test_parallel_workers_claim_distinct_jobs(self):
        from concurrent.futures import ThreadPoolExecutor
        jobs = [self.store.create("Job " + str(i)) for i in range(4)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            claimed = list(pool.map(lambda i: self.store.claim_ready("worker-" + str(i)), range(4)))
        ids = [item["id"] for item in claimed if item]
        self.assertEqual(len(ids), 4)
        self.assertEqual(len(set(ids)), 4)


if __name__ == "__main__":
    unittest.main()
