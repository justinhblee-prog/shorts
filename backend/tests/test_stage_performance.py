import unittest
from datetime import datetime, timezone
from unittest import mock

from stage_performance import build_stage_performance
from fastapi import HTTPException
import app as app_module
from app import get_job_stage_performance


class StagePerformanceTests(unittest.TestCase):
    def test_dwell_time_is_grouped_by_durable_queue_state(self):
        job = {"id": "job-1", "status": "review_pending",
               "created_at": "2026-11-15T10:00:00Z",
               "updated_at": "2026-11-15T10:00:30Z"}
        events = [
            {"created_at": "2026-11-15T10:00:10Z",
             "from_status": "queued", "to_status": "running"},
            {"created_at": "2026-11-15T10:00:20Z",
             "from_status": "running", "to_status": "review_pending"},
        ]
        result = build_stage_performance(
            job, events, datetime(2026, 11, 15, 10, 1, tzinfo=timezone.utc))
        durations = {item["status"]: item["observed_seconds"]
                     for item in result["state_durations"]}
        self.assertEqual(durations, {"queued": 10.0, "running": 10.0,
                                     "review_pending": 10.0})
        self.assertEqual(result["total_observed_seconds"], 30.0)
        self.assertEqual(result["measurement"], "durable_queue_state_dwell")
        self.assertTrue(result["read_only"])
        self.assertEqual(result["actions_taken"], [])

    def test_out_of_order_and_invalid_timestamps_are_reported(self):
        job = {"id": "job-2", "status": "running",
               "created_at": "2026-11-15T10:00:00Z",
               "updated_at": "2026-11-15T10:00:20Z"}
        events = [
            {"created_at": "not-a-time", "from_status": "queued",
             "to_status": "running"},
            {"created_at": "2026-11-15T10:00:10Z",
             "from_status": "queued", "to_status": "running"},
            {"created_at": "2026-11-15T10:00:05Z",
             "from_status": "running", "to_status": "failed_retriable"},
        ]
        result = build_stage_performance(job, events)
        self.assertEqual(result["data_quality_warnings"],
                         ["invalid_event_timestamp", "out_of_order_event_timestamp"])
        self.assertTrue(result["limitations"])

    def test_missing_event_history_returns_empty_measurements(self):
        result = build_stage_performance(
            {"id": "job-3", "status": "queued"}, [])
        self.assertEqual(result["state_durations"], [])
        self.assertIsNone(result["bottleneck"])
        self.assertEqual(result["total_observed_seconds"], 0)

    def test_api_requires_review_access_and_uses_durable_events(self):
        job = {"id": "job-4", "status": "queued"}
        with mock.patch("app.require_review_access") as access, \
             mock.patch.object(app_module.queue, "get", return_value=job), \
             mock.patch.object(app_module.queue, "events", return_value=[]) as events:
            result = get_job_stage_performance("job-4", x_review_token="secret")
        access.assert_called_once_with("secret")
        events.assert_called_once_with("job-4")
        self.assertEqual(result["job_id"], "job-4")
        self.assertTrue(result["read_only"])

    def test_api_returns_404_for_unknown_job(self):
        with mock.patch("app.require_review_access"), \
             mock.patch.object(app_module.queue, "get",
                               side_effect=app_module.JobNotFound()):
            with self.assertRaises(HTTPException) as caught:
                get_job_stage_performance("missing", x_review_token="secret")
        self.assertEqual(caught.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
