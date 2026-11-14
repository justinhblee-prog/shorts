import tempfile
import unittest
from pathlib import Path

from production_pipeline import (
    JsonProvider, ProductionPipeline, ProductionStore, ProviderError,
    submit_production,
)
from queue_store import JobQueue


class FakeProvider:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, stage, payload):
        self.calls.append((stage, payload))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class FakeQueue:
    def __init__(self):
        self.job = None

    def enqueue(self, job_type, payload, channel_name=None, idempotency_key=None):
        if self.job is None:
            self.job = {"id": "job-1", "job_type": job_type, "payload": payload,
                        "channel_name": channel_name, "status": "queued"}
        return self.job


class ProductionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ProductionStore(str(Path(self.tmp.name) / "test.sqlite3"))
        self.brief = {"brand": "Future Leak", "region": "US",
                      "language": "en", "topic": "AI agents"}

    def tearDown(self):
        self.tmp.cleanup()

    def test_submit_is_durable_and_does_not_call_providers(self):
        queue = FakeQueue()
        result = submit_production(queue, self.store, self.brief)
        self.assertEqual(result["job"]["status"], "queued")
        self.assertEqual(result["production"]["status"], "queued")
        self.assertEqual(result["production"]["artifacts"], [])

    def test_pipeline_runs_script_voice_render_and_waits_for_review(self):
        script = FakeProvider({"script": "Hook. Evidence. Takeaway."})
        voice = FakeProvider({"audio_url": "https://media.example/audio.mp3", "voice": "en-US"})
        render = FakeProvider({"video_url": "https://media.example/video.mp4", "duration_seconds": 28})
        pipeline = ProductionPipeline(self.store, script, voice, render)
        self.store.create("job-1", self.brief)
        result = pipeline.execute("job-1", self.brief)
        self.assertEqual(result["status"], "rendered")
        self.assertEqual([a["stage"] for a in result["artifacts"]],
                         ["script", "voice_generation", "rendering"])
        self.assertIsNone(result["artifacts"][0]["artifact_url"])
        self.assertEqual(len(script.calls), 1)
        self.assertEqual(len(voice.calls), 1)
        self.assertEqual(len(render.calls), 1)

    def test_missing_audio_url_fails_without_fake_video(self):
        script = FakeProvider({"script": "Real script"})
        voice = FakeProvider({"status": "ok"})
        render = FakeProvider({"video_url": "https://media.example/never.mp4"})
        pipeline = ProductionPipeline(self.store, script, voice, render)
        self.store.create("job-1", self.brief)
        with self.assertRaises(ProviderError) as caught:
            pipeline.execute("job-1", self.brief)
        self.assertEqual(caught.exception.stage, "voice_generation")
        result = self.store.get("job-1")
        self.assertEqual(result["status"], "failed_terminal")
        self.assertEqual(len(result["artifacts"]), 1)
        self.assertEqual(render.calls, [])

    def test_missing_provider_url_fails_closed(self):
        provider = JsonProvider("")
        with self.assertRaises(ProviderError) as caught:
            provider.post("script", {"topic": "test"})
        self.assertFalse(caught.exception.retryable)

    def test_queue_claim_filters_by_job_type(self):
        queue = JobQueue(str(Path(self.tmp.name) / "queue.sqlite3"))
        queue.enqueue("unrelated_task", {}, idempotency_key="other")
        queue.enqueue("short_video_production", self.brief, idempotency_key="video")
        claimed = queue.claim("worker-1", job_type="short_video_production")
        self.assertEqual(claimed["job_type"], "short_video_production")
        self.assertEqual(queue.get(claimed["id"])["status"], "running")

    def test_invalid_brief_rejected(self):
        with self.assertRaises(ValueError):
            ProductionPipeline.validate_brief({"brand": "x", "region": "US",
                                                "language": "en", "topic": ""})


if __name__ == "__main__":
    unittest.main()
