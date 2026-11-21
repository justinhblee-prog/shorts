import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app as app_module
from development_jobs import DevelopmentJobStore
from fastapi import HTTPException


class DevelopmentJobApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.database = Path(self.tmp.name) / "development.sqlite3"
        self.store = DevelopmentJobStore(str(self.database))
        self.job = self.store.create(
            title="Scoped development task",
            description="Read-only monitor fixture",
            scope=["backend/example.py"],
            acceptance=["A regression test exists"],
        )

    def tearDown(self):
        app_module._development_job_store_instance = None
        app_module._development_job_store_path = None
        self.tmp.cleanup()

    def test_monitor_routes_are_authenticated_get_only(self):
        routes = [
            route for route in app_module.app.routes
            if getattr(route, "path", "").startswith("/api/development/")
        ]
        self.assertEqual(
            {route.path for route in routes},
            {
                "/api/development/summary",
                "/api/development/jobs",
                "/api/development/jobs/{job_id}",
                "/api/development/jobs/{job_id}/events",
                "/api/development/workers",
            },
        )
        for route in routes:
            with self.subTest(path=route.path):
                self.assertEqual(set(route.methods or []), {"GET"})
                self.assertIn("x_review_token", route.endpoint.__annotations__)

    def test_monitor_reads_summary_jobs_events_and_workers_without_mutating_state(self):
        claimed = self.store.claim_ready("runner-visible-id")
        self.store.touch_worker(
            "runner-visible-id", hostname="private-runner-host",
            current_job_id=self.job["id"],
        )
        lease_token = claimed["lease_token"]
        before = self.store.get(self.job["id"])
        auth_calls = []

        def authorize(token, permission):
            auth_calls.append((token, permission))
            return "operator"

        with (
            mock.patch.object(app_module, "_get_development_job_store", return_value=self.store),
            mock.patch.object(app_module, "require_review_permission", side_effect=authorize),
        ):
            summary = app_module.development_job_summary(x_review_token="operator-token")
            jobs = app_module.development_jobs(status="leased", limit=20, x_review_token="operator-token")
            detail = app_module.development_job_detail(self.job["id"], x_review_token="operator-token")
            events = app_module.development_job_events(self.job["id"], limit=20, x_review_token="operator-token")
            workers = app_module.development_workers(x_review_token="operator-token")

        self.assertEqual(summary["total"], 1)
        self.assertEqual(summary["active_leases"], 1)
        self.assertEqual(len(jobs["items"]), 1)
        self.assertEqual(jobs["items"][0]["status"], "leased")
        self.assertEqual(detail["job"]["id"], self.job["id"])
        self.assertNotIn("lease_token", jobs["items"][0])
        self.assertNotIn("lease_token", detail["job"])
        self.assertTrue(events["events"])
        self.assertTrue(all("details" not in event for event in events["events"]))
        self.assertEqual(len(workers["workers"]), 1)
        self.assertTrue(workers["workers"][0]["is_online"])
        self.assertNotIn("hostname", workers["workers"][0])
        self.assertEqual(self.store.get(self.job["id"])["lease_token"], lease_token)
        self.assertEqual(self.store.get(self.job["id"])["status"], before["status"])
        self.assertEqual(len(auth_calls), 5)
        self.assertTrue(all(permission == "development.read" for _, permission in auth_calls))

    def test_unknown_status_and_out_of_range_limits_are_rejected(self):
        with mock.patch.object(app_module, "require_review_permission"):
            with self.assertRaises(HTTPException) as status_error:
                app_module.development_jobs(status="unknown", limit=20, x_review_token="token")
            self.assertEqual(status_error.exception.status_code, 422)
            with self.assertRaises(HTTPException) as limit_error:
                app_module.development_jobs(status=None, limit=201, x_review_token="token")
            self.assertEqual(limit_error.exception.status_code, 422)

    def test_missing_job_and_missing_event_job_return_404(self):
        with (
            mock.patch.object(app_module, "_get_development_job_store", return_value=self.store),
            mock.patch.object(app_module, "require_review_permission"),
        ):
            with self.assertRaises(HTTPException) as detail_error:
                app_module.development_job_detail("not-a-job", x_review_token="token")
            self.assertEqual(detail_error.exception.status_code, 404)
            with self.assertRaises(HTTPException) as events_error:
                app_module.development_job_events("not-a-job", limit=10, x_review_token="token")
            self.assertEqual(events_error.exception.status_code, 404)

    def test_existing_database_is_opened_and_cached(self):
        app_module._development_job_store_instance = None
        app_module._development_job_store_path = None
        with mock.patch.dict(os.environ, {"NEXUS_DEVELOPMENT_DB": str(self.database)}, clear=False):
            first = app_module._get_development_job_store()
            second = app_module._get_development_job_store()
        self.assertEqual(first.db_path, str(self.database.resolve()))
        self.assertIs(first, second)
        self.assertTrue(self.database.is_file())

    def test_missing_database_configuration_fails_closed(self):
        app_module._development_job_store_instance = None
        app_module._development_job_store_path = None
        with mock.patch.dict(os.environ, {"NEXUS_DEVELOPMENT_DB": ""}, clear=False):
            with self.assertRaises(HTTPException) as caught:
                app_module._get_development_job_store()
        self.assertEqual(caught.exception.status_code, 503)

    def test_missing_database_file_is_not_created(self):
        missing = Path(self.tmp.name) / "not-created.sqlite3"
        app_module._development_job_store_instance = None
        app_module._development_job_store_path = None
        with mock.patch.dict(os.environ, {"NEXUS_DEVELOPMENT_DB": str(missing)}, clear=False):
            with self.assertRaises(HTTPException) as caught:
                app_module._get_development_job_store()
        self.assertEqual(caught.exception.status_code, 503)
        self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
