import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from production_pipeline import ProductionStore
from review_workflow import ReviewStore
from youtube_publishing import YouTubeUploadStore, YouTubePublisher, YouTubeUploadError


class FakeRequest:
    def __init__(self,response): self.response=response
    def next_chunk(self): return None,self.response
    def execute(self): return self.response


class FakeVideos:
    def insert(self,**kwargs):
        self.body=kwargs["body"]
        self.media=kwargs["media_body"]
        return FakeRequest({"id":"yt-video-123"})
    def list(self,**kwargs):
        return FakeRequest({"items":[{"statistics":{"viewCount":"123","likeCount":"8",
                            "commentCount":"2"},"status":{"privacyStatus":"private"}}]})


class FakeService:
    def __init__(self): self._videos=FakeVideos()
    def videos(self): return self._videos


class TimeoutRequest:
    def next_chunk(self):
        raise TimeoutError("connection dropped after request started")


class TimeoutVideos:
    def __init__(self): self.insert_calls=0
    def insert(self,**kwargs):
        self.insert_calls+=1
        return TimeoutRequest()


class TimeoutService:
    def __init__(self): self._videos=TimeoutVideos()
    def videos(self): return self._videos


class YouTubePublishingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=os.path.join(self.tmp.name,"db.sqlite3")
        self.prod=ProductionStore(self.db)
        self.review=ReviewStore(self.db)
        self.uploads=YouTubeUploadStore(self.db)
        self.prod.create("job-1",{"brand":"Brain Glitch","region":"US",
                                  "language":"English","topic":"Sleep"})
        self.prod.stage("job-1","rendered","review_pending")
        self.prod.artifact("job-1","rendering","video",
                           "https://media.example/video.mp4",{})
        self.review.decide("job-1","approved","reviewer-1")
        os.environ["NEXUS_MEDIA_DIR"]=self.tmp.name
        self.media=os.path.join(self.tmp.name,"video.mp4")
        Path(self.media).write_bytes(b"fake-media-for-unit-test")
        self.service=FakeService()
        self.publisher=YouTubePublisher(self.uploads,self.service)

    def tearDown(self): self.tmp.cleanup()

    def test_late_upload_completion_cannot_override_reconciled_not_uploaded(self):
        first_attempt=self.uploads.begin("job-1", "Title", "Description")
        self.uploads.mark_reconciliation_required("job-1", "timeout",first_attempt["attempt_id"])
        self.uploads.reconcile("job-1", "not_uploaded", note="Checked YouTube Studio")
        # A retry can begin after explicit no-upload confirmation. The stale
        # request must not finalize or overwrite that newer attempt.
        second_attempt=self.uploads.begin("job-1", "Retry", "")
        self.assertNotEqual(first_attempt["attempt_id"],second_attempt["attempt_id"])
        with self.assertRaises(YouTubeUploadError):
            self.uploads.finish("job-1", "late-video-id",first_attempt["attempt_id"])
        result = self.uploads.get("job-1")
        self.assertEqual(result["status"], "late_success_review_required")
        self.assertEqual(result["video_id"], "late-video-id")
        self.assertEqual(result["events"][-1]["event_type"], "late_remote_success")
        self.assertEqual(result["events"][-1]["attempt_id"],first_attempt["attempt_id"])
        with self.assertRaisesRegex(YouTubeUploadError, "blocked"):
            self.uploads.begin("job-1", "Retry", "")
        resolved=self.uploads.resolve_late_success(
            "job-1","reviewer-ops","Confirmed late video ID in YouTube Studio","late-video-id"
        )
        self.assertEqual(resolved["status"], "uploaded")
        self.assertEqual(resolved["video_id"], "late-video-id")
        self.assertEqual(resolved["events"][-1]["operator_id"], "reviewer-ops")
        self.assertEqual(resolved["events"][-1]["attempt_id"],first_attempt["attempt_id"])

    def test_operator_can_keep_current_video_when_stale_duplicate_arrives(self):
        first=self.uploads.begin("job-1","First attempt","")
        self.uploads.mark_reconciliation_required(
            "job-1","first request timed out",first["attempt_id"]
        )
        self.uploads.reconcile(
            "job-1","not_uploaded",note="Verified no upload at that time"
        )
        second=self.uploads.begin("job-1","Second attempt","")
        self.uploads.finish("job-1","current-video",second["attempt_id"])
        with self.assertRaises(YouTubeUploadError):
            self.uploads.finish("job-1","late-duplicate-video",first["attempt_id"])
        pending=self.uploads.get("job-1")
        self.assertEqual(pending["status"],"late_success_review_required")
        self.assertEqual(pending["video_id"],"current-video")
        late_ids=[event["video_id"] for event in pending["events"]
                  if event["event_type"]=="late_remote_success"]
        self.assertEqual(late_ids,["late-duplicate-video"])
        late_event=next(event for event in pending["events"]
                        if event["event_type"]=="late_remote_success")
        self.assertEqual(late_event["attempt_id"],first["attempt_id"])
        with self.assertRaisesRegex(YouTubeUploadError,"Choose the currently recorded"):
            self.uploads.resolve_late_success(
                "job-1","reviewer","invalid unrecorded ID","not-a-video"
            )
        resolved=self.uploads.resolve_late_success(
            "job-1","reviewer","Retained the already confirmed canonical video","current-video"
        )
        self.assertEqual(resolved["status"],"uploaded")
        self.assertEqual(resolved["video_id"],"current-video")
        self.assertEqual(resolved["events"][-1]["attempt_id"],second["attempt_id"])

    def test_superseded_attempt_uncertainty_blocks_new_attempt(self):
        first=self.uploads.begin("job-1","First attempt","")
        self.uploads.mark_reconciliation_required("job-1","first attempt timed out",first["attempt_id"])
        self.uploads.reconcile("job-1","not_uploaded",note="Checked YouTube Studio")
        second=self.uploads.begin("job-1","Retry attempt","")
        self.uploads.mark_reconciliation_required(
            "job-1","old request ended after retry began",first["attempt_id"]
        )
        result=self.uploads.get("job-1")
        self.assertEqual(result["status"],"reconciliation_required")
        self.assertEqual(result["events"][-1]["event_type"],"superseded_attempt_uncertain")
        with self.assertRaises(YouTubeUploadError):
            self.uploads.begin("job-1","Third attempt","")

    def test_existing_upload_tables_migrate_attempt_audit_columns(self):
        legacy_db=os.path.join(self.tmp.name,"legacy.sqlite3")
        import sqlite3
        with sqlite3.connect(legacy_db) as connection:
            connection.executescript("""
              CREATE TABLE youtube_uploads(
                job_id TEXT PRIMARY KEY,video_id TEXT,status TEXT NOT NULL,
                privacy_status TEXT NOT NULL DEFAULT 'private',title TEXT NOT NULL,
                description TEXT NOT NULL,uploaded_at TEXT,error TEXT,updated_at TEXT NOT NULL
              );
              CREATE TABLE youtube_upload_events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT NOT NULL,
                event_type TEXT NOT NULL,outcome TEXT,video_id TEXT,
                operator_id TEXT NOT NULL,note TEXT NOT NULL DEFAULT '',
                previous_status TEXT,resulting_status TEXT,created_at TEXT NOT NULL
              );
              CREATE TABLE production_runs(job_id TEXT PRIMARY KEY,status TEXT);
              CREATE TABLE review_decisions(id INTEGER PRIMARY KEY,job_id TEXT,decision TEXT);
            """)
        migrated=YouTubeUploadStore(legacy_db)
        with migrated.db() as connection:
            upload_columns={row["name"] for row in connection.execute("PRAGMA table_info(youtube_uploads)")}
            event_columns={row["name"] for row in connection.execute("PRAGMA table_info(youtube_upload_events)")}
        self.assertIn("attempt_id",upload_columns)
        self.assertIn("attempt_id",event_columns)

    def test_finish_requires_active_upload_state(self):
        with self.assertRaises(YouTubeUploadError):
            self.uploads.finish("missing-job", "video-id")

    def test_preflight_failure_is_audited_without_remote_request(self):
        attempt=self.uploads.begin("job-1","Bad media","")
        self.uploads.fail("job-1","Unsupported media extension",attempt["attempt_id"])
        result=self.uploads.get("job-1")
        self.assertEqual(result["status"],"failed")
        event=result["events"][-1]
        self.assertEqual(event["event_type"],"upload_preflight_failed")
        self.assertEqual(event["attempt_id"],attempt["attempt_id"])

    def test_upload_requires_approval(self):
        self.prod.create("job-2",{"brand":"Brain Glitch","region":"US",
                                  "language":"English","topic":"Focus"})
        with self.assertRaises(YouTubeUploadError):
            self.publisher.upload_approved("job-2",self.media,self.review,"Title")

    def test_prior_approval_is_invalidated_by_a_later_revision_decision(self):
        self.review.decide("job-1","approved","reviewer-1","Initial approval")
        self.prod.stage("job-1","review","review_pending")
        self.review.decide("job-1","revision_requested","reviewer-2","Correct captions")
        with self.assertRaisesRegex(YouTubeUploadError,"latest human review decision"):
            self.publisher.upload_approved(
                "job-1",self.media,self.review,"Sleep short"
            )
        self.assertIsNone(self.uploads.get("job-1"))

    def test_current_production_status_must_still_be_approved(self):
        self.prod.stage("job-1","review","review_pending")
        with self.assertRaisesRegex(YouTubeUploadError,"must remain approved"):
            self.publisher.upload_approved(
                "job-1",self.media,self.review,"Sleep short"
            )
        self.assertIsNone(self.uploads.get("job-1"))

    def test_upload_is_always_private_and_persists_source_stats(self):
        result=self.publisher.upload_approved("job-1",self.media,self.review,
                                              "A useful short","Description")
        self.assertEqual(result["status"],"uploaded")
        self.assertEqual(result["privacy_status"],"private")
        self.assertEqual(result["video_id"],"yt-video-123")
        self.assertEqual(result["events"][-1]["event_type"],"upload_confirmed")
        self.assertEqual(result["events"][-1]["video_id"],"yt-video-123")
        self.assertEqual(result["events"][-1]["attempt_id"],result["attempt_id"])
        self.assertEqual(result["events"][0]["event_type"],"upload_attempt_started")
        self.assertEqual(self.service._videos.body["status"]["privacyStatus"],"private")
        self.assertEqual(result["snapshots"][0]["view_count"],123)

    def test_stale_error_cannot_downgrade_confirmed_upload(self):
        uploaded=self.publisher.upload_approved(
            "job-1",self.media,self.review,"Confirmed short"
        )
        self.assertEqual(uploaded["status"],"uploaded")
        self.uploads.mark_reconciliation_required(
            "job-1","late stale worker exception","obsolete-attempt-token"
        )
        current=self.uploads.get("job-1")
        self.assertEqual(current["status"],"uploaded")
        self.assertEqual(current["video_id"],"yt-video-123")
        self.assertEqual(current["events"][-1]["event_type"],"superseded_attempt_uncertain")
        self.uploads.mark_reconciliation_required(
            "job-1","post-confirmation cleanup exception",uploaded["attempt_id"]
        )
        current=self.uploads.get("job-1")
        self.assertEqual(current["status"],"uploaded")
        self.assertEqual(current["events"][-1]["event_type"],"post_confirmation_worker_error")

    def test_upload_is_idempotent_after_success(self):
        first=self.publisher.upload_approved("job-1",self.media,self.review,"Title")
        second=self.publisher.upload_approved("job-1",self.media,self.review,"Title")
        self.assertEqual(first["video_id"],second["video_id"])

    def test_ambiguous_timeout_blocks_duplicate_retry_until_operator_reconciles(self):
        uncertain_service=TimeoutService()
        uncertain_publisher=YouTubePublisher(self.uploads,uncertain_service)
        with self.assertRaises(YouTubeUploadError):
            uncertain_publisher.upload_approved(
                "job-1",self.media,self.review,"Sleep short"
            )
        record=self.uploads.get("job-1")
        self.assertEqual(record["status"],"reconciliation_required")
        self.assertIn("uncertain",record["error"].lower())
        self.assertEqual(record["events"][-1]["event_type"],"upload_outcome_uncertain")
        self.assertEqual(record["events"][-1]["attempt_id"],record["attempt_id"])

        with self.assertRaises(YouTubeUploadError):
            uncertain_publisher.upload_approved(
                "job-1",self.media,self.review,"Sleep short"
            )
        self.assertEqual(uncertain_service._videos.insert_calls,1)

        reconciled=self.uploads.reconcile(
            "job-1","uploaded","yt-video-recovered","Found matching private video in YouTube Studio"
        )
        self.assertEqual(reconciled["status"],"uploaded")
        self.assertEqual(reconciled["video_id"],"yt-video-recovered")

    def test_operator_confirms_no_remote_upload_before_retry_is_allowed(self):
        uncertain_publisher=YouTubePublisher(self.uploads,TimeoutService())
        with self.assertRaises(YouTubeUploadError):
            uncertain_publisher.upload_approved(
                "job-1",self.media,self.review,"Sleep short"
            )
        reconciled=self.uploads.reconcile(
            "job-1","not_uploaded",None,"Checked channel uploads; no matching private video",
            "reviewer-audit"
        )
        self.assertEqual(reconciled["status"],"failed")
        event=reconciled["events"][-1]
        self.assertEqual(event["operator_id"],"reviewer-audit")
        self.assertEqual(event["outcome"],"not_uploaded")
        self.assertTrue(event["created_at"])
        retried=YouTubePublisher(self.uploads,FakeService()).upload_approved(
            "job-1",self.media,self.review,"Sleep short"
        )
        self.assertEqual(retried["status"],"uploaded")

    def test_reconciliation_requires_a_note_and_rejects_conflicting_outcome(self):
        with self.assertRaises(YouTubeUploadError):
            self.uploads.reconcile("missing","uploaded","video-id","checked")
        active=self.uploads.begin("job-1","Sleep short","")
        with self.assertRaises(YouTubeUploadError):
            self.uploads.reconcile("job-1","uploaded","yt-video-1","checked too early")
        self.uploads.mark_reconciliation_required("job-1","Simulated stale upload",active["attempt_id"])
        with self.assertRaises(YouTubeUploadError):
            self.uploads.reconcile("job-1","uploaded",None,"checked")
        reconciled=self.uploads.reconcile(
            "job-1","uploaded","yt-video-1","Verified in YouTube Studio"
        )
        with self.assertRaises(YouTubeUploadError):
            self.uploads.reconcile(
                "job-1","not_uploaded",None,"conflicting operator decision"
            )
        self.assertEqual(reconciled["video_id"],"yt-video-1")
        event_id=reconciled["events"][-1]["id"]
        with self.assertRaises(sqlite3.IntegrityError):
            with self.uploads.db() as connection:
                connection.execute(
                    "UPDATE youtube_upload_events SET note='tampered' WHERE id=?",
                    (event_id,)
                )
        with self.assertRaises(sqlite3.IntegrityError):
            with self.uploads.db() as connection:
                connection.execute(
                    "DELETE FROM youtube_upload_events WHERE id=?",(event_id,)
                )

    def test_active_upload_cannot_be_reconciled_early(self):
        self.uploads.begin("job-1","Sleep short","")
        with self.assertRaisesRegex(YouTubeUploadError,"active window"):
            self.uploads.reconcile(
                "job-1","not_uploaded",None,"Premature operator check"
            )

    def test_stale_upload_is_exposed_for_manual_reconciliation(self):
        previous=os.environ.get("NEXUS_UPLOAD_STALE_SECONDS")
        os.environ["NEXUS_UPLOAD_STALE_SECONDS"]="60"
        try:
            self.uploads.begin("job-1","Sleep short","")
            with self.uploads.db() as connection:
                connection.execute(
                    "UPDATE youtube_uploads SET updated_at=? WHERE job_id=?",
                    ("2020-01-01T00:00:00+00:00","job-1")
                )
            self.assertTrue(self.uploads.get("job-1")["reconciliation_required"])
            resolved=self.uploads.reconcile(
                "job-1","not_uploaded",None,"Verified no matching video in channel"
            )
            self.assertEqual(resolved["status"],"failed")
        finally:
            if previous is None:
                os.environ.pop("NEXUS_UPLOAD_STALE_SECONDS",None)
            else:
                os.environ["NEXUS_UPLOAD_STALE_SECONDS"]=previous

    def test_path_outside_media_root_rejected(self):
        outside=os.path.join(self.tmp.name,"..","outside.mp4")
        with self.assertRaises(YouTubeUploadError):
            self.publisher.upload_approved("job-1",outside,self.review,"Title")

    def test_unsupported_extension_rejected(self):
        bad=os.path.join(self.tmp.name,"payload.txt")
        Path(bad).write_text("not video")
        with self.assertRaises(YouTubeUploadError):
            self.publisher.upload_approved("job-1",bad,self.review,"Title")

    def test_missing_media_rejected(self):
        with self.assertRaises(YouTubeUploadError):
            self.publisher.upload_approved("job-1","/missing/video.mp4",
                                           self.review,"Title")


if __name__=="__main__":
    unittest.main()
