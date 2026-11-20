"""Crash/restart and lease-loss recovery tests for timeline render workers."""
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

from queue_store import JobQueue
from render_artifact_store import RenderArtifactStore
from timeline_render_worker import TimelineRenderWorker


class TimelineRenderRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.queue = JobQueue(self.root / "queue.sqlite3", lease_seconds=10)
        self.worker_id = "timeline-recovery-worker"
        self.generation = self.queue.register_worker(self.worker_id)["generation_token"]
        self.staging = self.root / "staging"
        self.artifacts = self.root / "artifacts"
        self.store = RenderArtifactStore(self.queue, self.staging, self.artifacts)

    def tearDown(self):
        self.temp.cleanup()

    def test_lease_loss_cancels_render_discards_output_and_allows_reclaim(self):
        queued = self.queue.enqueue(
            "timeline_render",
            {
                "snapshot_id": "edl_" + "a" * 32,
                "snapshot_sha256": "a" * 64,
                "edl": {},
            },
            workspace_id="ws_recovery",
            max_attempts=3,
        )
        render_started = threading.Event()
        replacement_generation = {}

        def replace_worker_generation():
            self.assertTrue(render_started.wait(3), "renderer did not start")
            replacement_generation["token"] = self.queue.register_worker(
                self.worker_id
            )["generation_token"]

        replacement = threading.Thread(
            target=replace_worker_generation, daemon=True
        )
        replacement.start()
        staged = self.staging / ("render_" + "b" * 32 + ".mp4")

        def render(payload, stop_event):
            staged.write_bytes(b"crash-left-render-output")
            render_started.set()
            self.assertTrue(
                stop_event.wait(3),
                "worker did not cancel the renderer after losing its generation",
            )
            return {"staged_path": str(staged)}

        worker = TimelineRenderWorker(
            self.queue,
            render,
            self.worker_id,
            self.generation,
            heartbeat_seconds=0.02,
            artifact_store=self.store,
        )
        self.assertFalse(worker.run_once())
        replacement.join(timeout=3)
        self.assertFalse(replacement.is_alive())
        self.assertIn("token", replacement_generation)
        self.assertFalse(staged.exists(), "stale worker output must be discarded")
        self.assertEqual(list(self.artifacts.iterdir()), [])

        # Simulate process death after lease loss: recovery, not the stale
        # worker, owns the transition back to the runnable queue.
        with self.queue.db() as db:
            db.execute(
                "UPDATE pipeline_jobs SET lease_expires_at=? WHERE id=?",
                ("2000-01-01T00:00:00+00:00", queued["id"]),
            )
        recovered = self.queue.recover()
        self.assertEqual(recovered["requeued"], 1)
        current = self.queue.get(queued["id"], workspace_id="ws_recovery")
        self.assertEqual(current["status"], "queued")
        self.assertEqual(current["error_code"], "lease_expired")
        reclaimed = self.queue.claim(
            self.worker_id,
            job_type="timeline_render",
            generation_token=replacement_generation["token"],
            workspace_id="ws_recovery",
        )
        self.assertIsNotNone(reclaimed)
        self.assertEqual(reclaimed["id"], queued["id"])
        self.assertEqual(reclaimed["attempt"], 2)

    def test_staging_reconciliation_removes_only_expired_generated_outputs(self):
        self.staging.mkdir(parents=True, exist_ok=True)
        old_output = self.staging / ("render_" + "c" * 32 + ".mp4")
        old_output.write_bytes(b"orphan output")
        old_job_dir = self.staging / (".render-" + "d" * 32)
        old_job_dir.mkdir()
        (old_job_dir / "intermediate.tmp").write_bytes(b"orphan intermediate")
        unrelated = self.staging / "user-notes.txt"
        unrelated.write_text("preserve", encoding="utf-8")
        fresh_output = self.staging / ("render_" + "e" * 32 + ".mp4")
        fresh_output.write_bytes(b"active output")

        old_time = time.time() - 8000
        os.utime(old_output, (old_time, old_time))
        os.utime(old_job_dir, (old_time, old_time))
        result = self.store.reconcile_orphaned_staging(grace_seconds=7200)

        self.assertEqual(result["removed_files"], 1)
        self.assertEqual(result["removed_directories"], 1)
        self.assertGreaterEqual(result["removed_bytes"], len(b"orphan output"))
        self.assertFalse(old_output.exists())
        self.assertFalse(old_job_dir.exists())
        self.assertTrue(unrelated.exists())
        self.assertTrue(fresh_output.exists())

    def test_staging_reconciliation_enforces_render_timeout_grace(self):
        with self.assertRaisesRegex(ValueError, "at least 7200"):
            self.store.reconcile_orphaned_staging(grace_seconds=7199)


if __name__ == "__main__":
    unittest.main()
