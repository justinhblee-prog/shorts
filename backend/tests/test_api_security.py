import os
import unittest
import app as app_module
from unittest import mock
from fastapi import HTTPException
from pydantic import ValidationError
from app import (app, require_review_access, YouTubeLateSuccessResolution, Enqueue,
                 enqueue, IdempotencyConflict, ProductionExecute, execute_production_job,
                 ProductionLeaseConflict, ProductionBrief, create_production_job)
from production_pipeline import ProviderError

class ApiSecurityTests(unittest.TestCase):
    def test_all_operational_routes_require_review_token(self):
        public = {"/api/health", "/api/brands", "/api/brands/{slug}"}
        unprotected = []
        for route in app.routes:
            path = getattr(route, "path", "")
            if not path.startswith("/api/") or path in public:
                continue
            endpoint = getattr(route, "endpoint", None)
            if endpoint is None:
                continue
            if "x_review_token" not in endpoint.__annotations__:
                unprotected.append(path)
        self.assertEqual(unprotected, [])

    def test_late_upload_resolution_route_is_registered_and_token_protected(self):
        route = next((r for r in app.routes
                      if getattr(r,"path",None)=="/api/youtube/uploads/{job_id}/resolve-late-result"),None)
        self.assertIsNotNone(route)
        self.assertIn("x_review_token",route.endpoint.__annotations__)
        with self.assertRaises(ValidationError):
            YouTubeLateSuccessResolution(operator_id="operator",note="checked without video ID")
        valid=YouTubeLateSuccessResolution(
            operator_id="operator",video_id="yt-video-123",note="verified in Studio"
        )
        self.assertEqual(valid.video_id,"yt-video-123")

    def test_queue_idempotency_conflict_returns_http_409(self):
        body = Enqueue(job_type="render", payload={"topic": "changed"},
                       idempotency_key="already-used")
        with (
            mock.patch("app.require_review_access"),
            mock.patch("app.queue.enqueue",
                              side_effect=IdempotencyConflict("different payload")),
        ):
            with self.assertRaises(HTTPException) as caught:
                enqueue(body, x_review_token="test-token")
        self.assertEqual(caught.exception.status_code, 409)

    def test_production_submission_freezes_selected_brand_profile_into_job(self):
        config = {
            "positioning": "Grounded AI explainers",
            "audience": "technology-curious adults",
            "tone": ["clear", "skeptical"],
            "risk_level": "elevated",
            "review_rules": ["Label speculation"],
            "regions": ["US"],
            "languages": ["en"],
        }
        brand = {"slug": "future-leak", "name": "Future Leak",
                 "active": True, "config": config}
        body = ProductionBrief(brand="future-leak", region="US",
                              language="en", topic="AI agents")
        with (
            mock.patch("app.require_review_access"),
            mock.patch("app.brand_store.list", return_value=[brand]),
            mock.patch("app.submit_production", return_value={"job": {"id": "job-brand"}}) as submit,
        ):
            result = create_production_job(body, x_review_token="test-token")
        self.assertEqual(result["job"]["id"], "job-brand")
        submitted_brief = submit.call_args.args[2]
        self.assertEqual(submitted_brief["brand"], "Future Leak")
        self.assertEqual(submitted_brief["brand_profile"], {
            "positioning": "Grounded AI explainers",
            "audience": "technology-curious adults",
            "tone": ["clear", "skeptical"],
            "risk_level": "elevated",
            "review_rules": ["Label speculation"],
        })

    def test_api_production_execution_passes_worker_lease_and_reconciles_handoff(self):
        job = {"id": "job-1", "job_type": "short_video_production",
               "status": "running", "worker_id": "worker-1",
               "lease_token": "lease-1", "payload": {"topic": "test"}}
        response = {"status": "review_pending"}
        body = ProductionExecute(worker_id="worker-1", lease_token="lease-1")
        with (
            mock.patch("app.require_review_access"),
            mock.patch("app.queue.get", return_value=job),
            mock.patch("app.production_pipeline.execute",
                              return_value={"artifacts": []}) as execute,
            mock.patch("app.queue.finish") as finish,
            mock.patch("app.production_store.reconcile_review_pending") as reconcile,
            mock.patch("app.production_store.get", return_value=response),
        ):
            result = execute_production_job("job-1", body, x_review_token="test-token")

        self.assertEqual(result, response)
        execute.assert_called_once_with(
            "job-1", job["payload"], worker_id="worker-1", lease_token="lease-1"
        )
        finish.assert_called_once()
        reconcile.assert_called_once_with(app_module.queue)

    def test_api_production_execution_rejects_stale_pipeline_lease(self):
        job = {"id": "job-1", "job_type": "short_video_production",
               "status": "running", "worker_id": "worker-1",
               "lease_token": "lease-1", "payload": {"topic": "test"}}
        body = ProductionExecute(worker_id="worker-1", lease_token="lease-1")
        with (
            mock.patch("app.require_review_access"),
            mock.patch("app.queue.get", return_value=job),
            mock.patch("app.production_pipeline.execute",
                              side_effect=ProductionLeaseConflict("stale lease")),
            mock.patch("app.queue.fail") as fail,
        ):
            with self.assertRaises(HTTPException) as caught:
                execute_production_job("job-1", body, x_review_token="test-token")
        self.assertEqual(caught.exception.status_code, 409)
        fail.assert_not_called()

    def test_api_provider_error_records_failure_and_pauses_production(self):
        job = {"id": "job-provider", "job_type": "short_video_production",
               "status": "running", "worker_id": "worker-1",
               "lease_token": "lease-1", "payload": {"topic": "test"}}
        body = ProductionExecute(worker_id="worker-1", lease_token="lease-1")
        with (
            mock.patch("app.require_review_access"),
            mock.patch.object(app_module.queue, "get", return_value=job),
            mock.patch.object(app_module.production_pipeline, "execute",
                              side_effect=ProviderError("script", "provider timeout", True)),
            mock.patch.object(app_module.queue, "fail") as fail,
            mock.patch.object(app_module.queue, "pause") as pause,
        ):
            with self.assertRaises(HTTPException) as caught:
                execute_production_job("job-provider", body, x_review_token="test-token")
        self.assertEqual(caught.exception.status_code, 502)
        fail.assert_called_once()
        pause.assert_called_once()

    def test_api_internal_error_records_failure_and_pauses_production(self):
        job = {"id": "job-internal", "job_type": "short_video_production",
               "status": "running", "worker_id": "worker-1",
               "lease_token": "lease-1", "payload": {"topic": "test"}}
        body = ProductionExecute(worker_id="worker-1", lease_token="lease-1")
        with (
            mock.patch("app.require_review_access"),
            mock.patch.object(app_module.queue, "get", return_value=job),
            mock.patch.object(app_module.production_pipeline, "execute",
                              side_effect=RuntimeError("unexpected")),
            mock.patch.object(app_module.queue, "fail") as fail,
            mock.patch.object(app_module.queue, "pause") as pause,
        ):
            with self.assertRaises(HTTPException) as caught:
                execute_production_job("job-internal", body, x_review_token="test-token")
        self.assertEqual(caught.exception.status_code, 500)
        fail.assert_called_once()
        pause.assert_called_once()
    def test_review_token_fails_closed(self):
        previous = os.environ.get("NEXUS_REVIEW_TOKEN")
        os.environ["NEXUS_REVIEW_TOKEN"] = "unit-test-secret"
        try:
            with self.assertRaises(HTTPException) as missing:
                require_review_access(None)
            self.assertEqual(missing.exception.status_code, 401)
            with self.assertRaises(HTTPException) as invalid:
                require_review_access("wrong-secret")
            self.assertEqual(invalid.exception.status_code, 401)
            self.assertIsNone(require_review_access("unit-test-secret"))
        finally:
            if previous is None:
                os.environ.pop("NEXUS_REVIEW_TOKEN", None)
            else:
                os.environ["NEXUS_REVIEW_TOKEN"] = previous

if __name__ == "__main__":
    unittest.main()
