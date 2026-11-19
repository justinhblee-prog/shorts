import json
import hashlib
import os
import tempfile, threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from production_pipeline import ProductionStore
from queue_store import JobQueue
from review_workflow import ReviewStore, ReviewConflict
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

    def test_mark_failed_before_remote_samples_clock_after_write_lock(self):
        self.store.begin(
            "job-1", "Lock contention test", True, "operator-1",
            "attempt-before-remote-lock", False, False,
        )
        decision = "2036-07-08T09:10:15+00:00"
        clock_called = threading.Event()
        started = threading.Event()
        outcome = {}

        def controlled_now():
            clock_called.set()
            return decision

        def fail_before_remote():
            started.set()
            try:
                self.store.mark_failed_before_remote(
                    "job-1", "attempt-before-remote-lock", "local preflight failed"
                )
            except Exception as exc:
                outcome["error"] = exc

        with self.store.db() as holder:
            holder.execute("BEGIN IMMEDIATE")
            with patch("tiktok_publishing._now", side_effect=controlled_now):
                thread = threading.Thread(target=fail_before_remote)
                thread.start()
                self.assertTrue(started.wait(1))
                self.assertFalse(
                    clock_called.wait(0.1),
                    "TikTok failure timestamp must not be sampled before the SQLite write lock",
                )
                holder.commit()
                thread.join(2)
            self.assertFalse(thread.is_alive(), "TikTok failure transition did not finish")

        self.assertNotIn("error", outcome)
        row = self.store.get("job-1")
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["updated_at"], decision)

    def test_begin_rechecks_current_approval_and_queue_state_atomically(self):
        # Simulate a reviewer reopening the job after publisher preflight but
        # before the attempt reservation transaction starts.
        self.prod.stage("job-1", "review", "review_pending")
        with self.queue.db() as connection:
            connection.execute(
                "UPDATE pipeline_jobs SET status='review_pending' WHERE id=?",
                ("job-1",),
            )
        with self.assertRaisesRegex(TikTokPublishError, "approval is no longer current"):
            self.store.begin(
                "job-1", "Approved caption", True, "operator-1",
                "stale-approval-attempt", False, False,
                require_current_approval=True,
            )
        self.assertIsNone(self.store.get("job-1"))

    def test_begin_rejects_queue_state_that_is_not_approved(self):
        with self.queue.db() as connection:
            connection.execute(
                "UPDATE pipeline_jobs SET status='review_pending' WHERE id=?",
                ("job-1",),
            )
        with self.assertRaisesRegex(TikTokPublishError, "approval is no longer current"):
            self.store.begin(
                "job-1", "Approved caption", True, "operator-1",
                "queue-state-mismatch-attempt", False, False,
                require_current_approval=True,
            )
        self.assertIsNone(self.store.get("job-1"))

    def test_concurrent_tiktok_reservations_allow_only_one_attempt(self):
        gate=threading.Event()
        def reserve(index):
            gate.wait()
            try:
                return self.store.begin(
                    "job-1",f"Concurrent title {index}",True,f"operator-{index}",
                    f"concurrent-attempt-{index}",False,False
                )["attempt_id"]
            except TikTokPublishError:
                return None
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures=[pool.submit(reserve,index) for index in range(8)]
            gate.set()
            results=[future.result() for future in futures]
        winners=[attempt for attempt in results if attempt is not None]
        self.assertEqual(len(winners),1)
        current=self.store.get("job-1")
        self.assertEqual(current["attempt_id"],winners[0])
        self.assertEqual(current["status"],"initializing")
        starts=[event for event in current["events"] if event["event_type"]=="operator_consent_recorded"]
        self.assertEqual(len(starts),1)
        self.assertEqual(current["privacy_level"],"SELF_ONLY")

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

    def test_tiktok_reconciliation_rejects_stale_attempt_identity_without_mutation(self):
        attempt_id = self._uncertain_tiktok_attempt()
        with self.assertRaisesRegex(TikTokPublishError, "attempt ID does not match"):
            self.store.reconcile(
                "job-1", "not_published", "operator-ops", "Checked account",
                confirmed=True, expected_attempt_id="stale-attempt",
            )
        current = self.store.get("job-1")
        self.assertEqual(current["status"], "reconciliation_required")
        self.assertEqual(current["attempt_id"], attempt_id)
        self.assertFalse(any(
            event["event_type"] == "operator_reconciliation"
            for event in current["events"]
        ))

    def test_superseded_tiktok_attempt_uncertainty_blocks_new_attempt(self):
        first_attempt = "uncertain-attempt-001"
        self.store.begin(
            "job-1", "Approved caption", True, "operator-1",
            first_attempt, False, False,
        )
        self.store.set_initialized(
            "job-1", first_attempt, "old-publish-id",
            {"creator_username": "creator", "creator_nickname": "Creator"},
        )
        self.store.mark_uncertain(
            "job-1", first_attempt, "initial upload response became uncertain",
        )
        with self.store.db() as connection:
            connection.execute(
                "UPDATE tiktok_publications SET updated_at=? WHERE job_id=?",
                ("2000-01-01T00:00:00+00:00", "job-1"),
            )
        self.store.reconcile(
            "job-1", "not_published", "operator-ops",
            "Verified no post existed before retry", confirmed=True,
        )
        # Preserve a known video ID even when a later audit row omits it.
        with self.store.db() as connection:
            connection.execute(
                """
                INSERT INTO tiktok_publication_events
                  (job_id,attempt_id,event_type,outcome,publish_id,video_id,
                   operator_id,note,created_at,policy_version)
                VALUES(?,?,'provider_video_observed','informational',
                       NULL,'old-video-id','operator-1',?,?,?)
                """,
                (
                    "job-1", first_attempt, "Observed provider video ID",
                    "2026-01-01T00:00:00+00:00", POLICY_VERSION,
                ),
            )
        # A later audit row without provider identifiers must not hide the
        # identifiers recorded by the earlier initialization event.
        with self.store.db() as connection:
            connection.execute(
                """
                INSERT INTO tiktok_publication_events
                  (job_id,attempt_id,event_type,outcome,publish_id,video_id,
                   operator_id,note,created_at,policy_version)
                VALUES(?,?,'diagnostic_without_provider_ids','informational',
                       NULL,NULL,?,?,?,?)
                """,
                (
                    "job-1", first_attempt, "operator-1",
                    "Non-provider diagnostic", "2026-01-01T00:00:00+00:00",
                    POLICY_VERSION,
                ),
            )
        second = self.store.begin(
            "job-1", "Retry after operator verification", True, "operator-1",
            "retry-attempt-002", False, False,
        )
        self.assertEqual(second["status"], "initializing")
        self.store.mark_uncertain(
            "job-1", first_attempt, "late response from the superseded TikTok attempt",
        )
        current = self.store.get("job-1")
        self.assertEqual(current["status"], "reconciliation_required")
        self.assertEqual(current["attempt_id"], "retry-attempt-002")
        self.assertEqual(current["events"][-1]["event_type"], "superseded_attempt_uncertain")
        self.assertEqual(current["events"][-1]["attempt_id"], first_attempt)
        self.assertEqual(current["events"][-1]["publish_id"], "old-publish-id")
        self.assertEqual(current["events"][-1]["video_id"], "old-video-id")
        self.assertEqual(current["events"][-1]["operator_id"], "operator-1")
        self.assertEqual(current["events"][-1]["publish_id"], "old-publish-id")
        with self.assertRaisesRegex(TikTokPublishError, "unresolved or already active"):
            self.store.begin(
                "job-1", "Third attempt", True, "operator-1",
                "retry-attempt-003", False, False,
            )

    def test_superseded_uncertainty_uses_original_consent_operator_not_reviewer(self):
        first_attempt = "uncertain-attempt-operator-check"
        self.store.begin("job-1","Old attempt",True,"old-operator",first_attempt,False,False)
        self.store.set_initialized(
            "job-1",first_attempt,"old-publish-id",
            {"creator_username":"creator","creator_nickname":"Creator"},
        )
        self.store.mark_uncertain("job-1",first_attempt,"old attempt timed out")
        with self.store.db() as connection:
            connection.execute(
                "UPDATE tiktok_publications SET updated_at=? WHERE job_id=?",
                ("2026-01-01T00:00:00+00:00","job-1"),
            )
        self.store.reconcile(
            "job-1","not_published","reviewer","Verified no post existed",
            confirmed=True,
        )
        self.store.begin("job-1","New attempt",True,"current-operator","retry-attempt-002",False,False)
        self.store.mark_uncertain("job-1",first_attempt,"late old worker timeout")
        result=self.store.get("job-1")
        self.assertEqual(result["status"],"reconciliation_required")
        event=result["events"][-1]
        self.assertEqual(event["attempt_id"],first_attempt)
        self.assertEqual(event["operator_id"],"old-operator")
        self.assertNotEqual(event["operator_id"],"reviewer")
        self.assertNotEqual(event["operator_id"],"current-operator")

    def test_late_superseded_tiktok_publish_complete_is_audited_and_blocks_retry(self):
        first_attempt = "old-poll-attempt"
        self.store.begin("job-1","Old attempt",True,"old-operator",first_attempt,False,False)
        self.store.set_initialized(
            "job-1",first_attempt,"old-publish-id",
            {"creator_username":"creator","creator_nickname":"Creator"},
        )
        self.store.mark_uncertain("job-1",first_attempt,"old request timed out")
        with self.store.db() as connection:
            connection.execute(
                "UPDATE tiktok_publications SET updated_at=? WHERE job_id=?",
                ("2026-01-01T00:00:00+00:00","job-1"),
            )
        self.store.reconcile(
            "job-1","not_published","reviewer","Verified no post existed",confirmed=True,
        )
        self.store.begin("job-1","New attempt",True,"new-operator","new-poll-attempt",False,False)
        result=self.store.mark_status(
            "job-1",first_attempt,"PUBLISH_COMPLETE",["late-old-video"],None,
        )
        self.assertEqual(result["attempt_id"],"new-poll-attempt")
        self.assertEqual(result["status"],"reconciliation_required")
        result=self.store.get("job-1")
        event=result["events"][-1]
        self.assertEqual(event["event_type"],"superseded_attempt_status_observed")
        self.assertEqual(event["attempt_id"],first_attempt)
        self.assertEqual(event["publish_id"],"old-publish-id")
        self.assertEqual(event["video_id"],"late-old-video")
        self.assertEqual(event["operator_id"],"old-operator")
        with self.assertRaises(TikTokPublishError):
            self.store.begin("job-1","Duplicate retry",True,"new-operator","third-attempt",False,False)

    def test_late_superseded_tiktok_success_blocks_retry_after_new_attempt_failed(self):
        first_attempt = "old-poll-attempt-failed-current"
        self.store.begin("job-1","Old attempt",True,"old-operator",first_attempt,False,False)
        self.store.set_initialized(
            "job-1",first_attempt,"old-publish-id",
            {"creator_username":"creator","creator_nickname":"Creator"},
        )
        self.store.mark_uncertain("job-1",first_attempt,"old request timed out")
        with self.store.db() as connection:
            connection.execute(
                "UPDATE tiktok_publications SET updated_at=? WHERE job_id=?",
                ("2026-01-01T00:00:00+00:00","job-1"),
            )
        self.store.reconcile(
            "job-1","not_published","reviewer","Verified no post existed",confirmed=True,
        )
        self.store.begin("job-1","New attempt",True,"new-operator","new-poll-attempt-failed",False,False)
        self.store.mark_failed_before_remote("job-1","new-poll-attempt-failed","local preflight failure")
        result=self.store.mark_status(
            "job-1",first_attempt,"PUBLISH_COMPLETE",["late-old-video"],None,
        )
        self.assertEqual(result["attempt_id"],"new-poll-attempt-failed")
        self.assertEqual(result["status"],"reconciliation_required")
        result=self.store.get("job-1")
        self.assertEqual(result["events"][-1]["attempt_id"],first_attempt)

    def test_late_superseded_tiktok_failed_status_is_audited_without_blocking_retry(self):
        first_attempt = "old-failed-poll-attempt"
        self.store.begin("job-1","Old attempt",True,"old-operator",first_attempt,False,False)
        self.store.set_initialized(
            "job-1",first_attempt,"old-publish-id",
            {"creator_username":"creator","creator_nickname":"Creator"},
        )
        self.store.mark_uncertain("job-1",first_attempt,"old request timed out")
        with self.store.db() as connection:
            connection.execute(
                "UPDATE tiktok_publications SET updated_at=? WHERE job_id=?",
                ("2026-01-01T00:00:00+00:00","job-1"),
            )
        self.store.reconcile(
            "job-1","not_published","reviewer","Verified no post existed",confirmed=True,
        )
        self.store.begin("job-1","New attempt",True,"new-operator","new-active-attempt",False,False)
        result=self.store.mark_status("job-1",first_attempt,"FAILED",[], "Old attempt failed")
        self.assertEqual(result["attempt_id"],"new-active-attempt")
        self.assertEqual(result["status"],"initializing")
        result=self.store.get("job-1")
        event=result["events"][-1]
        self.assertEqual(event["event_type"],"superseded_attempt_status_observed")
        self.assertEqual(event["attempt_id"],first_attempt)
        self.assertEqual(event["outcome"],"failed")
        self.assertEqual(event["publish_id"],"old-publish-id")
        self.assertEqual(event["operator_id"],"old-operator")
        self.assertIsNone(result["video_id"])

    def test_late_superseded_tiktok_inbox_delivery_blocks_retry_after_new_attempt_failed(self):
        first_attempt = "old-inbox-poll-attempt"
        self.store.begin("job-1","Old attempt",True,"old-operator",first_attempt,False,False)
        self.store.set_initialized(
            "job-1",first_attempt,"old-publish-id",
            {"creator_username":"creator","creator_nickname":"Creator"},
        )
        self.store.mark_uncertain("job-1",first_attempt,"old request timed out")
        with self.store.db() as connection:
            connection.execute(
                "UPDATE tiktok_publications SET updated_at=? WHERE job_id=?",
                ("2026-01-01T00:00:00+00:00","job-1"),
            )
        self.store.reconcile(
            "job-1","not_published","reviewer","Verified no post existed",confirmed=True,
        )
        self.store.begin("job-1","New attempt",True,"new-operator","new-inbox-current",False,False)
        self.store.mark_failed_before_remote("job-1","new-inbox-current","local preflight failure")
        result=self.store.mark_status(
            "job-1",first_attempt,"SEND_TO_USER_INBOX",["late-inbox-video"],None,
        )
        self.assertEqual(result["attempt_id"],"new-inbox-current")
        self.assertEqual(result["status"],"reconciliation_required")
        result=self.store.get("job-1")
        event=result["events"][-1]
        self.assertEqual(event["event_type"],"superseded_attempt_status_observed")
        self.assertEqual(event["attempt_id"],first_attempt)
        self.assertEqual(event["outcome"],"send_to_inbox")
        self.assertEqual(event["publish_id"],"old-publish-id")
        self.assertEqual(event["video_id"],"late-inbox-video")
        self.assertEqual(event["operator_id"],"old-operator")
        with self.assertRaises(TikTokPublishError):
            self.store.begin("job-1","Duplicate retry",True,"new-operator","third-inbox-attempt",False,False)

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

    def test_tiktok_disclosure_mapping_rejects_malformed_types(self):
        from tiktok_disclosure import build_tiktok_disclosure, TikTokDisclosureError

        for invalid in (None, True, 0, [], {}, "UNKNOWN", " ai_generated "):
            with self.subTest(invalid=invalid):
                with self.assertRaises(TikTokDisclosureError):
                    build_tiktok_disclosure(invalid)

    def test_missing_tiktok_disclosure_acknowledgement_blocks_before_network(self):
        policy = evaluate_content_policy({
            "rights": {"visuals_cleared": True, "audio_cleared": True,
                       "likeness_authorized": True},
            "synthetic_media_status": "ai_generated",
            "platforms": ["tiktok"],
            "platform_disclosures": {"tiktok_ai_generated_content": False},
            "factual_claims_verified": True,
            "originality_notes": "Original animation.",
        })
        self.assertIn(
            "platform_disclosures.tiktok_ai_generated_content",
            policy["approval_blockers"],
        )
        self.prod.artifact("job-1", "script", "text", None, {
            "script": "Approved test script", "policy_preflight": policy
        })
        self.prod.stage("job-1", "rendered", "review_pending")
        with self.queue.db() as connection:
            connection.execute(
                "UPDATE pipeline_jobs SET status='review_pending' WHERE id=?",
                ("job-1",),
            )
        with self.assertRaisesRegex(ReviewConflict, "Policy approval blockers"):
            self.review.decide("job-1", "approved", "reviewer-1")
        self.assertEqual(self.transport.calls, [])
        self.assertIsNone(self.store.get("job-1"))

    def test_tiktok_non_ai_content_uses_false_aigc_field(self):
        policy = evaluate_content_policy({
            "rights": {"visuals_cleared": True, "audio_cleared": True,
                       "likeness_authorized": True},
            "synthetic_media_status": "none",
            "platforms": ["tiktok"],
            "factual_claims_verified": True,
            "originality_notes": "Original filmed footage.",
        })
        self.prod.artifact("job-1", "script", "text", None, {
            "script": "Approved test script", "policy_preflight": policy
        })
        self.prod.stage("job-1", "rendered", "review_pending")
        with self.queue.db() as connection:
            connection.execute(
                "UPDATE pipeline_jobs SET status='review_pending' WHERE id=?",
                ("job-1",),
            )
        self.review.decide("job-1", "approved", "reviewer-1")
        self.transport.calls.clear()
        self.publisher.publish_private_approved(
            "job-1", self.media, self.review, "Filmed short", "operator-1",
            explicit_consent=True, privacy_level="SELF_ONLY",
        )
        init = next(call for call in self.transport.calls if "/video/init/" in call[0])
        body = json.loads(init[2].decode("utf-8"))
        self.assertIs(body["post_info"]["is_aigc"], False)

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

    def test_init_timeout_blocks_duplicate_tiktok_request_until_reconciliation(self):
        class InitTimeoutTransport:
            def __init__(self):
                self.calls = []

            def __call__(self, url, headers, body, timeout, method="POST"):
                self.calls.append((url, method))
                if url.endswith("/v2/post/publish/video/init/"):
                    raise TimeoutError("simulated response lost after request dispatch")
                return 200, json.dumps({
                    "data": {
                        "privacy_level_options": ["SELF_ONLY"],
                        "max_video_post_duration_sec": 600,
                    },
                    "error": {"code": "ok"},
                }).encode("utf-8")

        transport = InitTimeoutTransport()
        publisher = TikTokPublisher(
            self.store, "test-token", transport,
            media_inspector=FakeMediaInspector(),
        )
        with self.assertRaisesRegex(TikTokPublishError, "outcome is uncertain"):
            publisher.publish_private_approved(
                "job-1", self.media, self.review, "Caption", "operator-1",
                explicit_consent=True, privacy_level="SELF_ONLY",
            )
        record = self.store.get("job-1")
        self.assertEqual(record["status"], "reconciliation_required")
        self.assertIsNone(record["publish_id"])
        self.assertEqual(record["events"][-1]["event_type"], "remote_outcome_uncertain")
        first_attempt_calls = len(transport.calls)

        with self.assertRaisesRegex(TikTokPublishError, "unresolved"):
            publisher.publish_private_approved(
                "job-1", self.media, self.review, "Caption", "operator-1",
                explicit_consent=True, privacy_level="SELF_ONLY",
            )
        self.assertEqual(len(transport.calls), first_attempt_calls)
        self.assertEqual(
            sum(url.endswith("/v2/post/publish/video/init/") for url, _ in transport.calls),
            1,
        )

    def test_chunk_upload_timeout_preserves_publish_id_and_blocks_duplicate_init(self):
        class ChunkTimeoutTransport:
            def __init__(self):
                self.calls = []

            def __call__(self, url, headers, body, timeout, method="POST"):
                self.calls.append((url, method))
                if url.startswith("https://upload.us.tiktokapis.com/"):
                    raise TimeoutError("simulated media chunk response lost")
                if url.endswith("/v2/post/publish/creator_info/query/"):
                    payload = {
                        "data": {
                            "privacy_level_options": ["SELF_ONLY"],
                            "max_video_post_duration_sec": 600,
                        },
                        "error": {"code": "ok"},
                    }
                else:
                    payload = {
                        "data": {
                            "publish_id": "publish-chunk-uncertain",
                            "upload_url": "https://upload.us.tiktokapis.com/video/?token=test",
                        },
                        "error": {"code": "ok"},
                    }
                return 200, json.dumps(payload).encode("utf-8")

        transport = ChunkTimeoutTransport()
        publisher = TikTokPublisher(
            self.store, "test-token", transport,
            media_inspector=FakeMediaInspector(),
        )
        with self.assertRaisesRegex(TikTokPublishError, "outcome is uncertain"):
            publisher.publish_private_approved(
                "job-1", self.media, self.review, "Caption", "operator-1",
                explicit_consent=True, privacy_level="SELF_ONLY",
            )
        record = self.store.get("job-1")
        self.assertEqual(record["status"], "reconciliation_required")
        self.assertEqual(record["publish_id"], "publish-chunk-uncertain")
        first_attempt_calls = len(transport.calls)

        with self.assertRaisesRegex(TikTokPublishError, "unresolved"):
            publisher.publish_private_approved(
                "job-1", self.media, self.review, "Caption", "operator-1",
                explicit_consent=True, privacy_level="SELF_ONLY",
            )
        self.assertEqual(len(transport.calls), first_attempt_calls)
        self.assertEqual(
            sum(url.endswith("/v2/post/publish/video/init/") for url, _ in transport.calls),
            1,
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

    def test_status_refresh_compare_and_set_rejects_suppressed_state_write(self):
        self.publisher.publish_private_approved(
            "job-1", self.media, self.review, "AI generated short", "operator-1",
            explicit_consent=True, privacy_level="SELF_ONLY",
        )
        before = self.store.get("job-1")
        attempt_id = before["attempt_id"]
        with self.store.db() as connection:
            connection.execute("""
                CREATE TRIGGER suppress_tiktok_status_update
                BEFORE UPDATE ON tiktok_publications
                WHEN NEW.status='processing'
                BEGIN SELECT RAISE(IGNORE); END
            """)
        with self.assertRaisesRegex(TikTokPublishError, "state changed during status refresh"):
            self.store.mark_status(
                "job-1", attempt_id, "PROCESSING_UPLOAD", [], None
            )
        after = self.store.get("job-1")
        self.assertEqual(after["status"], before["status"])
        self.assertEqual(after["attempt_id"], attempt_id)
        self.assertFalse(any(
            event["event_type"] == "status_refreshed"
            for event in after["events"]
        ))

    def test_stale_status_response_cannot_overwrite_changed_source_state(self):
        self.publisher.publish_private_approved(
            "job-1", self.media, self.review, "AI generated short", "operator-1",
            explicit_consent=True, privacy_level="SELF_ONLY",
        )
        attempt_id = self.store.get("job-1")["attempt_id"]
        current = self.store.mark_status(
            "job-1", attempt_id, "PROCESSING_UPLOAD", [], None
        )
        event_count = len(current["events"])
        with self.assertRaisesRegex(TikTokPublishError, "state changed while the status request"):
            self.store.mark_status(
                "job-1", attempt_id, "PUBLISH_COMPLETE", ["stale-video-id"], None,
                expected_status="uploading",
            )
        after = self.store.get("job-1")
        self.assertEqual(after["status"], "processing")
        self.assertIsNone(after["video_id"])
        self.assertEqual(len(after["events"]), event_count)

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

    def test_late_publish_timeout_cannot_override_processing_status(self):
        self.publisher.publish_private_approved(
            "job-1", self.media, self.review, "AI generated short", "operator-1",
            explicit_consent=True, privacy_level="SELF_ONLY",
        )
        attempt_id = self.store.get("job-1")["attempt_id"]
        processing = self.store.mark_status(
            "job-1", attempt_id, "PROCESSING_UPLOAD", [], None
        )
        before = len(processing["events"])
        self.store.mark_uncertain(
            "job-1", attempt_id, "late upload transport timeout",
        )
        after = self.store.get("job-1")
        self.assertEqual(after["status"], "processing")
        self.assertEqual(len(after["events"]), before)

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

    def test_stale_poll_error_does_not_schedule_retry_for_changed_state(self):
        self.publisher.publish_private_approved(
            "job-1", self.media, self.review, "AI generated short", "operator-1",
            explicit_consent=True, privacy_level="SELF_ONLY",
        )
        attempt_id = self.store.get("job-1")["attempt_id"]
        self.store.mark_status("job-1", attempt_id, "PROCESSING_UPLOAD", [], None)
        before = self.store.get("job-1")
        result = self.store.record_status_poll_error(
            "job-1", attempt_id, "late timeout from prior poll",
            expected_status="uploading",
        )
        self.assertFalse(result)
        after = self.store.get("job-1")
        self.assertEqual(after["status"], "processing")
        self.assertEqual(after["updated_at"], before["updated_at"])
        self.assertEqual(len(after["events"]), len(before["events"]))

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
                "UPDATE tiktok_publications SET updated_at=datetime('now','-30 seconds') WHERE job_id='job-1'"
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
                "UPDATE tiktok_publications SET updated_at=datetime('now','-90 seconds') WHERE job_id='job-1'"
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
        self.assertEqual(self.store.due_status_job_ids(limit=5, min_age_seconds=60), [])

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
