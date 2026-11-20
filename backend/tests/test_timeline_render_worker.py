import tempfile
import unittest
from pathlib import Path

from queue_store import JobQueue
from timeline_render_worker import TimelineRenderWorker
from render_artifact_store import RenderArtifactStore


class TimelineRenderWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.queue = JobQueue(Path(self.temp.name) / "queue.sqlite3", lease_seconds=10)
        self.generation = self.queue.register_worker("timeline-worker")["generation_token"]

    def tearDown(self):
        self.temp.cleanup()

    def test_consumes_timeline_job_and_finishes_in_review_pending(self):
        queued = self.queue.enqueue(
            "timeline_render",
            {"snapshot_id": "edl_fixture", "snapshot_sha256": "a" * 64, "edl": {}},
            workspace_id="ws_fixture",
        )
        worker = TimelineRenderWorker(
            self.queue, lambda payload, stop_event: {"artifact_id": "private-output"},
            "timeline-worker", self.generation, heartbeat_seconds=0.02,
        )
        self.assertTrue(worker.run_once())
        finished = self.queue.get(queued["id"], workspace_id="ws_fixture")
        self.assertEqual(finished["status"], "review_pending")
        self.assertEqual(finished["worker_id"], None)

    def test_renderer_failure_is_recorded_as_retryable(self):
        queued = self.queue.enqueue("timeline_render", {
            "snapshot_id": "edl_failure", "snapshot_sha256": "b" * 64, "edl": {}
        }, workspace_id="ws_fixture")
        def fail(payload, stop_event):
            raise RuntimeError("fixture render failure")
        worker = TimelineRenderWorker(
            self.queue, fail, "timeline-worker", self.generation,
            heartbeat_seconds=0.02,
        )
        self.assertFalse(worker.run_once())
        failed = self.queue.get(queued["id"], workspace_id="ws_fixture")
        self.assertEqual(failed["status"], "failed_retriable")
        self.assertEqual(failed["error_code"], "timeline_render_failed")


    def test_worker_atomically_adopts_artifact_and_hands_off_for_review(self):
        root = Path(self.temp.name)
        staging = root / "staging"
        artifacts = root / "artifacts"
        staging.mkdir()
        store = RenderArtifactStore(self.queue, staging, artifacts)
        def render(payload, stop_event):
            output = staging / "result.mp4"
            output.write_bytes(b"realistic-fixture-bytes")
            return {"staged_path": str(output)}
        queued = self.queue.enqueue(
            "timeline_render",
            {"snapshot_id": "edl_" + "a" * 32,
             "snapshot_sha256": "c" * 64, "edl": {}},
            workspace_id="ws_fixture",
        )
        worker = TimelineRenderWorker(
            self.queue, render, "timeline-worker", self.generation,
            heartbeat_seconds=0.02, artifact_store=store,
        )
        self.assertTrue(worker.run_once())
        finished = self.queue.get(queued["id"], workspace_id="ws_fixture")
        self.assertEqual(finished["status"], "review_pending")
        self.assertIsNone(finished["lease_token"])
        with self.queue.db() as db:
            artifact = db.execute(
                "SELECT * FROM render_artifacts WHERE job_id=?", (queued["id"],)
            ).fetchone()
            events = db.execute(
                "SELECT event_type,to_status FROM job_events WHERE job_id=? ORDER BY id",
                (queued["id"],),
            ).fetchall()
        self.assertIsNotNone(artifact)
        self.assertEqual(events[-1]["event_type"], "completed")
        self.assertEqual(events[-1]["to_status"], "review_pending")
        self.assertTrue((artifacts / artifact["storage_key"]).is_file())


    def test_discards_staged_output_when_renderer_reports_lost_lease(self):
        root = Path(self.temp.name)
        staging = root / "staging"
        artifacts = root / "artifacts"
        staging.mkdir()
        store = RenderArtifactStore(self.queue, staging, artifacts)
        staged = staging / "abandoned.mp4"

        def lose_lease(payload, stop_event):
            staged.write_bytes(b"orphan-render")
            stop_event.set()
            return {"staged_path": str(staged)}

        queued = self.queue.enqueue(
            "timeline_render",
            {"snapshot_id": "edl_" + "d" * 32,
             "snapshot_sha256": "e" * 64, "edl": {}},
            workspace_id="ws_fixture",
        )
        worker = TimelineRenderWorker(
            self.queue, lose_lease, "timeline-worker", self.generation,
            heartbeat_seconds=0.02, artifact_store=store,
        )
        self.assertFalse(worker.run_once())
        self.assertFalse(staged.exists())
        with self.queue.db() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM render_artifacts WHERE job_id=?",
                           (queued["id"],)).fetchone()[0],
                0,
            )


if __name__ == "__main__":
    unittest.main()
