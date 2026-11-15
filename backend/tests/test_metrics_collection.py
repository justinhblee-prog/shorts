import tempfile
import unittest
from pathlib import Path

from youtube_publishing import YouTubeUploadStore


class MetricsCollectionStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = YouTubeUploadStore(str(Path(self.temp.name) / "metrics.sqlite3"))

    def tearDown(self):
        self.temp.cleanup()

    def _uploaded_video(self, video_id):
        with self.store.db() as connection:
            connection.execute(
                """INSERT INTO youtube_uploads
                   (job_id,video_id,status,title,description,updated_at)
                   VALUES(?,?,'uploaded','Test','',?)""",
                ("job-" + video_id, video_id, "2026-11-15T00:00:00+00:00"),
            )

    def test_collection_status_starts_unknown_and_reports_coverage(self):
        self._uploaded_video("yt-one")
        self._uploaded_video("yt-two")
        self.store.snapshot("yt-one", {"viewCount": "100", "likeCount": "5"})
        status = self.store.metrics_collection_status(freshness_seconds=21600)
        self.assertEqual(status["status"], "not_started")
        self.assertEqual(status["coverage"]["uploaded_videos"], 2)
        self.assertEqual(status["coverage"]["with_snapshot"], 1)
        self.assertEqual(status["coverage"]["without_snapshot"], 1)
        self.assertEqual(status["coverage"]["stale_snapshots"], 1)
        self.assertTrue(status["read_only"])

    def test_success_and_failure_are_persisted_without_losing_last_success(self):
        self.store.record_metrics_collection(
            "succeeded", requested=4, collected=3, missing=1
        )
        first = self.store.metrics_collection_status()
        self.assertEqual(first["status"], "succeeded")
        self.assertEqual(first["last_batch"], {
            "requested": 4, "collected": 3, "missing": 1
        })
        last_success = first["last_success_at"]

        self.store.record_metrics_collection("failed", error="HttpError")
        failed = self.store.metrics_collection_status()
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["last_error"], "HttpError")
        self.assertEqual(failed["last_success_at"], last_success)

        self.store.record_metrics_collection("succeeded", requested=0, collected=0)
        recovered = self.store.metrics_collection_status()
        self.assertEqual(recovered["status"], "succeeded")
        self.assertIsNone(recovered["last_error"])
        self.assertGreaterEqual(recovered["last_success_at"], last_success)

    def test_invalid_collection_state_is_rejected(self):
        with self.assertRaises(ValueError):
            self.store.record_metrics_collection("unknown")


if __name__ == "__main__":
    unittest.main()
