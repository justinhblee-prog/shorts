import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import render_worker
from queue_store import LeaseConflict
from render_asset_store import RenderAssetError
from render_output_store import RenderOutputLeaseConflict
from timeline_renderer import TimelineRenderCancelled
from timeline_edl import SCHEMA


def job_payload(audio_asset_id=None):
    return {
        "edl": {
            "schema": SCHEMA, "version": 1, "timebase": "milliseconds",
            "clips": [{
                "id": "clip-1", "type": "video", "start_ms": 0, "end_ms": 1000,
                "asset_id": "a" * 32, "source_in_ms": 0, "source_out_ms": 1000,
            }],
        },
        "audio_asset_id": audio_asset_id,
    }


def claimed_job(audio_asset_id=None):
    return {
        "id": str(uuid4()),
        "job_type": "timeline_render",
        "workspace_id": "workspace-a",
        "payload": job_payload(audio_asset_id),
        "lease_token": "lease-secret",
        "attempt": 1,
    }


class FakeQueue:
    def __init__(self, job, heartbeat_error=None):
        self.job = job
        self.heartbeat_error = heartbeat_error
        self.claim_calls = []
        self.heartbeat_calls = []
        self.finish_calls = []
        self.fail_calls = []

    def claim(self, *args, **kwargs):
        self.claim_calls.append((args, kwargs))
        return self.job

    def heartbeat(self, *args, **kwargs):
        self.heartbeat_calls.append((args, kwargs))
        if self.heartbeat_error:
            raise self.heartbeat_error

    def finish(self, *args, **kwargs):
        self.finish_calls.append((args, kwargs))

    def fail(self, *args, **kwargs):
        self.fail_calls.append((args, kwargs))


class FakeAssetStore:
    def __init__(self, error=None):
        self.error = error
        self.resolve_calls = []
        self.output_dir = Path("/tmp/render-output")

    def resolve_asset_paths(self, workspace_id, asset_ids, **kwargs):
        self.resolve_calls.append((workspace_id, asset_ids, kwargs))
        if self.error:
            raise self.error
        return {asset_id: Path("/tmp/" + asset_id) for asset_id in asset_ids}

    def workspace_render_output_dir(self, workspace_id):
        return self.output_dir


class FakeRenderer:
    def __init__(self, result=None, error=None, wait_for_stop=False):
        self.result = result or {
            "render_id": "b" * 32, "sha256": "c" * 64,
            "size_bytes": 100, "duration_seconds": 1.0,
            "width": 1080, "height": 1920,
            "audio_track_present": False, "media_path": "renders/out.mp4",
        }
        self.error = error
        self.wait_for_stop = wait_for_stop
        self.called = threading.Event()
        self.stop_seen = threading.Event()
        self.calls = []

    def render(self, edl, asset_paths, **kwargs):
        self.calls.append((edl, asset_paths, kwargs))
        self.called.set()
        stop_event = kwargs.get("stop_event")
        if self.wait_for_stop and stop_event is not None:
            stop_event.wait(2)
            self.stop_seen.set()
        if self.error:
            raise self.error
        return self.result


class FakeOutputStore:
    def __init__(self, error=None):
        self.error = error
        self.adopt_calls = []

    def adopt(self, *args):
        self.adopt_calls.append(args)
        if self.error:
            raise self.error
        return {
            "render_id": "b" * 32, "sha256": "c" * 64,
            "size_bytes": 100, "duration_seconds": 1.0,
            "width": 1080, "height": 1920,
            "audio_track_present": False, "review_status": "pending",
        }


class RenderWorkerTests(unittest.TestCase):
    def setUp(self):
        self.originals = {
            "queue": render_worker.queue,
            "asset_store": render_worker.asset_store,
            "output_store": render_worker.output_store,
            "renderer": render_worker.renderer,
            "worker_id": render_worker.WORKER_ID,
            "generation": render_worker.WORKER_GENERATION_TOKEN,
            "heartbeat": render_worker.HEARTBEAT_SECONDS,
        }
        render_worker.WORKER_ID = "render-worker-test"
        render_worker.WORKER_GENERATION_TOKEN = "generation-test"
        render_worker.HEARTBEAT_SECONDS = 3600
        render_worker.stopping.clear()

    def tearDown(self):
        render_worker.queue = self.originals["queue"]
        render_worker.asset_store = self.originals["asset_store"]
        render_worker.output_store = self.originals["output_store"]
        render_worker.renderer = self.originals["renderer"]
        render_worker.WORKER_ID = self.originals["worker_id"]
        render_worker.WORKER_GENERATION_TOKEN = self.originals["generation"]
        render_worker.HEARTBEAT_SECONDS = self.originals["heartbeat"]
        render_worker.stopping.clear()
        render_worker.active_job_id = None
        render_worker.active_stop_event = None

    def test_claims_only_render_jobs_and_hands_output_to_review(self):
        job = claimed_job()
        queue = FakeQueue(job)
        assets = FakeAssetStore()
        outputs = FakeOutputStore()
        renderer = FakeRenderer()
        render_worker.queue, render_worker.asset_store = queue, assets
        render_worker.output_store, render_worker.renderer = outputs, renderer

        self.assertTrue(render_worker.run_once())
        self.assertEqual(queue.claim_calls[0][1]["job_type"], "timeline_render")
        self.assertEqual(queue.finish_calls[0][0][0], job["id"])
        self.assertEqual(queue.finish_calls[0][1]["workspace_id"], "workspace-a")
        self.assertEqual(queue.finish_calls[0][0][3]["review_status"], "pending")
        self.assertEqual(outputs.adopt_calls[0][2], "render-worker-test")
        self.assertEqual(assets.resolve_calls[0][2]["expected_asset_type"], "video")

    def test_resolves_optional_audio_inside_same_workspace(self):
        job = claimed_job(audio_asset_id="d" * 32)
        queue, assets, outputs, renderer = FakeQueue(job), FakeAssetStore(), FakeOutputStore(), FakeRenderer()
        render_worker.queue, render_worker.asset_store = queue, assets
        render_worker.output_store, render_worker.renderer = outputs, renderer
        render_worker.run_once()
        self.assertEqual(len(assets.resolve_calls), 2)
        self.assertEqual(assets.resolve_calls[1][0], "workspace-a")
        self.assertEqual(assets.resolve_calls[1][2]["expected_asset_type"], "audio")
        self.assertEqual(renderer.calls[0][2]["audio_asset_id"], "d" * 32)

    def test_validation_failure_is_terminal_and_never_finishes_job(self):
        job = claimed_job()
        queue, assets, outputs, renderer = (
            FakeQueue(job), FakeAssetStore(RenderAssetError("asset unavailable")),
            FakeOutputStore(), FakeRenderer(),
        )
        render_worker.queue, render_worker.asset_store = queue, assets
        render_worker.output_store, render_worker.renderer = outputs, renderer
        render_worker.run_once()
        self.assertEqual(queue.fail_calls[0][0][3], "render_validation_failed")
        self.assertFalse(queue.fail_calls[0][0][5])
        self.assertEqual(queue.finish_calls, [])
        self.assertEqual(renderer.calls, [])

    def test_lost_lease_cancels_active_render_without_stale_completion(self):
        job = claimed_job()
        queue = FakeQueue(job, heartbeat_error=LeaseConflict("expired"))
        assets, outputs = FakeAssetStore(), FakeOutputStore()
        renderer = FakeRenderer(wait_for_stop=True)
        render_worker.queue, render_worker.asset_store = queue, assets
        render_worker.output_store, render_worker.renderer = outputs, renderer
        render_worker.HEARTBEAT_SECONDS = 0

        render_worker.run_once()

        self.assertTrue(renderer.called.is_set())
        self.assertTrue(renderer.stop_seen.is_set())
        self.assertEqual(queue.finish_calls, [])
        self.assertEqual(queue.fail_calls, [])

    def test_output_adoption_lease_conflict_never_finishes_job(self):
        job = claimed_job()
        queue, assets = FakeQueue(job), FakeAssetStore()
        outputs = FakeOutputStore(RenderOutputLeaseConflict("stale lease"))
        renderer = FakeRenderer()
        render_worker.queue, render_worker.asset_store = queue, assets
        render_worker.output_store, render_worker.renderer = outputs, renderer
        render_worker.run_once()
        self.assertEqual(queue.finish_calls, [])
        self.assertEqual(queue.fail_calls, [])


if __name__ == "__main__":
    unittest.main()
