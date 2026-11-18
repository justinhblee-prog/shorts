import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from development_jobs import DevelopmentJobStore
from seed_development_jobs import seed_development_jobs


class SeedDevelopmentJobsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = DevelopmentJobStore(os.path.join(self.tmp.name, "jobs.sqlite3"))

    def tearDown(self):
        self.tmp.cleanup()

    def _prepare(self, job_id, worker_id, lease_token, files, validation_ref):
        artifact = Path(self.tmp.name) / ("artifact-" + hashlib.sha256(job_id.encode("utf-8")).hexdigest() + ".zip")
        artifact.write_bytes(job_id.encode("utf-8"))
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        return self.store.prepare_review(
            job_id, worker_id, lease_token, files, True, validation_ref, str(artifact), digest,
        )

    def _publish(self, files):
        sha = "d" * 40
        return self.store.publish_review(
            "https://github.com/acme/app/pull/456", sha, files, expected_head_sha=sha,
        )

    def test_seed_is_idempotent_and_preserves_existing_progress(self):
        first = seed_development_jobs(self.store)
        self.assertEqual(len(first), 4)
        initial_dependency_events = len(self.store.events("DEV-ORCH-009"))
        claimed = self.store.claim_ready("seed-test-worker")
        self.assertEqual(claimed["id"], "DEV-ORCH-005")
        second = seed_development_jobs(self.store)
        self.assertEqual([job["id"] for job in second],
                         ["DEV-ORCH-005", "DEV-ORCH-007", "DEV-ORCH-009", "DEV-ORCH-010"])
        self.assertEqual(self.store.get("DEV-ORCH-005")["worker_id"], "seed-test-worker")
        self.assertEqual(self.store.get("DEV-ORCH-009")["status"], "blocked")
        self.assertEqual(self.store.get("DEV-ORCH-010")["status"], "blocked")
        self.assertEqual(self.store.get("DEV-ORCH-009")["scope"], [
            ".github/workflows/nexus-development-job-worker.yml",
            "backend/run_development_agent.py",
            "backend/development_backlog_service.py",
            "backend/tests/test_development_worker_workflow_contract.py",
        ])
        self.assertEqual(self.store.get("DEV-ORCH-010")["scope"], [
            ".github/workflows/nexus-development-job-worker.yml",
            "backend/development_job_worker.py",
        ])
        self.assertEqual(len(self.store.events("DEV-ORCH-009")), initial_dependency_events)

    def test_dependency_chain_unlocks_only_after_all_prerequisites_complete(self):
        seed_development_jobs(self.store)
        first = self.store.claim_ready("worker-a")
        self._prepare(first["id"], "worker-a", first["lease_token"],
                      ["backend/development_jobs.py"], "ci://run/1")
        self._publish(["backend/development_jobs.py"])
        second = self.store.claim_ready("worker-b")
        self.store.complete(second["id"], "worker-b", second["lease_token"],
                            ["backend/development_github_intake.py"], True, "ci://run/2")
        third = self.store.claim_ready("worker-c")
        self.assertEqual(third["id"], "DEV-ORCH-009")
        self.assertEqual(self.store.get("DEV-ORCH-010")["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
