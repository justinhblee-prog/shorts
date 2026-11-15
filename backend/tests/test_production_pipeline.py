import tempfile
import unittest
from pathlib import Path

from production_pipeline import (
    JsonProvider, ProductionPipeline, ProductionStore, ProductionLeaseConflict, ProviderError,
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

    def test_brand_profile_is_applied_to_script_voice_and_render_provider_payloads(self):
        profile = {
            "positioning": "Evidence-led AI explainers",
            "audience": "technology-curious adults",
            "tone": ["clear", "grounded"],
            "risk_level": "elevated",
            "review_rules": ["Distinguish demos from shipped capabilities"],
        }
        brief = {**self.brief, "brand_profile": profile}
        script = FakeProvider({"script": "Hook. Evidence. Takeaway."})
        voice = FakeProvider({"audio_url": "https://media.example/audio.mp3"})
        render = FakeProvider({"video_url": "https://media.example/video.mp4"})
        pipeline = ProductionPipeline(self.store, script, voice, render)
        self.store.create("job-brand-profile", brief)

        pipeline.execute("job-brand-profile", brief)

        script_payload = script.calls[0][1]
        voice_payload = voice.calls[0][1]
        render_payload = render.calls[0][1]
        self.assertEqual(script_payload["brand_profile"], profile)
        self.assertEqual(script_payload["editorial_constraints"], profile["review_rules"])
        self.assertEqual(voice_payload["voice_tone"], profile["tone"])
        self.assertEqual(voice_payload["target_audience"], profile["audience"])
        self.assertEqual(render_payload["brand_profile"], profile)

    def test_invalid_brand_profile_fails_before_provider_calls(self):
        script = FakeProvider({"script": "must not run"})
        voice = FakeProvider({"audio_url": "https://media.example/audio.mp3"})
        render = FakeProvider({"video_url": "https://media.example/video.mp4"})
        pipeline = ProductionPipeline(self.store, script, voice, render)
        with self.assertRaisesRegex(ValueError, "brand_profile.risk_level"):
            pipeline.validate_brief({**self.brief, "brand_profile": {"risk_level": "unknown"}})
        self.assertEqual(script.calls, [])
        self.assertEqual(voice.calls, [])
        self.assertEqual(render.calls, [])

    def test_retry_start_clears_stale_downstream_artifacts(self):
        self.store.create("job-1", self.brief)
        first = ProductionPipeline(
            self.store,
            FakeProvider({"script": "Old script"}),
            FakeProvider({"audio_url": "https://media.example/old.mp3"}),
            FakeProvider({"video_url": "https://media.example/old.mp4"}),
        )
        first.execute("job-1", self.brief)
        self.assertEqual(len(self.store.get("job-1")["artifacts"]), 3)

        retry = ProductionPipeline(
            self.store,
            FakeProvider(ProviderError("script", "Temporary script failure", True)),
            FakeProvider({"audio_url": "https://media.example/unused.mp3"}),
            FakeProvider({"video_url": "https://media.example/unused.mp4"}),
        )
        with self.assertRaises(ProviderError):
            retry.execute("job-1", self.brief)
        result = self.store.get("job-1")
        self.assertEqual(result["status"], "failed_retriable")
        self.assertEqual(result["artifacts"], [])

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

    def test_stale_worker_cannot_write_after_lease_is_reclaimed(self):
        db = self.store.db_path
        queue = JobQueue(db, lease_seconds=10)
        submitted = submit_production(queue, self.store, self.brief)
        job_id = submitted["job"]["id"]
        old_claim = queue.claim("worker-old", "host-old",
                                job_type="short_video_production")
        with queue.db() as connection:
            connection.execute(
                "UPDATE pipeline_jobs SET lease_expires_at=? WHERE id=?",
                ("2000-01-01T00:00:00+00:00", job_id)
            )
        new_claim = queue.claim("worker-new", "host-new",
                                job_type="short_video_production")
        self.assertEqual(new_claim["id"], job_id)
        self.assertNotEqual(old_claim["lease_token"], new_claim["lease_token"])

        script = FakeProvider({"script": "Fresh worker script"})
        voice = FakeProvider({"audio_url": "https://media.example/audio.mp3"})
        render = FakeProvider({"video_url": "https://media.example/video.mp4"})
        pipeline = ProductionPipeline(self.store, script, voice, render)

        with self.assertRaises(ProductionLeaseConflict):
            pipeline.execute(job_id, self.brief, worker_id="worker-old",
                             lease_token=old_claim["lease_token"])
        self.assertEqual(script.calls, [])
        self.assertEqual(self.store.get(job_id)["status"], "queued")

        with self.assertRaises(ProductionLeaseConflict):
            self.store.artifact(job_id, "rendering", "video",
                                "https://media.example/stale.mp4", {},
                                worker_id="worker-old",
                                lease_token=old_claim["lease_token"])

        fresh = pipeline.execute(job_id, self.brief, worker_id="worker-new",
                                 lease_token=new_claim["lease_token"])
        self.assertEqual(fresh["status"], "rendered")
        self.assertEqual(len(fresh["artifacts"]), 3)

    def test_queue_job_without_production_row_is_recovered_after_enqueue_crash(self):
        queue = JobQueue(self.store.db_path)
        job = queue.enqueue("short_video_production", self.brief,
                            idempotency_key="crash-window")
        self.assertIsNone(self.store.get(job["id"]))

        result = self.store.reconcile_missing_runs(queue)
        self.assertEqual(result["restored"], 1)
        self.assertEqual(result["job_ids"], [job["id"]])
        restored = self.store.get(job["id"])
        self.assertEqual(restored["status"], "queued")
        self.assertEqual(restored["topic"], self.brief["topic"])

        # Reconciliation is idempotent and does not replace an existing run.
        again = self.store.reconcile_missing_runs(queue)
        self.assertEqual(again["restored"], 0)
        self.assertEqual(self.store.get(job["id"])["status"], "queued")

    def test_recovery_can_target_a_job_claimed_during_enqueue_race(self):
        queue = JobQueue(self.store.db_path)
        job = queue.enqueue("short_video_production", self.brief)
        claimed = queue.claim("worker-race", "test-host",
                              job_type="short_video_production")
        self.assertEqual(claimed["id"], job["id"])

        result = self.store.reconcile_missing_runs(queue, job_ids=[claimed["id"]])
        self.assertEqual(result["restored"], 1)
        self.assertEqual(self.store.get(job["id"])["status"], "queued")

    def test_orphan_recovery_skips_non_object_payload_without_crashing(self):
        queue = JobQueue(self.store.db_path)
        job = queue.enqueue("short_video_production", ["not", "an", "object"])
        result = self.store.reconcile_missing_runs(queue)
        self.assertEqual(result["restored"], 0)
        self.assertEqual(result["invalid"], [job["id"]])
        self.assertIsNone(self.store.get(job["id"]))

    def test_worker_pause_mirrors_terminal_state_into_production_record(self):
        queue = JobQueue(self.store.db_path)
        submitted = submit_production(queue, self.store, self.brief)
        job_id = submitted["job"]["id"]
        queue.claim("worker-paused", job_type="short_video_production")

        queue.pause("provider result uncertain", job_id)

        job = queue.get(job_id)
        production = self.store.get(job_id)
        self.assertEqual(job["status"], "failed_terminal")
        self.assertEqual(job["error_code"], "worker_paused")
        self.assertEqual(production["status"], "failed_terminal")
        self.assertEqual(production["current_stage"], "worker_paused")

    def test_lost_worker_signal_stops_before_any_provider_call(self):
        import threading

        script = FakeProvider({"script": "must not run"})
        voice = FakeProvider({"audio_url": "https://media.example/audio.mp3"})
        render = FakeProvider({"video_url": "https://media.example/video.mp4"})
        pipeline = ProductionPipeline(self.store, script, voice, render)
        self.store.create("job-stop", self.brief)
        stop_event = threading.Event()
        stop_event.set()

        with self.assertRaises(ProductionLeaseConflict):
            pipeline.execute("job-stop", self.brief, stop_event=stop_event)

        self.assertEqual(script.calls, [])
        self.assertEqual(voice.calls, [])
        self.assertEqual(render.calls, [])

    def test_invalid_brief_rejected(self):
        with self.assertRaises(ValueError):
            ProductionPipeline.validate_brief({"brand": "x", "region": "US",
                                                "language": "en", "topic": ""})


if __name__ == "__main__":
    unittest.main()
