import json
import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from production_pipeline import ProductionStore
from queue_store import JobQueue
from review_workflow import ReviewStore
from policy_engine import evaluate_content_policy, POLICY_VERSION, POLICY_CHECKED_ON
from tiktok_publishing import TikTokPublishStore, TikTokPublisher, TikTokPublishError, CHUNK_SIZE, _NoRedirectHandler


class FakeMediaInspector:
    def __init__(self, duration_seconds=30, width=1080, height=1920,
                 frame_rate=30, video_codec="h264", format_names=None):
        self.duration_seconds = duration_seconds
        self.width = width
        self.height = height
        self.frame_rate = frame_rate
        self.video_codec = video_codec
        self.format_names = format_names or ["mov", "mp4"]

    def inspect(self, media_path):
        return {
            "status": "inspected",
            "duration_seconds": self.duration_seconds,
            "width": self.width,
            "height": self.height,
            "frame_rate": self.frame_rate,
            "video_codec": self.video_codec,
            "format_names": self.format_names,
        }


class TikTokTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, headers, body, timeout, method="POST"):
        self.calls.append((url, headers, body, method))
        if url.startswith("https://upload.us.tiktokapis.com"):
            return 201, b""
        status, payload = self.responses.pop(0)
        return status, json.dumps(payload).encode("utf-8")


class TikTokPublishingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "db.sqlite3")
        self.queue = JobQueue(self.db)
        self.prod = ProductionStore(self.db)
        self.review = ReviewStore(self.db)
        self.store = TikTokPublishStore(self.db)
        self.prod.create("job-1", {
            "brand": "Test", "region": "US", "language": "en", "topic": "Test"
        })
        self.prod.stage("job-1", "rendered", "review_pending")
        with self.queue.db() as connection:
            timestamp="2026-11-16T00:00:00+00:00"
            connection.execute("""
                INSERT INTO pipeline_jobs
                  (id,job_type,payload_json,status,priority,attempt,max_attempts,
                   available_at,created_at,updated_at)
                VALUES(?,?,?,'review_pending',100,0,3,?,?,?)
            """, ("job-1","short_video_production",
                  json.dumps({"brand":"Test","region":"US",
                              "language":"en","topic":"Test"}),
                  timestamp,timestamp,timestamp))
        self.media = os.path.join(self.tmp.name, "video.mp4")
        media_bytes=b"test-video-bytes"
        Path(self.media).write_bytes(media_bytes)
        os.environ["NEXUS_MEDIA_DIR"] = self.tmp.name
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
        self.prod.artifact("job-1", "rendering", "video",
            "https://media.example/video.mp4", {
                "media_staging": {
                    "media_path":"video.mp4","size_bytes":len(media_bytes),
                    "sha256":hashlib.sha256(media_bytes).hexdigest(),
                }
            })
        self.review.decide("job-1", "approved", "reviewer-1")
        self.transport = TikTokTransport([
            (200, {"data": {"privacy_level_options": ["SELF_ONLY"], "max_video_post_duration_sec": 600},
                   "error": {"code": "ok"}}),
            (200, {"data": {"publish_id": "publish-123",
                            "upload_url": "https://upload.us.tiktokapis.com/video/?token=x"},
                   "error": {"code": "ok"}}),
        ])
        self.publisher = TikTokPublisher(self.store, "test-token", self.transport, media_inspector=FakeMediaInspector())

    def tearDown(self):
        self.tmp.cleanup()

    def _uncertain_tiktok_attempt(self):
        attempt_id = "uncertain-attempt-001"
        self.store.begin(
            "job-1", "Approved caption", True, "operator-1", attempt_id, False, False
        )
        self.store.mark_uncertain("job-1", attempt_id, "network timeout during initialization")
        with self.store.db() as connection:
            connection.execute(
                "UPDATE tiktok_publications SET updated_at=? WHERE job_id=?",
                ("2000-01-01T00:00:00+00:00", "job-1"),
            )
        return attempt_id

    def test_tiktok_upload_attempt_records_active_policy_version_and_check_date(self):
        record=self.store.begin(
            "job-1","Approved caption",True,"operator-1","audit-attempt",
            False,False,
        )
        self.assertEqual(record["policy_version"],POLICY_VERSION)
        self.assertEqual(record["policy_checked_on"],POLICY_CHECKED_ON)
        self.assertEqual(record["events"][0]["policy_version"],POLICY_VERSION)
        self.assertEqual(record["events"][0]["policy_checked_on"],POLICY_CHECKED_ON)

    def test_tiktok_reconciliation_requires_explicit_confirmation(self):
        self._uncertain_tiktok_attempt()
        with self.assertRaisesRegex(TikTokPublishError, "Explicit confirmation"):
            self.store.reconcile(
                "job-1", "not_published", "operator-1", "Checked account",
                confirmed=False,
            )
        self.assertEqual(self.store.get("job-1")["status"], "reconciliation_required")

    def test_tiktok_reconciliation_published_records_verified_video_id(self):
        attempt_id = self._uncertain_tiktok_attempt()
        result = self.store.reconcile(
            "job-1", "published", "operator-ops",
            "Verified the private post in the creator account", "verified-video-1",
            confirmed=True,
        )
        self.assertEqual(result["status"], "publish_complete")
        self.assertEqual(result["video_id"], "verified-video-1")
        self.assertEqual(result["attempt_id"], attempt_id)
        self.assertEqual(result["events"][-1]["event_type"], "operator_reconciliation")
        self.assertEqual(result["events"][-1]["operator_id"], "operator-ops")

    def test_tiktok_reconciliation_not_published_unlocks_safe_retry(self):
        self._uncertain_tiktok_attempt()
        result = self.store.reconcile(
            "job-1", "not_published", "operator-ops",
            "Verified no post exists in the creator account", confirmed=True,
        )
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["video_id"])
        next_attempt = self.store.begin(
            "job-1", "Retry after verification", True, "operator-1",
            "retry-attempt-002", False, False,
        )
        self.assertEqual(next_attempt["status"], "initializing")
        self.assertEqual(next_attempt["attempt_id"], "retry-attempt-002")

    def test_tiktok_reconciliation_rejects_recent_uncertain_attempt(self):
        self.store.begin(
            "job-1", "Approved caption", True, "operator-1",
            "fresh-attempt-003", False, False,
        )
        self.store.mark_uncertain("job-1", "fresh-attempt-003", "recent timeout")
        with self.assertRaisesRegex(TikTokPublishError, "at least 15 minutes"):
            self.store.reconcile(
                "job-1", "not_published", "operator-ops",
                "Checked account", confirmed=True,
            )

    def test_tiktok_reconciliation_rejects_video_id_owned_by_another_job(self):
        self._uncertain_tiktok_attempt()
        with self.store.db() as connection:
            connection.execute("""INSERT INTO tiktok_publications
                (job_id,status,privacy_level,title,is_aigc,operator_id,consented_at,
                 updated_at,attempt_id,policy_version,video_id)
                VALUES('job-2','publish_complete','SELF_ONLY','Other',0,'operator',
                 '2026-01-01','2026-01-01','other-attempt','test-policy','duplicate-id')""")
        with self.assertRaisesRegex(TikTokPublishError, "already associated"):
            self.store.reconcile(
                "job-1", "published", "operator-ops", "Verified duplicate",
                "duplicate-id", confirmed=True,
            )

    def test_publish_rejects_media_mutated_after_human_approval(self):
        Path(self.media).write_bytes(b"mutated-after-approval")
        with self.assertRaisesRegex(TikTokPublishError, "changed after human approval"):
            self.publisher.publish_private_approved(
                "job-1", self.media, self.review, "AI generated short", "operator-1",
                explicit_consent=True, privacy_level="SELF_ONLY",
            )
        self.assertEqual(self.transport.calls, [])
        self.assertIsNone(self.store.get("job-1"))

    def test_missing_explicit_privacy_choice_is_blocked_before_network_request(self):
        with self.assertRaisesRegex(TikTokPublishError, "explicitly select SELF_ONLY"):
            self.publisher.publish_private_approved(
                "job-1", self.media, self.review, "AI generated short", "operator-1",
                explicit_consent=True,
                brand_content_toggle=False,
                brand_organic_toggle=False,
            )
        self.assertEqual(self.transport.calls, [])

    def test_video_exceeding_creator_duration_limit_is_blocked_before_init(self):
        self.transport.responses[0] = (200, {
            "data": {
                "privacy_level_options": ["SELF_ONLY"],
                "max_video_post_duration_sec": 20,
            },
            "error": {"code": "ok"},
        })
        with self.assertRaisesRegex(TikTokPublishError, "exceeds the TikTok limit"):
            self.publisher.publish_private_approved(
                "job-1", self.media, self.review, "AI generated short", "operator-1",
                explicit_consent=True,
            privacy_level="SELF_ONLY",
            )
        self.assertEqual(len(self.transport.calls), 1)
        self.assertEqual(self.store.get("job-1")["status"], "failed")

    def test_tiktok_rejects_video_outside_supported_frame_rate(self):
        self.publisher.media_inspector = FakeMediaInspector(frame_rate=20)
        with self.assertRaisesRegex(TikTokPublishError, "23 and 60 FPS"):
            self.publisher.publish_private_approved(
                "job-1", self.media, self.review, "AI generated short", "operator-1",
                explicit_consent=True,
                privacy_level="SELF_ONLY",
            )
        self.assertEqual(len(self.transport.calls), 1)

    def test_tiktok_rejects_video_with_unsupported_dimensions(self):
        self.publisher.media_inspector = FakeMediaInspector(width=240, height=1920)
        with self.assertRaisesRegex(TikTokPublishError, "dimensions"):
            self.publisher.publish_private_approved(
                "job-1", self.media, self.review, "AI generated short", "operator-1",
                explicit_consent=True,
                privacy_level="SELF_ONLY",
            )
        self.assertEqual(len(self.transport.calls), 1)

    def test_tiktok_rejects_unsupported_video_codec(self):
        self.publisher.media_inspector = FakeMediaInspector(video_codec="mpeg4")
        with self.assertRaisesRegex(TikTokPublishError, "codec"):
            self.publisher.publish_private_approved(
                "job-1", self.media, self.review, "AI generated short", "operator-1",
                explicit_consent=True,
                privacy_level="SELF_ONLY",
            )
        self.assertEqual(len(self.transport.calls), 1)

    def test_file_just_over_64_mib_uses_two_valid_sequential_chunks(self):
        path = Path(self.tmp.name) / "large.mp4"
        size = CHUNK_SIZE + 17
        with path.open("wb") as media:
            media.truncate(size)
        calls = []

        def transport(url, headers, body, timeout, method="POST"):
            calls.append({
                "method": method,
                "length": len(body),
                "range": headers.get("Content-Range"),
            })
            return (206 if len(calls) == 1 else 201), b""

        publisher = TikTokPublisher(
            self.store, "test-token", transport,
            media_inspector=FakeMediaInspector(),
        )
        publisher._upload_chunks(
            "https://upload.us.tiktokapis.com/video/?token=test",
            str(path), "video/mp4", size,
        )
        self.assertEqual(len(calls), 2)
        base = size // 2
        self.assertEqual(calls[0]["length"], base)
        self.assertEqual(calls[1]["length"], size - base)
        self.assertEqual(calls[0]["range"], f"bytes 0-{base - 1}/{size}")
        self.assertEqual(calls[1]["range"], f"bytes {base}-{size - 1}/{size}")

    def test_api_error_string_is_reported_without_attribute_error(self):
        transport = TikTokTransport([(200, {"error": "access_denied"})])
        publisher = TikTokPublisher(self.store, "test-token", transport)
        with self.assertRaisesRegex(TikTokPublishError, "TikTok API error: access_denied"):
            publisher._call("https://open.tiktokapis.com/v2/test/")

    def test_http_error_string_is_reported_without_attribute_error(self):
        transport = TikTokTransport([(403, {"error": "access_denied"})])
        publisher = TikTokPublisher(self.store, "test-token", transport)
        with self.assertRaisesRegex(TikTokPublishError, "TikTok HTTP 403: access_denied"):
            publisher._call("https://open.tiktokapis.com/v2/test/")

    def test_non_object_api_response_is_rejected_cleanly(self):
        transport = TikTokTransport([(200, ["unexpected", "array"])])
        publisher = TikTokPublisher(self.store, "test-token", transport)
        with self.assertRaisesRegex(TikTokPublishError, "unexpected response shape"):
            publisher._call("https://open.tiktokapis.com/v2/test/")

    def test_success_accepts_string_ok_error_envelope(self):
        transport = TikTokTransport([(200, {"data": {"ready": True}, "error": "ok"})])
        publisher = TikTokPublisher(self.store, "test-token", transport)
        self.assertTrue(publisher._call("https://open.tiktokapis.com/v2/test/")["data"]["ready"])

    def test_atomic_begin_result_prevents_duplicate_publish_after_completion_race(self):
        completed = {
            "job_id": "job-1",
            "status": "publish_complete",
            "attempt_id": "already-completed-attempt",
            "video_id": "video-123",
        }
        # Simulate the first read missing a concurrent completion, followed by
        # BEGIN IMMEDIATE observing the authoritative terminal row.
        self.store.get = lambda job_id: None
        self.store.begin = lambda *args, **kwargs: completed
        result = self.publisher.publish_private_approved(
            "job-1", self.media, self.review, "AI generated short", "operator-1",
            explicit_consent=True,
            privacy_level="SELF_ONLY",
        )
        self.assertEqual(result, completed)
        self.assertEqual(self.transport.calls, [])

    def test_publish_approved_video_as_private_with_aigc_label(self):
        result = self.publisher.publish_private_approved(
            "job-1", self.media, self.review, "AI generated short", "operator-1",
            explicit_consent=True,
            privacy_level="SELF_ONLY",
        )
        self.assertEqual(result["status"], "uploading")
        init = self.transport.calls[1]
        body = json.loads(init[2].decode("utf-8"))
        self.assertEqual(body["post_info"]["privacy_level"], "SELF_ONLY")
        self.assertTrue(body["post_info"]["is_aigc"])
        self.assertEqual(body["source_info"]["source"], "FILE_UPLOAD")
        self.assertEqual(self.transport.calls[2][2], b"test-video-bytes")
        self.assertEqual(self.transport.calls[2][3], "PUT")
        self.assertNotIn("Authorization", self.transport.calls[2][1])
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
        self.prod.stage("job-1", "rendered", "review_pending")
        with self.queue.db() as connection:
            connection.execute(
                "UPDATE pipeline_jobs SET status='review_pending' WHERE id=?",
                ("job-1",),
            )
            queue_state = connection.execute(
                "SELECT job_type,status FROM pipeline_jobs WHERE id=?", ("job-1",)
            ).fetchone()
            self.assertEqual(
                (queue_state["job_type"], queue_state["status"]),
                ("short_video_production", "review_pending"),
            )
        self.review.decide("job-1", "revision_requested", "reviewer-2",
                           comment="Please correct the disclosure metadata.")
        with self.assertRaisesRegex(TikTokPublishError, "latest human review"):
            self.publisher.publish_private_approved(
                "job-1", self.media, self.review, "Caption", "operator-1",
                explicit_consent=True,
            privacy_level="SELF_ONLY",
            )

    def test_upload_url_rejects_unapproved_tiktok_subdomain(self):
        with self.assertRaisesRegex(TikTokPublishError, "untrusted upload URL"):
            TikTokPublisher._validate_upload_url("https://evil.tiktokapis.com/video/")

    def test_upload_url_rejects_credentials_and_nonstandard_ports(self):
        for url in (
            "https://user@open-upload.tiktokapis.com/video/",
            "https://open-upload.tiktokapis.com:8443/video/",
            "https://open-upload.tiktokapis.com/video/#fragment",
        ):
            with self.subTest(url=url):
                with self.assertRaisesRegex(TikTokPublishError, "untrusted upload URL"):
                    TikTokPublisher._validate_upload_url(url)

    def test_signed_upload_redirects_are_disabled(self):
        handler = _NoRedirectHandler()
        redirected = handler.redirect_request(
            None, None, 307, "Temporary Redirect", {}, "https://attacker.example/collect"
        )
        self.assertIsNone(redirected)

    def test_upload_url_accepts_documented_regional_upload_host(self):
        url = "https://upload.us.tiktokapis.com/video/?token=signed"
        self.assertEqual(TikTokPublisher._validate_upload_url(url), url)

    def test_upload_url_accepts_official_upload_host(self):
        url = "https://open-upload.tiktokapis.com/video/?token=signed"
        self.assertEqual(TikTokPublisher._validate_upload_url(url), url)

    def test_unknown_upload_url_host_is_rejected_and_attempt_not_retried(self):
        transport = TikTokTransport([
            (200, {"data": {"privacy_level_options": ["SELF_ONLY"], "max_video_post_duration_sec": 600},
                   "error": {"code": "ok"}}),
            (200, {"data": {"publish_id": "publish-123",
                            "upload_url": "https://evil.example/upload"},
                   "error": {"code": "ok"}}),
        ])
        publisher = TikTokPublisher(self.store, "test-token", transport, media_inspector=FakeMediaInspector())
        with self.assertRaisesRegex(TikTokPublishError, "outcome is uncertain"):
            publisher.publish_private_approved(
                "job-1", self.media, self.review, "Caption", "operator-1",
                explicit_consent=True,
            privacy_level="SELF_ONLY",
            )
        self.assertEqual(self.store.get("job-1")["status"], "reconciliation_required")
        with self.assertRaisesRegex(TikTokPublishError, "unresolved"):
            publisher.publish_private_approved(
                "job-1", self.media, self.review, "Caption", "operator-1",
                explicit_consent=True,
            privacy_level="SELF_ONLY",
            )

    def test_send_to_user_inbox_status_is_tracked_separately(self):
        self.publisher.publish_private_approved(
            "job-1", self.media, self.review, "AI generated short", "operator-1",
            explicit_consent=True,
            privacy_level="SELF_ONLY",
        )
        self.transport.responses.append((200, {
            "data": {"status": "SEND_TO_USER_INBOX",
                     "publicaly_available_post_id": []},
            "error": {"code": "ok"},
        }))
        result = self.publisher.refresh_status("job-1")
        self.assertEqual(result["status"], "send_to_inbox")

    def test_status_refresh_records_published_video(self):
        self.publisher.publish_private_approved(
            "job-1", self.media, self.review, "AI generated short", "operator-1",
            explicit_consent=True,
            privacy_level="SELF_ONLY",
        )
        self.transport.responses.append((200, {
            "data": {"status": "PUBLISH_COMPLETE",
                     "publicaly_available_post_id": ["123456789"]},
            "error": {"code": "ok"},
        }))
        result = self.publisher.refresh_status("job-1")
        self.assertEqual(result["status"], "publish_complete")
        self.assertEqual(result["video_id"], "123456789")

    def test_late_processing_status_cannot_downgrade_published_result(self):
        self.publisher.publish_private_approved(
            "job-1", self.media, self.review, "AI generated short", "operator-1",
            explicit_consent=True,
            privacy_level="SELF_ONLY",
        )
        attempt_id = self.store.get("job-1")["attempt_id"]
        complete = self.store.mark_status(
            "job-1", attempt_id, "PUBLISH_COMPLETE", ["123456789"], None
        )
        self.assertEqual(complete["status"], "publish_complete")
        stale = self.store.mark_status(
            "job-1", attempt_id, "PROCESSING_UPLOAD", [], None
        )
        self.assertEqual(stale["status"], "publish_complete")
        self.assertEqual(stale["video_id"], "123456789")

    def test_late_poll_error_cannot_downgrade_published_result(self):
        self.publisher.publish_private_approved(
            "job-1", self.media, self.review, "AI generated short", "operator-1",
            explicit_consent=True, privacy_level="SELF_ONLY",
        )
        attempt_id = self.store.get("job-1")["attempt_id"]
        complete = self.store.mark_status(
            "job-1", attempt_id, "PUBLISH_COMPLETE", ["video-123"], None,
        )
        self.assertEqual(complete["status"], "publish_complete")
        self.store.mark_uncertain(
            "job-1", attempt_id, "late concurrent status poll timed out",
        )
        after = self.store.get("job-1")
        self.assertEqual(after["status"], "publish_complete")
        self.assertEqual(after["video_id"], "video-123")
        self.assertEqual(after["events"][-1]["event_type"], "post_terminal_poll_error")
        self.assertEqual(after["events"][-1]["outcome"], "informational")
        self.store.record_status_poll_error(
            "job-1", attempt_id, "another late scheduler poll failed",
        )
        after_scheduler_error = self.store.get("job-1")
        self.assertEqual(after_scheduler_error["status"], "publish_complete")
        self.assertEqual(
            after_scheduler_error["events"][-1]["event_type"],
            "post_terminal_poll_error",
        )

    def test_late_processing_status_cannot_downgrade_inbox_handoff(self):
        self.publisher.publish_private_approved(
            "job-1", self.media, self.review, "AI generated short", "operator-1",
            explicit_consent=True,
            privacy_level="SELF_ONLY",
        )
        attempt_id = self.store.get("job-1")["attempt_id"]
        inbox = self.store.mark_status(
            "job-1", attempt_id, "SEND_TO_USER_INBOX", [], None
        )
        self.assertEqual(inbox["status"], "send_to_inbox")
        self.store.mark_uncertain(
            "job-1", attempt_id, "late concurrent status poll timed out",
        )
        after_error = self.store.get("job-1")
        self.assertEqual(after_error["status"], "send_to_inbox")
        self.assertEqual(after_error["events"][-1]["event_type"], "post_terminal_poll_error")
        stale = self.store.mark_status(
            "job-1", attempt_id, "PROCESSING_UPLOAD", [], None
        )
        self.assertEqual(stale["status"], "send_to_inbox")

    def test_status_fetch_rejects_malformed_nested_data(self):
        self.publisher.publish_private_approved(
            "job-1", self.media, self.review, "AI generated short", "operator-1",
            explicit_consent=True,
            privacy_level="SELF_ONLY",
        )
        self.transport.responses.append((200, {
            "data": ["unexpected"], "error": {"code": "ok"}
        }))
        with self.assertRaisesRegex(TikTokPublishError, "unexpected shape"):
            self.publisher.refresh_status("job-1")

    def test_scheduler_poll_refreshes_pending_status_and_stops_after_completion(self):
        self.publisher.publish_private_approved(
            "job-1", self.media, self.review, "AI generated short", "operator-1",
            explicit_consent=True,
            privacy_level="SELF_ONLY",
        )
        self.transport.responses.append((200, {
            "data": {"status": "PUBLISH_COMPLETE",
                     "publicaly_available_post_id": []},
            "error": {"code": "ok"},
        }))
        result = self.publisher.refresh_due_statuses(limit=5, min_age_seconds=0)
        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["updated"], 1)
        self.assertEqual(self.store.get("job-1")["status"], "publish_complete")
        again = self.publisher.refresh_due_statuses(limit=5, min_age_seconds=0)
        self.assertEqual(again["checked"], 0)

    def test_scheduler_poll_errors_are_audited_and_backed_off(self):
        self.publisher.publish_private_approved(
            "job-1", self.media, self.review, "AI generated short", "operator-1",
            explicit_consent=True,
            privacy_level="SELF_ONLY",
        )
        self.transport.responses.append((200, {
            "error": {"code": "rate_limit_exceeded", "message": "slow down"}
        }))
        result = self.publisher.refresh_due_statuses(limit=5, min_age_seconds=0)
        self.assertEqual(result["checked"], 1)
        self.assertEqual(len(result["errors"]), 1)
        record = self.store.get("job-1")
        self.assertEqual(record["status"], "uploading")
        self.assertEqual(record["events"][-1]["event_type"], "status_poll_failed")
        self.assertEqual(
            self.store.due_status_job_ids(limit=5, min_age_seconds=60), []
        )

    def test_scheduler_poll_backoff_grows_and_success_resets_it(self):
        self.publisher.publish_private_approved(
            "job-1", self.media, self.review, "AI generated short", "operator-1",
            explicit_consent=True,
            privacy_level="SELF_ONLY",
        )
        attempt_id = self.store.get("job-1")["attempt_id"]
        self.store.record_status_poll_error("job-1", attempt_id, "temporary error")
        with self.store.db() as connection:
            connection.execute(
                "UPDATE tiktok_publications SET updated_at=datetime('now','-59 seconds') WHERE job_id='job-1'"
            )
        self.assertEqual(self.store.due_status_job_ids(limit=5, min_age_seconds=0), [])
        with self.store.db() as connection:
            connection.execute(
                "UPDATE tiktok_publications SET updated_at=datetime('now','-61 seconds') WHERE job_id='job-1'"
            )
        self.assertEqual(self.store.due_status_job_ids(limit=5, min_age_seconds=0), ["job-1"])

        self.store.record_status_poll_error("job-1", attempt_id, "second temporary error")
        with self.store.db() as connection:
            connection.execute(
                "UPDATE tiktok_publications SET updated_at=datetime('now','-119 seconds') WHERE job_id='job-1'"
            )
        self.assertEqual(self.store.due_status_job_ids(limit=5, min_age_seconds=0), [])
        with self.store.db() as connection:
            connection.execute(
                "UPDATE tiktok_publications SET updated_at=datetime('now','-121 seconds') WHERE job_id='job-1'"
            )
        self.assertEqual(self.store.due_status_job_ids(limit=5, min_age_seconds=0), ["job-1"])

        self.transport.responses.append((200, {
            "data": {"status": "PROCESSING_UPLOAD", "publicaly_available_post_id": []},
            "error": {"code": "ok"},
        }))
        self.publisher.refresh_status("job-1")
        with self.store.db() as connection:
            connection.execute(
                "UPDATE tiktok_publications SET updated_at=datetime('now','-1 seconds') WHERE job_id='job-1'"
            )
        self.assertEqual(self.store.due_status_job_ids(limit=5, min_age_seconds=0), ["job-1"])

    def test_media_path_must_be_inside_media_root(self):
        outside = os.path.join(self.tmp.name, "..", "outside.mp4")
        with self.assertRaisesRegex(TikTokPublishError, "inside NEXUS_MEDIA_DIR"):
            self.publisher._media(outside)

    def test_audit_events_are_immutable(self):
        self.publisher.publish_private_approved(
            "job-1", self.media, self.review, "AI generated short", "operator-1",
            explicit_consent=True,
            privacy_level="SELF_ONLY",
        )
        with self.store.db() as connection:
            with self.assertRaises(Exception):
                connection.execute(
                    "UPDATE tiktok_publication_events SET note='changed' WHERE job_id='job-1'"
                )


if __name__ == "__main__":
    unittest.main()
