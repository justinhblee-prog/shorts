import json
import os
import tempfile
import unittest
from pathlib import Path

from production_pipeline import ProductionStore
from review_workflow import ReviewStore
from policy_engine import evaluate_content_policy
from tiktok_publishing import TikTokPublishStore, TikTokPublisher, TikTokPublishError


class FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body or {}
    def json(self):
        return self._body


class FakeSession:
    def __init__(self):
        self.posts = []
        self.puts = []
        self.responses = []
    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        if "/creator_info/" in url:
            return FakeResponse(body={"data":{"privacy_level_options":["SELF_ONLY"]},
                                      "error":{"code":"ok"}})
        if "/video/init/" in url:
            return FakeResponse(body={"data":{"publish_id":"publish-123",
                "upload_url":"https://open-upload.tiktokapis.com/video/?upload_id=1&upload_token=x"},
                "error":{"code":"ok"}})
        if "/status/fetch/" in url:
            return FakeResponse(body={"data":{"status":"PUBLISH_COMPLETE"},
                                      "error":{"code":"ok"}})
        raise AssertionError(url)
    def put(self, url, **kwargs):
        self.puts.append((url, kwargs))
        return FakeResponse(201)


class TikTokPublishingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "nexus.sqlite3")
        self.prod = ProductionStore(self.db)
        self.review = ReviewStore(self.db)
        self.store = TikTokPublishStore(self.db)
        self.prod.create("job-tt", {"brand":"Test", "region":"US",
                                    "language":"English", "topic":"Test"})
        self.prod.stage("job-tt", "rendered", "review_pending")
        self.prod.artifact("job-tt", "script", "text", None, {
            "script":"test",
            "policy_preflight":evaluate_content_policy({
                "platforms":["tiktok"], "synthetic_media_status":"ai_generated",
                "platform_disclosures":{"tiktok_ai_generated_content":True},
                "rights":{"visuals_cleared":True,"audio_cleared":True,
                          "likeness_authorized":True},
                "factual_claims_verified":True, "originality_notes":"Original test",
            }),
        })
        self.review.decide("job-tt", "approved", "reviewer")
        self.media = os.path.join(self.tmp.name, "video.mp4")
        Path(self.media).write_bytes(b"fake video bytes")
        os.environ["NEXUS_MEDIA_DIR"] = self.tmp.name
        os.environ["TIKTOK_ACCESS_TOKEN"] = "test-token"
        self.session = FakeSession()
        self.publisher = TikTokPublisher(self.store, self.session)

    def tearDown(self):
        os.environ.pop("TIKTOK_ACCESS_TOKEN", None)
        self.tmp.cleanup()

    def test_publish_requires_explicit_creator_consent(self):
        with self.assertRaisesRegex(TikTokPublishError, "consent"):
            self.publisher.publish_approved("job-tt", self.media, self.review,
                "caption", False, True, "reviewer", False, False)
        self.assertIsNone(self.store.get("job-tt"))

    def test_private_upload_maps_aigc_and_status(self):
        result = self.publisher.publish_approved("job-tt", self.media, self.review,
            "creator confirmed caption", True, True, "reviewer", False, False)
        self.assertEqual(result["status"], "processing")
        init = next(item for item in self.session.posts if "/video/init/" in item[0])
        body = init[1]["json"]
        self.assertEqual(body["post_info"]["privacy_level"], "SELF_ONLY")
        self.assertTrue(body["post_info"]["is_aigc"])
        self.assertTrue(body["post_info"]["disable_duet"])
        self.assertEqual(len(self.session.puts), 1)
        self.assertNotIn("Authorization", self.session.puts[0][1]["headers"])
        completed = self.publisher.refresh_status("job-tt")
        self.assertEqual(completed["status"], "published")
        self.assertEqual(completed["remote_status"], "PUBLISH_COMPLETE")

    def test_unknown_policy_and_missing_disclosure_fail_closed(self):
        with self.prod.db() as connection:
            row = connection.execute(
                "SELECT id,metadata_json FROM production_artifacts WHERE job_id=?",
                ("job-tt",)
            ).fetchone()
            metadata = json.loads(row["metadata_json"])
            metadata["policy_preflight"]["platform_disclosures"] = {}
            connection.execute("UPDATE production_artifacts SET metadata_json=? WHERE id=?",
                (json.dumps(metadata), row["id"]))
        with self.assertRaisesRegex(TikTokPublishError, "blocked|disclosure"):
            self.publisher.publish_approved("job-tt", self.media, self.review,
                "caption", True, True, "reviewer", False, False)
        self.assertIsNone(self.store.get("job-tt"))

    def test_sponsorship_fields_are_explicit_and_audited(self):
        result = self.publisher.publish_approved("job-tt", self.media, self.review,
            "caption", True, True, "reviewer", True, False)
        init = next(item for item in self.session.posts if "/video/init/" in item[0])
        self.assertTrue(init[1]["json"]["post_info"]["brand_content_toggle"])
        self.assertFalse(init[1]["json"]["post_info"]["brand_organic_toggle"])
        self.assertEqual(result["events"][0]["operator_id"], "reviewer")

    def test_ambiguous_init_can_be_reconciled_by_operator(self):
        attempt = self.store.begin("job-tt", "caption", True, "policy-v1", "reviewer")
        self.store.update("job-tt", attempt["attempt_id"], "reconciliation_required",
            error="timeout", event_type="publish_outcome_uncertain")
        result = self.store.reconcile("job-tt", "not_published", "ops",
            "Checked TikTok profile and inbox; no post exists")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["events"][-1]["event_type"], "operator_reconciled")
        self.assertEqual(result["events"][-1]["operator_id"], "ops")

    def test_chunk_plan_matches_tiktok_trailing_chunk_rule(self):
        size = 50_000_123
        chunk_size = 10_000_000
        total_chunks = size // chunk_size
        self.assertEqual(total_chunks, 5)
        last_chunk = size - chunk_size * (total_chunks - 1)
        self.assertGreaterEqual(last_chunk, 5 * 1024 * 1024)
        self.assertEqual(last_chunk, 10_000_123)

    def test_caption_limit_uses_utf16_code_units(self):
        with self.assertRaisesRegex(TikTokPublishError, "UTF-16"):
            self.publisher.publish_approved("job-tt", self.media, self.review,
                "😀" * 1101, True, True, "reviewer", False, False)

    def test_upload_url_length_is_bounded(self):
        long_url = "https://open-upload.tiktokapis.com/" + ("x" * 230)
        with self.assertRaisesRegex(TikTokPublishError, "oversized"):
            TikTokPublisher._upload_url_allowed(long_url)

    def test_untrusted_upload_url_is_rejected(self):
        self.assertRaises(TikTokPublishError,
            TikTokPublisher._upload_url_allowed, "https://evil.example/upload")

    def test_uncertain_upload_cannot_be_retried(self):
        result = self.publisher.publish_approved("job-tt", self.media, self.review,
            "caption", True, True, "reviewer", False, False)
        self.store.update("job-tt", result["attempt_id"], "reconciliation_required",
            error="timeout", event_type="publish_outcome_uncertain")
        with self.assertRaisesRegex(TikTokPublishError, "retry"):
            self.publisher.publish_approved("job-tt", self.media, self.review,
                "caption", True, True, "reviewer", False, False)


if __name__ == "__main__":
    unittest.main()
