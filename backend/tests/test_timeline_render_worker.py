import tempfile
import unittest
from pathlib import Path

from queue_store import JobQueue
from timeline_render_worker import TimelineRenderWorker, create_edl_render_worker
from ffmpeg_edl_renderer import EDLFFmpegRenderer
from render_artifact_store import RenderArtifactStore


class TimelineRenderWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.queue = JobQueue(Path(self.temp.name) / "queue.sqlite3", lease_seconds=10)
        self.generation = self.queue.register_worker("timeline-worker")["generation_token"]

    def tearDown(self):
        self.temp.cleanup()

    def test_factory_wires_edl_renderer_and_requires_artifact_store(self):
        root = Path(self.temp.name)
        binary = root / "ffmpeg"
        binary.write_bytes(b"fixture binary")
        staging = root / "staging"
        artifacts = root / "artifacts"
        store = RenderArtifactStore(self.queue, staging, artifacts)
        class AssetResolver:
            def resolve_clean_asset_path(self, workspace_id, principal_id, asset_id):
                return root / "source.mp4"
        (root / "source.mp4").write_bytes(b"fixture source")
        worker = create_edl_render_worker(
            self.queue, AssetResolver(), "timeline-worker", self.generation,
            staging, binary, store, heartbeat_seconds=0.02,
        )
        self.assertIsInstance(worker.renderer, EDLFFmpegRenderer)
        self.assertIs(worker.artifact_store, store)
        with self.assertRaisesRegex(ValueError, "artifact_store is required"):
            create_edl_render_worker(
                self.queue, AssetResolver(), "timeline-worker", self.generation,
                staging, binary, None,
            )
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


    def test_shutdown_cancels_active_renderer_and_requeues_job(self):
        import threading
        queued = self.queue.enqueue(
            "timeline_render",
            {"snapshot_id": "edl_shutdown", "snapshot_sha256": "d" * 64, "edl": {}},
            workspace_id="ws_fixture",
        )
        shutdown = threading.Event()

        def render(payload, stop_event):
            shutdown.set()
            self.assertTrue(stop_event.wait(2))
            raise RuntimeError("renderer observed cancellation")

        worker = TimelineRenderWorker(
            self.queue, render, "timeline-worker", self.generation,
            heartbeat_seconds=0.02, shutdown_event=shutdown,
        )
        self.assertFalse(worker.run_once())
        finished = self.queue.get(queued["id"], workspace_id="ws_fixture")
        self.assertEqual(finished["status"], "failed_retriable")
        self.assertEqual(finished["error_code"], "timeline_worker_shutdown")

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

    def test_graceful_shutdown_cancels_and_discards_unadopted_output(self):
        root = Path(self.temp.name)
        staging = root / "staging"
        artifacts = root / "artifacts"
        staging.mkdir()
        store = RenderArtifactStore(self.queue, staging, artifacts)
        shutdown = __import__("threading").Event()
        staged = staging / "shutdown.mp4"

        def render(payload, stop_event):
            staged.write_bytes(b"shutdown-render")
            shutdown.set()
            if not stop_event.wait(1):
                raise AssertionError("worker did not propagate shutdown to renderer")
            return {"staged_path": str(staged)}

        queued = self.queue.enqueue(
            "timeline_render",
            {"snapshot_id": "edl_" + "f" * 32,
             "snapshot_sha256": "1" * 64, "edl": {}},
            workspace_id="ws_fixture",
        )
        worker = TimelineRenderWorker(
            self.queue, render, "timeline-worker", self.generation,
            heartbeat_seconds=0.02, artifact_store=store,
            shutdown_event=shutdown,
        )
        self.assertFalse(worker.run_once())
        self.assertFalse(staged.exists())
        with self.queue.db() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM render_artifacts WHERE job_id=?",
                           (queued["id"],)).fetchone()[0],
                0,
            )

    def test_resolves_legacy_job_creator_from_immutable_snapshot_owner(self):
        queued = self.queue.enqueue(
            "timeline_render",
            {"snapshot_id": "edl_" + "9" * 32,
             "snapshot_sha256": "a" * 64, "edl": {}},
            workspace_id="ws_fixture",
        )
        seen = []

        def render(payload, stop_event, workspace_id, principal_id):
            seen.append((workspace_id, principal_id))
            return {"rendered": True}

        worker = TimelineRenderWorker(
            self.queue, render, "timeline-worker", self.generation,
            heartbeat_seconds=0.02,
            principal_resolver=lambda workspace_id, payload: "alice",
        )
        self.assertTrue(worker.run_once())
        self.assertEqual(seen, [("ws_fixture", "alice")])

    def test_rejects_creator_identity_conflicting_with_snapshot_owner(self):
        queued = self.queue.enqueue(
            "timeline_render",
            {"snapshot_id": "edl_" + "8" * 32,
             "snapshot_sha256": "b" * 64, "creator_principal_id": "mallory",
             "edl": {}},
            workspace_id="ws_fixture",
        )
        invoked = []

        def render(payload, stop_event, workspace_id, principal_id):
            invoked.append(principal_id)
            return {"rendered": True}

        worker = TimelineRenderWorker(
            self.queue, render, "timeline-worker", self.generation,
            heartbeat_seconds=0.02,
            principal_resolver=lambda workspace_id, payload: "alice",
        )
        self.assertFalse(worker.run_once())
        self.assertEqual(invoked, [])
        failed = self.queue.get(queued["id"], workspace_id="ws_fixture")
        self.assertEqual(failed["status"], "failed_retriable")


    def test_heartbeat_lease_loss_cancels_renderer_and_discards_late_staged_output(self):
        import threading

        root = Path(self.temp.name)
        staging = root / "lease-loss-staging"
        artifacts = root / "lease-loss-artifacts"
        staging.mkdir()
        store = RenderArtifactStore(self.queue, staging, artifacts)
        heartbeat_failed = threading.Event()
        staged = staging / "late-output.mp4"

        class LeaseLossQueue:
            def __init__(self, delegate):
                self.delegate = delegate

            def __getattr__(self, name):
                return getattr(self.delegate, name)

            def heartbeat(self, *args, **kwargs):
                heartbeat_failed.set()
                raise RuntimeError("simulated generation/lease fence rejection")

        def render(payload, stop_event):
            self.assertTrue(heartbeat_failed.wait(2), "heartbeat monitor did not run")
            self.assertTrue(stop_event.wait(2), "lease loss was not propagated to renderer")
            # Simulate a renderer that finishes writing at the cancellation boundary.
            staged.write_bytes(b"late-output-after-lease-loss")
            return {"staged_path": str(staged)}

        queued = self.queue.enqueue(
            "timeline_render",
            {"snapshot_id": "edl_" + "7" * 32,
             "snapshot_sha256": "f" * 64, "edl": {}},
            workspace_id="ws_fixture",
        )
        worker = TimelineRenderWorker(
            LeaseLossQueue(self.queue), render, "timeline-worker", self.generation,
            heartbeat_seconds=0.01, artifact_store=store,
        )

        self.assertFalse(worker.run_once())
        self.assertFalse(staged.exists(), "unadopted output must be discarded after heartbeat lease loss")
        self.assertFalse(artifacts.exists() and any(artifacts.iterdir()))
        with self.queue.db() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM render_artifacts WHERE job_id=?",
                           (queued["id"],)).fetchone()[0],
                0,
            )
        # The stale worker must not mutate the queue after its lease fence is rejected.
        current = self.queue.get(queued["id"], workspace_id="ws_fixture")
        self.assertEqual(current["status"], "running")


if __name__ == "__main__":
    unittest.main()
