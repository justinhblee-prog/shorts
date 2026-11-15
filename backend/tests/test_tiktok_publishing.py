import json
import os
import tempfile
import unittest
from pathlib import Path

from production_pipeline import ProductionStore
from review_workflow import ReviewStore
from policy_engine import evaluate_content_policy
from tiktok_publishing import TikTokPublishStore, TikTokPublisher, TikTokPublishError


class TikTokTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append((url, headers, body))
        if url.startswith("https://upload.us.tiktokapis.com"):
            return 201, b""
        status, payload = self.responses.pop(0)
        return status, json.dumps(payload).encode("utf-8")


class TikTokPublishingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "db.sqlite3")
        self.prod = ProductionStore(self.db)
        self.review = ReviewStore(self.db)
        self.store = TikTokPublishStore(self.db)
        self.prod.create("job-1", {
            "brand": "Test", "region": "US", "language": "en", "topic": "Test"
        })
        self.prod.stage("job-1", "rendered", "review_pending")
        policy = evaluate_content_policy({
            "rights": {"visuals_cleared": True, "audio_cleared": True,
                       "likeness_authorized": True},
            "synthetic_media_status": "ai_generated",
            "platforms": ["tiktok"],
            "platform_disclosures": {"tiktok_ai_generated_content": True},
            "factual_claims_verified": True,
            "originality_notes": "Original animation.",
        })
        self.prod.artifact("job-1", "script", "text", None, {
            "script": "Approved test script", "policy_preflight": policy
        })
        self.review.decide("job-1", "approved", "reviewer-1")
        self.media = os.path.join(self.tmp.name, "video.mp4")
        Path(self.media).write_bytes(b"test-video-bytes")
        os.environ["NEXUS_MEDIA_DIR"] = self.tmp.name
        self.transport = TikTokTransport([
            (200, {"data": {"privacy_level_options": ["SELF_ONLY"]},
                   "error": {"code": "ok"}}),
            (200, {"data": {"publish_id": "publish-123",
                            "upload_url": "https://upload.us.tiktokapis.com/video/?token=x"},
                   "error": {"code": "ok"}}),
        ])
        self.publisher = TikTokPublisher(self.store, "test-token", self.transport)

    def tearDown(self):
        self.tmp.cleanup()

    def test_publish_approved_video_as_private_with_aigc_label(self):
        result = self.publisher.publish_private_approved(
            "job-1", self.media, self.review, "AI generated short", "operator-1",
            explicit_consent=True,
        )
        self.assertEqual(result["status"], "uploading")
        init = self.transport.calls[1]
        body = json.loads(init[2].decode("utf-8"))
        self.assertEqual(body["post_info"]["privacy_level"], "SELF_ONLY")
        self.assertTrue(body["post_info"]["is_aigc"])
        self.assertEqual(body["source_info"]["source"], "FILE_UPLOAD")
        self.assertEqual(self.transport.calls[2][2], b"test-video-bytes")
        self.assertEqual(self.transport.calls[2][1]["Content-Range"],
                         "bytes 0-15/16")
        self.assertEqual(result["events"][0]["event_type"], "operator_consent_recorded")

    def test_explicit_consent_is_required_before_any_network_request(self):
        with self.assertRaisesRegex(TikTokPublishError, "Explicit operator consent"):
            self.publisher.publish_private_approved(
                "job-1", self.media, self.review, "Caption", "operator-1",
                explicit_consent=False,
            )
        self.assertEqual(self.transport.calls, [])

    def test_unapproved_or_stale_policy_is_rejected(self):
        self.review.decide("job-1", "revision_requested", "reviewer-2")
        with self.assertRaisesRegex(TikTokPublishError, "latest human review"):
            self.publisher.publish_private_approved(
                "job-1", self.media, self.review, "Caption", "operator-1",
                explicit_consent=True,
            )

    def test_unknown_upload_url_host_is_rejected_and_attempt_not_retried(self):
        transport = TikTokTransport([
            (200, {"data": {"privacy_level_options": ["SELF_ONLY"]},
                   "error": {"code": "ok"}}),
            (200, {"data": {"publish_id": "publish-123",
                            "upload_url": "https://evil.example/upload"},
                   "error": {"code": "ok"}}),
        ])
        publisher = TikTokPublisher(self.store, "test-token", transport)
        with self.assertRaisesRegex(TikTokPublishError, "outcome is uncertain"):
            publisher.publish_private_approved(
                "job-1", self.media, self.review, "Caption", "operator-1",
                explicit_consent=True,
            )
        self.assertEqual(self.store.get("job-1")["status"], "reconciliation_required")
        with self.assertRaisesRegex(TikTokPublishError, "unresolved"):
            publisher.publish_private_approved(
                "job-1", self.media, self.review, "Caption", "operator-1",
                explicit_consent=True,
            )

    def test_status_refresh_records_published_video(self):
        self.publisher.publish_private_approved(
            "job-1", self.media, self.review, "AI generated short", "operator-1",
            explicit_consent=True,
        )
        self.transport.responses.append((200, {
            "data": {"status": "PUBLISH_COMPLETE",
                     "publicaly_available_post_id": ["123456789"]},
            "error": {"code": "ok"},
        }))
        result = self.publisher.refresh_status("job-1")
        self.assertEqual(result["status"], "publish_complete")
        self.assertEqual(result["video_id"], "123456789")

    def test_media_path_must_be_inside_media_root(self):
        outside = os.path.join(self.tmp.name, "..", "outside.mp4")
        with self.assertRaisesRegex(TikTokPublishError, "inside NEXUS_MEDIA_DIR"):
            self.publisher._media(outside)

    def test_audit_events_are_immutable(self):
        self.publisher.publish_private_approved(
            "job-1", self.media, self.review, "AI generated short", "operator-1",
            explicit_consent=True,
        )
        with self.store.db() as connection:
            with self.assertRaises(Exception):
                connection.execute(
                    "UPDATE tiktok_publication_events SET note='changed' WHERE job_id='job-1'"
                )


if __name__ == "__main__":
    unittest.main()
