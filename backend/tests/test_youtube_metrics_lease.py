import tempfile
import unittest
from pathlib import Path

from youtube_publishing import YouTubeUploadStore


class YouTubeMetricsLeaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.temp.name) / "youtube-metrics.sqlite3")
        self.store = YouTubeUploadStore(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def test_metrics_lease_is_exclusive_and_token_fenced(self):
        first = self.store.acquire_metrics_collector_lease("worker-a", 60)
        self.assertTrue(first)
        self.assertIsNone(self.store.acquire_metrics_collector_lease("worker-a", 60))
        self.assertIsNone(self.store.acquire_metrics_collector_lease("worker-b", 60))
        self.assertTrue(
            self.store.renew_metrics_collector_lease("worker-a", first, 120)
        )
        self.assertFalse(
            self.store.renew_metrics_collector_lease("worker-b", first, 120)
        )
        self.assertTrue(self.store.release_metrics_collector_lease("worker-a", first))
        second = self.store.acquire_metrics_collector_lease("worker-b", 60)
        self.assertTrue(second)
        self.assertNotEqual(first, second)

    def test_expired_lease_cannot_be_renewed_by_previous_owner(self):
        token = self.store.acquire_metrics_collector_lease(
            "worker-a", 60, now=1000
        )
        self.assertTrue(token)
        with self.store.db() as connection:
            connection.execute(
                "UPDATE youtube_metrics_collector_lease SET lease_until=0 WHERE id=1"
            )
        self.assertFalse(
            self.store.renew_metrics_collector_lease(
                "worker-a", token, 120, now=1001
            )
        )
        replacement = self.store.acquire_metrics_collector_lease(
            "worker-b", 60, now=1001
        )
        self.assertTrue(replacement)
        self.assertFalse(
            self.store.release_metrics_collector_lease("worker-a", token)
        )

    def test_replaced_lease_token_cannot_write_snapshot_or_state(self):
        token = self.store.acquire_metrics_collector_lease("worker-a", 60)
        with self.store.db() as connection:
            connection.execute(
                "UPDATE youtube_metrics_collector_lease SET token='replacement' WHERE id=1"
            )
        with self.assertRaisesRegex(RuntimeError, "stale write rejected"):
            self.store.snapshot(
                "video-stale", {"viewCount": "9"},
                lease_owner="worker-a", lease_token=token,
            )
        with self.assertRaisesRegex(RuntimeError, "stale write rejected"):
            self.store.record_metrics_collection(
                "succeeded", requested=1, collected=1,
                lease_owner="worker-a", lease_token=token,
            )
        with self.store.db() as connection:
            snapshots = connection.execute(
                "SELECT COUNT(*) FROM youtube_video_snapshots WHERE video_id='video-stale'"
            ).fetchone()[0]
            states = connection.execute(
                "SELECT COUNT(*) FROM youtube_metrics_collection_state"
            ).fetchone()[0]
        self.assertEqual(snapshots, 0)
        self.assertEqual(states, 0)


if __name__ == "__main__":
    unittest.main()
