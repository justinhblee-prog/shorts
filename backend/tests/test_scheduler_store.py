import os
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from scheduler_store import ScheduleStore
from queue_store import JobQueue


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "nexus.sqlite3")
        self.schedules = ScheduleStore(self.db)
        self.queue = JobQueue(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def schedule(self, start):
        return self.schedules.create("hourly", 3600,
            {"brand": "Brain Glitch", "region": "US", "language": "English",
             "topic": "Test"}, start_at=start.isoformat())

    def test_due_occurrence_dispatches_once_and_advances_schedule(self):
        now = datetime.now(timezone.utc)
        item = self.schedule(now - timedelta(minutes=5))
        result = self.schedules.dispatch_due(self.queue, now=now)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["pending"], 0)
        self.assertGreater(datetime.fromisoformat(self.schedules.get(item["id"])["next_run_at"]), now)
        job = self.queue.claim("test-worker", "localhost", job_type="short_video_production")
        self.assertIsNotNone(job)
        self.assertEqual(job["idempotency_key"],
                         "schedule:" + item["id"] + ":" + item["next_run_at"])

    def test_pending_outbox_is_replayed_idempotently(self):
        now = datetime.now(timezone.utc)
        item = self.schedule(now - timedelta(minutes=5))
        # Simulate a process crash after the schedule occurrence is reserved,
        # but before its outbox record is sent to the durable job queue.
        with self.schedules.db() as c:
            c.execute("BEGIN IMMEDIATE")
            due = item["next_run_at"]
            c.execute("""INSERT INTO schedule_dispatch_outbox
                (id,schedule_id,scheduled_for,payload_json,status,created_at)
                VALUES('outbox-1',?,?,?,'pending',?)""",
                (item["id"], due, __import__("json").dumps(item["payload"]),
                 datetime.now(timezone.utc).isoformat()))
        first = self.schedules.dispatch_due(self.queue, now=now)
        second = self.schedules.dispatch_due(self.queue, now=now)
        self.assertEqual(first["count"], 1)
        self.assertEqual(second["count"], 0)
        self.assertEqual(self.queue.stats()["total"], 1)
        self.assertEqual(self.schedules.pending_dispatches(), [])

    def test_inactive_schedule_does_not_create_outbox(self):
        now = datetime.now(timezone.utc)
        item = self.schedule(now - timedelta(hours=2))
        self.schedules.set_active(item["id"], False)
        result = self.schedules.dispatch_due(self.queue, now=now)
        self.assertEqual(result["count"], 0)
        self.assertEqual(self.schedules.pending_dispatches(), [])

    def test_naive_now_is_rejected(self):
        with self.assertRaises(ValueError):
            self.schedules.dispatch_due(self.queue, now=datetime(2026, 1, 1))
if __name__ == "__main__":
    unittest.main()
