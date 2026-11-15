import tempfile
import unittest
from pathlib import Path

from youtube_publishing import YouTubeUploadStore
from metrics_collector import run_once
from metrics_collector import OWNER_ID


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


class MetricsCollectorRunTests(unittest.TestCase):
    class Store:
        def __init__(self, lease=True):
            self.lease = lease
            self.states = []
            self.released = False

        def acquire_metrics_collector_lease(self, owner_id, lease_seconds=300):
            return "fake-lease-token" if self.lease else None

        def renew_metrics_collector_lease(self, owner_id, lease_token, lease_seconds=300):
            self.renewed = (owner_id, lease_token)
            return self.lease
        def release_metrics_collector_lease(self, owner_id, lease_token):
            self.released = (owner_id, lease_token) == (OWNER_ID, "fake-lease-token")
            return self.released

        def record_metrics_collection(self, status, **kwargs):
            self.states.append((status, kwargs))

    class Publisher:
        def __init__(self, error=None):
            self.error = error

        def refresh_due_metrics(self, **kwargs):
            if self.error:
                raise self.error
            return {"requested": 2, "collected": 2, "missing": [],
                    "source": "YouTube Data API v3"}

    def test_run_once_persists_success_and_releases_lease(self):
        store = self.Store()
        result = run_once(store, self.Publisher())
        self.assertEqual(result["collected"], 2)
        self.assertEqual([state for state, _ in store.states], ["running", "succeeded"])
        self.assertTrue(store.released)

    def test_run_once_persists_failure_and_releases_lease(self):
        store = self.Store()
        with self.assertRaisesRegex(RuntimeError, "provider unavailable"):
            run_once(store, self.Publisher(RuntimeError("provider unavailable")))
        self.assertEqual([state for state, _ in store.states], ["running", "failed"])
        self.assertEqual(store.states[-1][1]["error"], "RuntimeError")
        self.assertTrue(store.released)

    def test_run_once_skips_when_another_collector_holds_lease(self):
        store = self.Store(lease=False)
        result = run_once(store, self.Publisher())
        self.assertTrue(result["skipped"])
        self.assertEqual(store.states, [])
        self.assertFalse(store.released)


class LeaseHeartbeatTests(unittest.TestCase):
    def test_heartbeat_assertion_detects_fencing_loss_without_waiting_for_timer(self):
        from metrics_collector import LeaseHeartbeat, CollectorLeaseLost
        heartbeat = LeaseHeartbeat(lambda: False, lease_seconds=30)
        with self.assertRaises(CollectorLeaseLost):
            heartbeat.assert_owned()
        self.assertTrue(heartbeat.lost.is_set())

    def test_heartbeat_uses_a_bounded_fraction_of_lease_duration(self):
        from metrics_collector import LeaseHeartbeat
        heartbeat = LeaseHeartbeat(lambda: True, lease_seconds=300)
        self.assertLess(heartbeat.interval, heartbeat.lease_seconds)
        self.assertLessEqual(heartbeat.interval, 30)


if __name__ == "__main__":
    unittest.main()
