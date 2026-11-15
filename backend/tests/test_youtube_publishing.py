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
