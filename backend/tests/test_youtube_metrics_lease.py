import tempfile
import unittest
import threading
from datetime import datetime, timezone
from unittest.mock import patch
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

    def test_acquire_metrics_lease_samples_clock_after_write_lock(self):
        sampled = threading.Event()
        started = threading.Event()
        observed = {}
        decision = datetime(2036, 7, 8, 9, 10, 11, tzinfo=timezone.utc)

        class ControlledDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                sampled.set()
                return decision

        def acquire():
            started.set()
            try:
                observed["token"] = self.store.acquire_metrics_collector_lease("worker-a", 60)
            except Exception as exc:
                observed["error"] = exc

        with self.store.db() as holder:
            holder.execute("BEGIN IMMEDIATE")
            with patch("youtube_publishing.datetime", ControlledDateTime):
                thread = threading.Thread(target=acquire)
                thread.start()
                self.assertTrue(started.wait(1))
                self.assertFalse(sampled.wait(0.1), "metrics lease clock sampled before write lock")
                holder.commit()
                thread.join(2)
            self.assertFalse(thread.is_alive(), "metrics lease acquisition did not finish")

        self.assertNotIn("error", observed)
        self.assertTrue(observed["token"])
        with self.store.db() as connection:
            row = connection.execute(
                "SELECT updated_at,lease_until FROM youtube_metrics_collector_lease WHERE id=1"
            ).fetchone()
        self.assertEqual(row["updated_at"], decision.isoformat())
        self.assertEqual(float(row["lease_until"]), decision.timestamp() + 60)

    def test_renew_metrics_lease_samples_clock_after_write_lock(self):
        token = self.store.acquire_metrics_collector_lease("worker-a", 60, now=1000)
        with self.store.db() as connection:
            connection.execute(
                "UPDATE youtube_metrics_collector_lease SET lease_until=9999999999 WHERE id=1"
            )
        sampled = threading.Event()
        started = threading.Event()
        observed = {}
        decision = datetime(2036, 7, 8, 9, 10, 12, tzinfo=timezone.utc)

        class ControlledDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                sampled.set()
                return decision

        def renew():
            started.set()
            try:
                observed["renewed"] = self.store.renew_metrics_collector_lease(
                    "worker-a", token, 120
                )
            except Exception as exc:
                observed["error"] = exc

        with self.store.db() as holder:
            holder.execute("BEGIN IMMEDIATE")
            with patch("youtube_publishing.datetime", ControlledDateTime):
                thread = threading.Thread(target=renew)
                thread.start()
                self.assertTrue(started.wait(1))
                self.assertFalse(sampled.wait(0.1), "metrics lease renewal clock sampled before write lock")
                holder.commit()
                thread.join(2)
            self.assertFalse(thread.is_alive(), "metrics lease renewal did not finish")

        self.assertNotIn("error", observed)
        self.assertTrue(observed["renewed"])
        with self.store.db() as connection:
            row = connection.execute(
                "SELECT updated_at,lease_until FROM youtube_metrics_collector_lease WHERE id=1"
            ).fetchone()
        self.assertEqual(row["updated_at"], decision.isoformat())
        self.assertEqual(float(row["lease_until"]), decision.timestamp() + 120)

    def test_metrics_collection_and_snapshot_clocks_wait_for_write_lock(self):
        token = self.store.acquire_metrics_collector_lease("worker-a", 60, now=1000)
        with self.store.db() as connection:
            connection.execute(
                "UPDATE youtube_metrics_collector_lease SET lease_until=9999999999 WHERE id=1"
            )

        def assert_clock_waits(operation, decision, failure_message):
            sampled = threading.Event()
            started = threading.Event()
            outcome = {}

            class ControlledDateTime(datetime):
                @classmethod
                def now(cls, tz=None):
                    sampled.set()
                    return decision

            def run():
                started.set()
                try:
                    operation()
                except Exception as exc:
                    outcome["error"] = exc

            with self.store.db() as holder:
                holder.execute("BEGIN IMMEDIATE")
                with patch("youtube_publishing.datetime", ControlledDateTime):
                    thread = threading.Thread(target=run)
                    thread.start()
                    self.assertTrue(started.wait(1))
                    self.assertFalse(sampled.wait(0.1), failure_message)
                    holder.commit()
                    thread.join(2)
                self.assertFalse(thread.is_alive(), "metrics write did not finish")
            self.assertNotIn("error", outcome)

        collection_time = datetime(2036, 7, 8, 9, 10, 13, tzinfo=timezone.utc)
        assert_clock_waits(
            lambda: self.store.record_metrics_collection(
                "running", lease_owner="worker-a", lease_token=token
            ),
            collection_time,
            "metrics collection timestamp sampled before write lock",
        )
        with self.store.db() as connection:
            state = connection.execute(
                "SELECT last_attempt_at,updated_at FROM youtube_metrics_collection_state WHERE id=1"
            ).fetchone()
        self.assertEqual(state["last_attempt_at"], collection_time.isoformat())
        self.assertEqual(state["updated_at"], collection_time.isoformat())

        snapshot_time = datetime(2036, 7, 8, 9, 10, 14, tzinfo=timezone.utc)
        assert_clock_waits(
            lambda: self.store.snapshot(
                "video-lock-clock", {"viewCount": "42"},
                lease_owner="worker-a", lease_token=token,
            ),
            snapshot_time,
            "metrics snapshot timestamp sampled before write lock",
        )
        with self.store.db() as connection:
            snapshot = connection.execute(
                "SELECT collected_at FROM youtube_video_snapshots WHERE video_id='video-lock-clock'"
            ).fetchone()
        self.assertEqual(snapshot["collected_at"], snapshot_time.isoformat())

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
