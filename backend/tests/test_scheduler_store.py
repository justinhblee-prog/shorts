import os
import sqlite3
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

    def test_scheduled_tiktok_platform_is_preserved_in_dispatched_job(self):
        now=datetime.now(timezone.utc)
        item=self.schedules.create(
            "TikTok daily",3600,
            {"brand":"Brain Glitch","region":"US","language":"English",
             "topic":"Test","platforms":["tiktok"]},
            start_at=(now-timedelta(minutes=5)).isoformat(),
        )
        result=self.schedules.dispatch_due(self.queue,now=now)
        self.assertEqual(result["count"],1)
        job=self.queue.claim("tiktok-worker","localhost",job_type="short_video_production")
        self.assertIsNotNone(job)
        self.assertEqual(job["payload"]["platforms"],["tiktok"])
        self.assertEqual(job["payload"]["topic"],"Test")

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


    def test_crash_after_queue_acceptance_replays_same_idempotent_job(self):
        now = datetime.now(timezone.utc)
        item = self.schedule(now - timedelta(minutes=5))
        class AcceptThenCrashQueue:
            def __init__(self, queue):
                self.queue = queue
                self.calls = 0
            def is_paused(self):
                return self.queue.is_paused()
            def enqueue(self, *args, **kwargs):
                self.calls += 1
                result = self.queue.enqueue(*args, **kwargs)
                if self.calls == 1:
                    raise RuntimeError("simulated crash after durable queue acceptance")
                return result
        flaky = AcceptThenCrashQueue(self.queue)
        first = self.schedules.dispatch_due(flaky, now=now)
        self.assertEqual(first["count"], 0)
        self.assertEqual(len(self.schedules.pending_dispatches()), 1)
        self.assertEqual(self.queue.stats()["total"], 1)
        second = self.schedules.dispatch_due(flaky, now=now + timedelta(seconds=30))
        self.assertEqual(second["count"], 1)
        self.assertEqual(self.queue.stats()["total"], 1)
        self.assertEqual(self.schedules.pending_dispatches(), [])
        self.assertEqual(flaky.calls, 2)
    def test_queue_failure_keeps_outbox_pending_for_retry(self):
        now = datetime.now(timezone.utc)
        item = self.schedule(now - timedelta(minutes=5))
        class FailingQueue:
            def is_paused(self):
                return False
            def enqueue(self, *args, **kwargs):
                raise RuntimeError("temporary queue outage")
        first = self.schedules.dispatch_due(FailingQueue(), now=now)
        self.assertEqual(first["count"], 0)
        pending = self.schedules.pending_dispatches()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["attempts"], 1)
        self.assertIn("temporary queue outage", pending[0]["last_error"])
        second = self.schedules.dispatch_due(self.queue, now=now + timedelta(seconds=30))
        self.assertEqual(second["count"], 1)
        self.assertEqual(self.schedules.pending_dispatches(), [])
        self.assertEqual(self.queue.stats()["total"], 1)



    def test_existing_outbox_table_is_migrated_without_losing_pending_rows(self):
        legacy_db = os.path.join(self.tmp.name, "legacy.sqlite3")
        with sqlite3.connect(legacy_db) as connection:
            connection.execute("""CREATE TABLE schedule_dispatch_outbox(
                id TEXT PRIMARY KEY, schedule_id TEXT NOT NULL,
                scheduled_for TEXT NOT NULL, payload_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT, created_at TEXT NOT NULL, dispatched_at TEXT,
                UNIQUE(schedule_id,scheduled_for)
            )""")
            connection.execute("""INSERT INTO schedule_dispatch_outbox
                (id,schedule_id,scheduled_for,payload_json,status,created_at)
                VALUES('legacy-1','schedule-1','2026-11-16T00:00:00+00:00','{}','pending',
                       '2026-11-16T00:00:00+00:00')""")
        migrated = ScheduleStore(legacy_db)
        pending = migrated.pending_dispatches(now=datetime(2026, 11, 16, 1, tzinfo=timezone.utc))
        self.assertEqual(len(pending), 1)
        self.assertIsNone(pending[0]["next_attempt_at"])

    def test_outbox_retry_uses_exponential_backoff_and_caps_at_one_hour(self):
        now = datetime.now(timezone.utc)
        item = self.schedule(now - timedelta(minutes=5))
        class FailingQueue:
            def is_paused(self):
                return False
            def enqueue(self, *args, **kwargs):
                raise RuntimeError("temporary outage")
        first = self.schedules.dispatch_due(FailingQueue(), now=now)
        self.assertEqual(first["count"], 0)
        row = self.schedules.pending_dispatches()[0]
        self.assertEqual(row["attempts"], 1)
        self.assertEqual(datetime.fromisoformat(row["next_attempt_at"]), now + timedelta(seconds=30))
        self.assertEqual(self.schedules.dispatch_due(self.queue, now=now + timedelta(seconds=29))["count"], 0)
        self.assertEqual(self.schedules.dispatch_due(self.queue, now=now + timedelta(seconds=30))["count"], 1)

    def test_outbox_retry_schedule_caps_after_repeated_failures(self):
        now = datetime.now(timezone.utc)
        self.schedule(now - timedelta(minutes=5))
        class FailingQueue:
            def is_paused(self):
                return False
            def enqueue(self, *args, **kwargs):
                raise RuntimeError("still unavailable")
        for attempt in range(9):
            current = now + timedelta(seconds=3600 * attempt)
            self.schedules.dispatch_due(FailingQueue(), now=current)
        row = self.schedules.pending_dispatches()[0]
        self.assertEqual(row["attempts"], 9)
        self.assertEqual(datetime.fromisoformat(row["next_attempt_at"]),
                         now + timedelta(seconds=8 * 3600 + 3600))

    def test_paused_production_holds_due_schedule_in_outbox_until_resume(self):
        now = datetime.now(timezone.utc)
        item = self.schedule(now - timedelta(minutes=5))
        self.queue.pause("operator requested pause", actor="operator-1")
        paused = self.schedules.dispatch_due(self.queue, now=now)
        self.assertTrue(paused["paused"])
        self.assertEqual(paused["count"], 0)
        self.assertEqual(self.queue.stats()["total"], 0)
        pending = self.schedules.pending_dispatches()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["schedule_id"], item["id"])
        self.queue.resume(actor="operator-1", note="Provider state reconciled")
        resumed = self.schedules.dispatch_due(self.queue, now=now)
        self.assertEqual(resumed["count"], 1)
        self.assertEqual(self.queue.stats()["total"], 1)
        self.assertEqual(self.schedules.pending_dispatches(), [])
    def test_deactivating_schedule_cancels_undispatched_occurrence(self):
        now = datetime.now(timezone.utc)
        item = self.schedule(now - timedelta(minutes=5))
        self.queue.pause("hold scheduled work", actor="operator-1")
        held = self.schedules.dispatch_due(self.queue, now=now)
        self.assertEqual(held["pending"], 1)
        self.schedules.set_active(item["id"], False)
        status = self.schedules.outbox_status()
        self.assertEqual(status["counts"].get("cancelled"), 1)
        self.assertEqual(self.schedules.pending_dispatches(), [])
        self.queue.resume(actor="operator-1", note="Reviewed schedule change")
        resumed = self.schedules.dispatch_due(self.queue, now=now)
        self.assertEqual(resumed["count"], 0)
        self.assertEqual(self.queue.stats()["total"], 0)
    def test_inactive_schedule_does_not_create_outbox(self):
        now = datetime.now(timezone.utc)
        item = self.schedule(now - timedelta(hours=2))
        self.schedules.set_active(item["id"], False)
        result = self.schedules.dispatch_due(self.queue, now=now)
        self.assertEqual(result["count"], 0)
        self.assertEqual(self.schedules.pending_dispatches(), [])


    def test_outbox_status_reports_pending_and_dispatched_counts(self):
        now = datetime.now(timezone.utc)
        self.schedule(now - timedelta(minutes=5))
        self.schedules.dispatch_due(self.queue, now=now)
        status = self.schedules.outbox_status()
        self.assertEqual(status["counts"].get("dispatched"), 1)
        self.assertEqual(status["pending_retries"], 0)
        self.assertEqual(status["items"][0]["status"], "dispatched")



    def test_outbox_status_distinguishes_deferred_retries_from_ready_pending(self):
        now = datetime.now(timezone.utc)
        self.schedule(now - timedelta(minutes=5))
        class FailingQueue:
            def is_paused(self):
                return False
            def enqueue(self, *args, **kwargs):
                raise RuntimeError("temporary queue outage")
        self.schedules.dispatch_due(FailingQueue(), now=now)
        deferred = self.schedules.outbox_status(now=now)
        self.assertEqual(deferred["counts"].get("pending"), 1)
        self.assertEqual(deferred["pending_retries"], 1)
        self.assertEqual(deferred["pending_ready"], 0)
        ready = self.schedules.outbox_status(now=now + timedelta(seconds=30))
        self.assertEqual(ready["pending_retries"], 0)
        self.assertEqual(ready["pending_ready"], 1)

    def test_outbox_status_rejects_naive_clock(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            self.schedules.outbox_status(now=datetime(2026, 1, 1))

    def test_outbox_moves_to_dead_letter_after_ten_failed_attempts(self):
        now = datetime.now(timezone.utc)
        self.schedules.create("annual", 31536000,
            {"brand": "Brain Glitch", "region": "US", "language": "English", "topic": "Test"},
            start_at=(now - timedelta(minutes=5)).isoformat())
        class FailingQueue:
            def is_paused(self):
                return False
            def enqueue(self, *args, **kwargs):
                raise RuntimeError("permanent payload or queue failure")
        for attempt in range(10):
            self.schedules.dispatch_due(FailingQueue(),
                now=now + timedelta(seconds=3600 * attempt))
        status = self.schedules.outbox_status()
        self.assertEqual(status["counts"].get("dead_letter"), 1)
        self.assertEqual(status["pending_retries"], 0)
        row = status["items"][0]
        self.assertEqual(row["status"], "dead_letter")
        self.assertEqual(row["attempts"], 10)
        self.assertIsNone(row["next_attempt_at"])
        self.assertIn("RuntimeError", row["last_error"])
        # A dead-letter row is excluded from automatic retry polling.
        self.assertEqual(self.schedules.pending_dispatches(), [])

    def test_dead_letter_can_be_manually_retried_and_dispatched_idempotently(self):
        now = datetime.now(timezone.utc)
        self.schedules.create("annual", 31536000,
            {"brand": "Brain Glitch", "region": "US", "language": "English", "topic": "Test"},
            start_at=(now - timedelta(minutes=5)).isoformat())
        class FailingQueue:
            def is_paused(self):
                return False
            def enqueue(self, *args, **kwargs):
                raise RuntimeError("queue unavailable")
        for attempt in range(10):
            self.schedules.dispatch_due(FailingQueue(),
                now=now + timedelta(seconds=3600 * attempt))
        row = self.schedules.outbox_status()["items"][0]
        retried = self.schedules.retry_dead_letter(row["id"])
        self.assertEqual(retried["status"], "pending")
        self.assertEqual(retried["attempts"], 0)
        self.assertIsNone(retried["next_attempt_at"])
        self.assertIsNone(self.schedules.retry_dead_letter(row["id"]))
        result = self.schedules.dispatch_due(self.queue, now=now + timedelta(hours=11))
        self.assertEqual(result["count"], 1)
        self.assertEqual(self.schedules.outbox_status()["counts"].get("dispatched"), 1)

    def test_retry_dead_letter_requires_existing_dead_letter_id(self):
        for invalid in ("", None, 42):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "outbox_id"):
                    self.schedules.retry_dead_letter(invalid)
        self.assertIsNone(self.schedules.retry_dead_letter("missing"))

    def test_naive_now_is_rejected(self):
        with self.assertRaises(ValueError):
            self.schedules.dispatch_due(self.queue, now=datetime(2026, 1, 1))


    def test_schedule_interval_rejects_coercion_and_out_of_range_values(self):
        payload = {"brand": "B", "region": "US", "language": "English", "topic": "x"}
        for invalid in (True, False, 3600.5, "3600", 3599, 31536001, 10**12):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "interval_seconds|schedule interval"):
                    self.schedules.create("invalid", invalid, payload)
        minimum = self.schedules.create("minimum", 3600, payload)
        maximum = self.schedules.create("maximum", 31536000, payload)
        self.assertEqual(minimum["interval_seconds"], 3600)
        self.assertEqual(maximum["interval_seconds"], 31536000)


    def test_schedule_activation_requires_a_real_boolean(self):
        item = self.schedule(datetime.now(timezone.utc) + timedelta(hours=1))
        for invalid in (0, 1, "false", "true", None, [], {}):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "active must be a boolean"):
                    self.schedules.set_active(item["id"], invalid)
        self.assertFalse(self.schedules.set_active(item["id"], False)["active"])
        self.assertTrue(self.schedules.set_active(item["id"], True)["active"])

    def test_scheduler_store_limits_reject_coercion_and_out_of_range_values(self):
        for method, maximum in (
            (self.schedules.pending_dispatches, 500),
            (self.schedules.outbox_status, 100),
        ):
            for invalid in (True, False, 1.5, "10", 0, -1, maximum + 1):
                with self.subTest(method=method.__name__, invalid=invalid):
                    with self.assertRaisesRegex(ValueError, "limit must be an integer"):
                        method(invalid)
            result = method(1)
            self.assertEqual(result, [] if method == self.schedules.pending_dispatches else {
                "counts": {}, "items": [], "pending_retries": 0
            })
        for invalid in (True, False, 1.5, "10", 0, -1, 101):
            with self.subTest(dispatch_limit=invalid):
                with self.assertRaisesRegex(ValueError, "limit must be an integer"):
                    self.schedules.dispatch_due(self.queue, limit=invalid)

    def test_dispatch_rejects_invalid_lease_duration_even_when_nothing_is_due(self):
        for invalid in (True, False, 1.5, "90", 0, -1, 3601):
            with self.subTest(lease_seconds=invalid):
                with self.assertRaisesRegex(ValueError, "lease_seconds"):
                    self.schedules.dispatch_due(self.queue, lease_seconds=invalid)

    def test_scheduler_lease_duration_is_strict_and_bounded(self):
        for invalid in (True, False, 1.5, "90", 0, -1, 3601, 10**9):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "lease_seconds"):
                    self.schedules.acquire_scheduler_lease("invalid", invalid)
        token = self.schedules.acquire_scheduler_lease("scheduler-min", 1)
        self.assertIsNotNone(token)
        self.assertTrue(self.schedules.renew_scheduler_lease("scheduler-min", token, 3600))
        with self.assertRaisesRegex(ValueError, "lease_seconds"):
            self.schedules.renew_scheduler_lease("scheduler-min", token, True)

if __name__ == "__main__":
    unittest.main()
