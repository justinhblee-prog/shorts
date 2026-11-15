import os
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

    def test_upload_requires_approval(self):
        self.prod.create("job-2",{"brand":"Brain Glitch","region":"US",
                                  "language":"English","topic":"Focus"})
        with self.assertRaises(YouTubeUploadError):
            self.publisher.upload_approved("job-2",self.media,self.review,"Title")

    def test_upload_is_always_private_and_persists_source_stats(self):
        result=self.publisher.upload_approved("job-1",self.media,self.review,
                                              "A useful short","Description")
        self.assertEqual(result["status"],"uploaded")
        self.assertEqual(result["privacy_status"],"private")
        self.assertEqual(result["video_id"],"yt-video-123")
        self.assertEqual(self.service._videos.body["status"]["privacyStatus"],"private")
        self.assertEqual(result["snapshots"][0]["view_count"],123)

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
            "job-1","not_uploaded",None,"Checked channel uploads; no matching private video"
        )
        self.assertEqual(reconciled["status"],"failed")
        retried=YouTubePublisher(self.uploads,FakeService()).upload_approved(
            "job-1",self.media,self.review,"Sleep short"
        )
        self.assertEqual(retried["status"],"uploaded")

    def test_reconciliation_requires_a_note_and_rejects_conflicting_outcome(self):
        with self.assertRaises(YouTubeUploadError):
            self.uploads.reconcile("missing","uploaded","video-id","checked")
        self.uploads.begin("job-1","Sleep short","")
        with self.assertRaises(YouTubeUploadError):
            self.uploads.reconcile("job-1","uploaded","yt-video-1","checked too early")
        self.uploads.mark_reconciliation_required("job-1","Simulated stale upload")
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
