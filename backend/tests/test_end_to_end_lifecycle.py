"""End-to-end lifecycle contract test using explicitly mocked external providers.

This test validates integration and state transitions, not live AI/CDN/YouTube services.
"""
import os
import tempfile
import unittest
from pathlib import Path

from ledger import LedgerStore
from media_staging import MediaStager
from production_pipeline import ProductionPipeline, ProductionStore, submit_production
from queue_store import JobQueue
from review_workflow import ReviewStore
from youtube_publishing import YouTubePublisher, YouTubeUploadStore


class FakeProvider:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, stage, payload):
        self.calls.append((stage, payload))
        return dict(self.response)


class FakeUploadRequest:
    def __init__(self, response):
        self.response = response

    def next_chunk(self):
        return None, self.response


class FakeVideos:
    def __init__(self):
        self.upload_body = None
        self.media_body = None

    def insert(self, **kwargs):
        self.upload_body = kwargs["body"]
        self.media_body = kwargs["media_body"]
        return FakeUploadRequest({"id": "private-video-001"})

    def list(self, **kwargs):
        return type("Response", (), {"execute": lambda self: {
            "items": [{"statistics": {"viewCount": "10", "likeCount": "1",
                                      "commentCount": "0"},
                       "status": {"privacyStatus": "private"}}]
        }})()


class FakeYouTubeService:
    def __init__(self):
        self._videos = FakeVideos()

    def videos(self):
        return self._videos


class EndToEndLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = str(self.root / "nexus.sqlite3")
        self.media_dir = self.root / "media"
        self.previous_media = os.environ.get("NEXUS_MEDIA_DIR")
        os.environ["NEXUS_MEDIA_DIR"] = str(self.media_dir)

        self.queue = JobQueue(self.db, lease_seconds=90)
        self.production = ProductionStore(self.db)
        self.review = ReviewStore(self.db)
        self.uploads = YouTubeUploadStore(self.db)
        self.ledger = LedgerStore(self.db)

        self.script = FakeProvider({"script": "Verified hook. Evidence. Practical takeaway."})
        self.voice = FakeProvider({"audio_url": "https://cdn.example.test/audio.mp3",
                                   "provider": "test-voice"})
        self.render = FakeProvider({"video_url": "https://cdn.example.test/video.mp4",
                                    "duration_seconds": 27,
                                    "provider": "test-render"})
        self.pipeline = ProductionPipeline(self.production, self.script,
                                           self.voice, self.render)
        self.youtube = FakeYouTubeService()
        self.publisher = YouTubePublisher(self.uploads, self.youtube)

    def tearDown(self):
        if self.previous_media is None:
            os.environ.pop("NEXUS_MEDIA_DIR", None)
        else:
            os.environ["NEXUS_MEDIA_DIR"] = self.previous_media
        self.tmp.cleanup()

    def test_queued_job_to_review_private_upload_and_recorded_finance(self):
        brief = {"brand": "Brain Glitch", "region": "US",
                 "language": "English", "topic": "Sleep and memory",
                 "idempotency_key": "e2e-sleep-001",
                 "rights": {"visuals_cleared": True, "audio_cleared": True,
                            "likeness_authorized": True},
                 "synthetic_media_status": "none"}
        submitted = submit_production(self.queue, self.production, brief)
        job_id = submitted["job"]["id"]
        self.assertEqual(submitted["job"]["status"], "queued")

        claimed = self.queue.claim("integration-worker", "test-host",
                                   job_type="short_video_production")
        self.assertEqual(claimed["id"], job_id)
        generated = self.pipeline.execute(job_id, claimed["payload"],
                                             worker_id="integration-worker",
                                             lease_token=claimed["lease_token"])
        self.assertEqual(generated["status"], "rendered")
        self.assertEqual([a["artifact_type"] for a in generated["artifacts"]],
                         ["text", "report", "audio", "video", "report"])
        quality = next(a["metadata"] for a in generated["artifacts"]
                       if a["stage"] == "quality_check")
        self.assertEqual(quality["status"], "review_required")

        self.queue.finish(job_id, "integration-worker", claimed["lease_token"],
                          {"production_status": "review_pending"})
        self.production.stage(job_id, "review_pending", "review_pending")
        pending = self.review.list_pending()
        self.assertEqual([item["job_id"] for item in pending], [job_id])

        decision = self.review.decide(job_id, "approved", "human-reviewer",
                                      "Content and rights checked")
        self.assertEqual(decision["production"]["status"], "approved")
        self.assertEqual(len(self.review.history(job_id)), 1)

        mp4 = b"0000ftypisom" + b"mock-mp4-payload"
        stager = MediaStager(
            media_dir=str(self.media_dir),
            allowed_hosts="cdn.example.test",
            max_bytes=1024,
            resolver=lambda host: ["8.8.8.8"],
            fetcher=lambda host, ip, path, timeout: (
                200, {"content-type": "video/mp4",
                      "content-length": str(len(mp4))}, [mp4]),
        )
        video_artifact = next(item for item in generated["artifacts"]
                              if item["artifact_type"] == "video")
        staged = stager.stage(job_id, video_artifact["artifact_url"])
        self.assertTrue((self.media_dir / staged["media_path"]).is_file())
        # Manual staging happens after the first review decision. Persist the
        # byte fingerprint into the artifact and require a fresh human approval.
        updated_metadata=dict(video_artifact.get("metadata") or {})
        updated_metadata["media_staging"]=staged
        self.production.artifact(
            job_id,"rendering","video",video_artifact["artifact_url"],updated_metadata
        )
        self.review.reopen_for_review(
            job_id,"Media staging fingerprint changed; fresh human review required"
        )
        self.assertEqual(self.queue.get(job_id)["status"],"review_pending")
        self.review.decide(
            job_id,"approved","human-reviewer",
            "Re-reviewed exact staged media fingerprint and content"
        )

        uploaded = self.publisher.upload_approved(
            job_id, staged["media_path"], self.review,
            "Sleep and Memory: One Useful Fact", "Evidence-led short")
        self.assertEqual(uploaded["status"], "uploaded")
        self.assertEqual(uploaded["privacy_status"], "private")
        self.assertEqual(uploaded["video_id"], "private-video-001")
        self.assertEqual(self.youtube._videos.upload_body["status"]["privacyStatus"],
                         "private")
        self.assertEqual(uploaded["snapshots"][0]["view_count"], 10)

        revenue = self.ledger.record({
            "job_id": job_id, "brand": brief["brand"], "region": brief["region"],
            "entry_type": "youtube_ads", "amount": 1.25, "currency": "USD",
            "source_type": "youtube_analytics", "source_reference": "e2e-revenue-001",
            "occurred_at": "2026-11-15T00:00:00+00:00",
            "note": "Explicit test fixture, not actual revenue"
        })
        cost = self.ledger.record({
            "job_id": job_id, "brand": brief["brand"], "region": brief["region"],
            "entry_type": "production_cost", "amount": 0.40, "currency": "USD",
            "source_type": "ai_provider", "source_reference": "e2e-cost-001",
            "occurred_at": "2026-11-15T00:00:00+00:00",
            "note": "Explicit test fixture, not actual cost"
        })
        report = self.ledger.report(brand=brief["brand"], currency="USD")
        self.assertEqual(revenue["job_id"], job_id)
        self.assertEqual(cost["job_id"], job_id)
        self.assertEqual(report["revenue"], 1.25)
        self.assertEqual(report["costs"], 0.40)
        self.assertEqual(round(report["net"], 2), 0.85)


    def test_queue_completion_crash_window_is_reconciled_into_review_queue(self):
        brief = {"brand": "Brain Glitch", "region": "US",
                 "language": "English", "topic": "Crash recovery"}
        submitted = submit_production(self.queue, self.production, brief)
        job_id = submitted["job"]["id"]
        claimed = self.queue.claim("crash-worker", "test-host",
                                   job_type="short_video_production")
        self.production.stage(job_id, "rendered", "rendered")
        self.production.artifact(job_id, "rendering", "video",
                                 "https://cdn.example.test/video.mp4", {})
        # Simulate process termination after durable queue completion but before
        # the production record is advanced to review_pending.
        self.queue.finish(job_id, "crash-worker", claimed["lease_token"],
                          {"production_status": "review_pending"})
        self.assertEqual(self.production.get(job_id)["status"], "rendered")
        repaired = self.production.reconcile_review_pending(self.queue)
        self.assertEqual(repaired["job_ids"], [job_id])
        pending = self.review.list_pending()
        self.assertEqual([item["job_id"] for item in pending], [job_id])
        self.assertEqual(self.production.get(job_id)["status"], "review_pending")


    def test_cancel_after_queue_completion_prevents_review_promotion(self):
        brief = {"brand": "Brain Glitch", "region": "US",
                 "language": "English", "topic": "Cancelled after finish"}
        submitted = submit_production(self.queue, self.production, brief)
        job_id = submitted["job"]["id"]
        claimed = self.queue.claim("cancel-race-worker", "test-host",
                                   job_type="short_video_production")
        self.production.stage(job_id, "rendered", "rendered")
        self.queue.finish(job_id, "cancel-race-worker", claimed["lease_token"],
                          {"production_status": "review_pending"})
        self.queue.cancel(job_id, "Operator cancelled before review handoff")
        result = self.production.reconcile_review_pending(self.queue)
        self.assertEqual(result["reconciled"], 0)
        self.assertEqual(self.production.get(job_id)["status"], "cancelled")

    def test_cancelled_queue_job_is_reflected_in_production_record(self):
        brief = {"brand": "Brain Glitch", "region": "US",
                 "language": "English", "topic": "Cancelled job"}
        submitted = submit_production(self.queue, self.production, brief)
        job_id = submitted["job"]["id"]
        self.queue.cancel(job_id, "Operator cancellation")
        result = self.production.reconcile_terminal_jobs(self.queue)
        self.assertEqual(result["job_ids"], [job_id])
        self.assertEqual(self.production.get(job_id)["status"], "cancelled")
        self.assertEqual(self.production.get(job_id)["current_stage"], "cancelled")

    def test_reconciliation_never_promotes_a_job_before_queue_completion(self):
        brief = {"brand": "Brain Glitch", "region": "US",
                 "language": "English", "topic": "Not complete"}
        submitted = submit_production(self.queue, self.production, brief)
        job_id = submitted["job"]["id"]
        self.production.stage(job_id, "rendered", "rendered")
        result = self.production.reconcile_review_pending(self.queue)
        self.assertEqual(result["reconciled"], 0)
        self.assertEqual(self.production.get(job_id)["status"], "rendered")
        self.assertEqual(self.review.list_pending(), [])

    def test_upload_cannot_start_without_human_approval(self):
        brief = {"brand": "Brain Glitch", "region": "US",
                 "language": "English", "topic": "Sleep"}
        submitted = submit_production(self.queue, self.production, brief)
        job_id = submitted["job"]["id"]
        self.media_dir.mkdir(parents=True, exist_ok=True)
        (self.media_dir / "candidate.mp4").write_bytes(b"fake")
        from youtube_publishing import YouTubeUploadError
        with self.assertRaises(YouTubeUploadError):
            self.publisher.upload_approved(job_id, "candidate.mp4",
                                            self.review, "Unapproved")
        self.assertIsNone(self.uploads.get(job_id))


if __name__ == "__main__":
    unittest.main()
