import tempfile
import unittest
from pathlib import Path

from queue_store import JobQueue
from timeline_render_worker import TimelineRenderWorker


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


if __name__ == "__main__":
    unittest.main()
