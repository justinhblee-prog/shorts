import json
import unittest
from unittest import mock

import app as app_module


class DevelopmentJobApiSecurityTests(unittest.TestCase):
    def test_list_endpoint_requires_operations_read_and_redacts_lease_and_error(self):
        job = {
            "id": "DEV-ORCH-001", "title": "Registry", "status": "running",
            "lease_token": "private-lease-token", "worker_id": "runner-a",
            "result_summary": "provider error bearer private-result-secret",
            "scope": ["backend/development_jobs.py"], "attempts": 1,
            "max_attempts": 3,
        }
        with (
            mock.patch.object(app_module, "require_review_permission") as auth,
            mock.patch.object(app_module.development_job_store, "list", return_value=[job]),
            mock.patch.object(app_module.development_job_store, "summary",
                              return_value={"total": 1, "by_status": {"running": 1}}),
        ):
            result = app_module.list_development_jobs(x_review_token="monitor-token")
        auth.assert_called_once_with("monitor-token", "operations.read")
        serialized = json.dumps(result)
        self.assertNotIn("private-lease-token", serialized)
        self.assertNotIn("private-result-secret", serialized)
        self.assertEqual(result["jobs"][0]["worker_id"], "runner-a")
        self.assertEqual(result["jobs"][0]["scope"], ["backend/development_jobs.py"])

    def test_event_endpoint_omits_raw_error_details(self):
        events = [{
            "event_type": "failed", "from_status": "running", "to_status": "retry_wait",
            "actor": "runner-a", "created_at": "2026-11-17T10:00:00+00:00",
            "details": {"error": "Bearer event-private-secret", "retryable": True},
            "details_json": "{\"error\":\"Bearer event-private-secret\"}",
        }]
        with (
            mock.patch.object(app_module, "require_review_permission") as auth,
            mock.patch.object(app_module.development_job_store, "events", return_value=events),
        ):
            result = app_module.development_job_events(
                "DEV-ORCH-001", x_review_token="monitor-token"
            )
        auth.assert_called_once_with("monitor-token", "operations.read")
        serialized = json.dumps(result)
        self.assertNotIn("event-private-secret", serialized)
        self.assertEqual(result["events"][0]["details"], {"retryable": True})

    def test_detail_endpoint_redacts_worker_lease_token(self):
        job = {"id": "DEV-ORCH-001", "status": "leased", "lease_token": "detail-secret"}
        with (
            mock.patch.object(app_module, "require_review_permission") as auth,
            mock.patch.object(app_module.development_job_store, "get", return_value=job),
        ):
            result = app_module.get_development_job(
                "DEV-ORCH-001", x_review_token="monitor-token"
            )
        auth.assert_called_once_with("monitor-token", "operations.read")
        self.assertNotIn("detail-secret", json.dumps(result))


    def test_summary_endpoint_exposes_lease_health_under_operations_read(self):
        summary = {
            "total": 2, "by_status": {"running": 1, "completed": 1},
            "active_leases": 1, "expired_leases": 0,
            "latest_updated_at": "2026-11-17T10:00:00+00:00",
            "latest_validation_ref": "ci://run/42",
        }
        with (
            mock.patch.object(app_module, "require_review_permission") as auth,
            mock.patch.object(app_module.development_job_store, "summary", return_value=summary),
        ):
            result = app_module.development_job_summary(x_review_token="monitor-token")
        auth.assert_called_once_with("monitor-token", "operations.read")
        self.assertEqual(result["active_leases"], 1)
        self.assertEqual(result["expired_leases"], 0)
        self.assertEqual(result["latest_validation_ref"], "ci://run/42")


    def test_worker_presence_endpoint_requires_operations_read(self):
        workers = [{
            "worker_id": "runner-a", "hostname": "windows-runner",
            "status": "online", "current_job_id": "DEV-ORCH-005",
            "last_seen_at": "2026-11-17T10:00:00+00:00", "is_online": True,
        }]
        summary = {"online_workers": 1, "known_workers": 1}
        with (
            mock.patch.object(app_module, "require_review_permission") as auth,
            mock.patch.object(app_module.development_job_store, "list_workers", return_value=workers),
            mock.patch.object(app_module.development_job_store, "summary", return_value=summary),
        ):
            result = app_module.list_development_workers(x_review_token="monitor-token")
        auth.assert_called_once_with("monitor-token", "operations.read")
        self.assertEqual(result["workers"][0]["worker_id"], "runner-a")
        self.assertTrue(result["workers"][0]["is_online"])
        self.assertEqual(result["summary"]["online_workers"], 1)


if __name__ == "__main__":
    unittest.main()
