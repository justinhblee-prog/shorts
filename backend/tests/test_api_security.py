import json
import os
import unittest
import app as app_module
from unittest import mock
from fastapi import HTTPException
from pydantic import ValidationError
from app import (app, require_review_access, YouTubeLateSuccessResolution, Enqueue,
                 enqueue, IdempotencyConflict, ProductionExecute, execute_production_job,
                 ProductionLeaseConflict, ProductionBrief, create_production_job,
                 QueueControlAction, queue_control, pause_queue, resume_queue,
                 TrendProductionDraft, draft_production_from_trend,
                 OpportunityInput, create_opportunity_score, PolicyEvidenceInput, ScheduleInput)
from production_pipeline import ProviderError, PolicyBlocked

class ApiSecurityTests(unittest.TestCase):


    def test_publishing_status_endpoints_redact_raw_provider_errors(self):
        upload = {
            "job_id": "job-safe", "status": "failed",
            "error": "Authorization: Bearer youtube-secret",
            "events": [{"event_type": "upload_failed", "error": "youtube-body-secret"}],
        }
        tiktok = {
            "job_id": "job-safe", "status": "failed",
            "error": "Authorization: Bearer tiktok-secret",
            "events": [{"event_type": "publish_failed", "error": "tiktok-body-secret"}],
        }
        with (
            mock.patch.object(app_module, "require_review_permission"),
            mock.patch.object(app_module.youtube_upload_store, "get", return_value=upload),
        ):
            safe_upload = app_module.get_youtube_upload(
                "job-safe", x_review_token="review-token"
            )
        with (
            mock.patch.object(app_module, "require_review_permission"),
            mock.patch.object(app_module.tiktok_publish_store, "get", return_value=tiktok),
        ):
            safe_tiktok = app_module.get_tiktok_publication(
                "job-safe", x_review_token="review-token"
            )
        serialized = json.dumps({"upload": safe_upload, "tiktok": safe_tiktok})
        for secret in (
            "youtube-secret", "youtube-body-secret",
            "tiktok-secret", "tiktok-body-secret",
        ):
            self.assertNotIn(secret, serialized)
        self.assertEqual(safe_upload["error"], app_module.review_store.SAFE_ERROR_NOTICE)
        self.assertEqual(safe_tiktok["error"], app_module.review_store.SAFE_ERROR_NOTICE)
        self.assertEqual(
            safe_upload["events"][0]["error"], app_module.review_store.SAFE_ERROR_NOTICE
        )
        self.assertEqual(
            safe_tiktok["events"][0]["error"], app_module.review_store.SAFE_ERROR_NOTICE
        )

    def test_approved_review_list_redacts_platform_publication_errors(self):
        upload = {
            "status": "failed", "error": "youtube-private-error",
            "events": [{"error": "youtube-event-secret"}],
        }
        tiktok = {
            "status": "failed", "error": "tiktok-private-error",
            "events": [{"error": "tiktok-event-secret"}],
        }
        with (
            mock.patch.object(app_module, "require_review_permission"),
            mock.patch.object(app_module.review_store, "list_approved",
                              return_value=[{"job_id": "job-safe"}]),
            mock.patch.object(app_module.youtube_upload_store, "get", return_value=upload),
            mock.patch.object(app_module.tiktok_publish_store, "get", return_value=tiktok),
        ):
            result = app_module.approved_reviews()
        item = result["items"][0]
        serialized = json.dumps(item)
        for secret in (
            "youtube-private-error", "youtube-event-secret",
            "tiktok-private-error", "tiktok-event-secret",
        ):
            self.assertNotIn(secret, serialized)
        self.assertEqual(item["tiktok_error"], app_module.review_store.SAFE_ERROR_NOTICE)
        self.assertEqual(
            item["upload_events"][0]["error"], app_module.review_store.SAFE_ERROR_NOTICE
        )
        self.assertEqual(
            item["tiktok_events"][0]["error"], app_module.review_store.SAFE_ERROR_NOTICE
        )

    def test_queue_read_endpoints_redact_worker_and_provider_diagnostics(self):
        job = {
            "id": "job-safe", "status": "failed_terminal",
            "error_message": "Authorization: Bearer queue-job-secret",
            "payload": {"topic": "Safe topic"},
        }
        events = [
            {"event_type": "worker_pause", "details": {
                "reason": "Provider response leaked bearer queue-event-secret",
            }},
            {"event_type": "failed", "details": {
                "error_message": "queue-event-error-secret",
            }},
        ]
        with (
            mock.patch.object(app_module, "require_review_permission"),
            mock.patch.object(app_module.queue, "get", return_value=job),
        ):
            safe_job = app_module.get_job("job-safe", x_review_token="review-token")
        with (
            mock.patch.object(app_module, "require_review_permission"),
            mock.patch.object(app_module.queue, "get", return_value=job),
            mock.patch.object(app_module.queue, "events", return_value=events),
        ):
            safe_events = app_module.get_events("job-safe", x_review_token="review-token")
        serialized = json.dumps({"job": safe_job, "events": safe_events})
        for secret in (
            "queue-job-secret", "queue-event-secret", "queue-event-error-secret",
        ):
            self.assertNotIn(secret, serialized)
        self.assertEqual(
            safe_job["error_message"], app_module.review_store.SAFE_ERROR_NOTICE
        )
        self.assertEqual(
            safe_events["events"][0]["details"]["reason"],
            app_module.review_store.SAFE_ERROR_NOTICE,
        )
        self.assertEqual(
            safe_events["events"][1]["details"]["error_message"],
            app_module.review_store.SAFE_ERROR_NOTICE,
        )

    def test_queue_control_read_redacts_system_pause_reason_but_preserves_operator_note(self):
        control = {"paused": True, "pause_reason": "Provider failed with Bearer control-secret",
                   "paused_job_id": "job-safe"}
        events = [
            {"event_type": "paused", "actor": "system",
             "reason": "Provider failed with Bearer event-secret"},
            {"event_type": "paused", "actor": "operator-1",
             "reason": "Maintenance window"},
        ]
        with (
            mock.patch.object(app_module, "require_review_permission"),
            mock.patch.object(app_module.queue, "worker_control", return_value=control),
            mock.patch.object(app_module.queue, "worker_control_events", return_value=events),
        ):
            result = app_module.queue_control(x_review_token="review-token")
        serialized = json.dumps(result)
        self.assertNotIn("control-secret", serialized)
        self.assertNotIn("event-secret", serialized)
        self.assertEqual(
            result["control"]["pause_reason"], app_module.review_store.SAFE_ERROR_NOTICE
        )
        self.assertEqual(
            result["events"][0]["reason"], app_module.review_store.SAFE_ERROR_NOTICE
        )
        self.assertEqual(result["events"][1]["reason"], "Maintenance window")

    def test_production_detail_redacts_raw_error_and_nested_provider_secrets(self):
        record = {
            "job_id": "job-safe",
            "status": "review_pending",
            "error": "Authorization: Bearer production-secret",
            "artifacts": [{
                "stage": "script",
                "artifact_type": "text",
                "artifact_url": None,
                "metadata": {
                    "script": "Safe script",
                    "provider_token": "detail-provider-token",
                    "nested": {"api_key": "detail-api-key", "quality_score": 0.9},
                },
            }],
        }
        with (
            mock.patch.object(app_module, "require_review_permission"),
            mock.patch.object(app_module.production_store, "get", return_value=record),
        ):
            result = app_module.get_production_job("job-safe", x_review_token="review-token")
        serialized = json.dumps(result)
        self.assertNotIn("production-secret", serialized)
        self.assertNotIn("detail-provider-token", serialized)
        self.assertNotIn("detail-api-key", serialized)
        self.assertEqual(result["error"], app_module.review_store.SAFE_ERROR_NOTICE)
        self.assertEqual(result["artifacts"][0]["metadata"]["script"], "Safe script")
        self.assertEqual(result["artifacts"][0]["metadata"]["nested"]["quality_score"], 0.9)

    def test_readiness_requires_queue_and_scheduler_storage(self):
        with mock.patch.object(app_module.queue, "stats", return_value={"total": 0}), \
             mock.patch.object(app_module.schedule_store, "outbox_status",
                               return_value={"counts": {}, "items": []}):
            result = app_module.readiness()
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["checks"], {
            "queue_store": "ok", "scheduler_store": "ok"
        })

    def test_readiness_fails_closed_when_durable_storage_is_unavailable(self):
        with mock.patch.object(app_module.queue, "stats",
                               side_effect=OSError("database unavailable")):
            with self.assertRaises(HTTPException) as unavailable:
                app_module.readiness()
        self.assertEqual(unavailable.exception.status_code, 503)
        self.assertEqual(unavailable.exception.detail,
                         "Application storage is not ready")

    def test_liveness_remains_independent_from_database_readiness(self):
        with mock.patch.object(app_module.queue, "stats",
                               side_effect=OSError("database unavailable")):
            self.assertEqual(app_module.health()["status"], "ok")

    def test_all_operational_routes_require_review_token(self):
        public = {"/api/health", "/api/ready", "/api/brands", "/api/brands/{slug}", "/api/tiktok/oauth/callback", "/api/youtube/oauth/callback"}
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


    def test_per_operator_rbac_uses_token_identity_and_denies_ungranted_actions(self):
        token = "alice-token-" + ("a" * 40)
        with mock.patch.dict(os.environ, {
            "NEXUS_REVIEW_CREDENTIALS_JSON": '{"alice":"' + token + '"}',
            "NEXUS_REVIEW_ROLE_MAP_JSON": '{"alice":["reviewer"]}',
        }, clear=False):
            self.assertEqual(
                app_module.require_review_permission(token, "review.decide"),
                "alice",
            )
            with self.assertRaises(HTTPException) as denied:
                app_module.require_review_permission(token, "publish.execute")
            self.assertEqual(denied.exception.status_code, 403)

    def test_malformed_per_operator_credentials_fail_closed(self):
        with mock.patch.dict(os.environ, {
            "NEXUS_REVIEW_CREDENTIALS_JSON": "not-json",
            "NEXUS_REVIEW_TOKEN": "legacy-token",
        }, clear=False):
            with self.assertRaises(HTTPException) as invalid:
                require_review_access("legacy-token")
            self.assertEqual(invalid.exception.status_code, 503)

    def test_youtube_oauth_routes_and_callback_state_are_protected(self):
        routes = {
            (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", []) or []))): route
            for route in app.routes
        }
        for path, method in (
            ("/api/youtube/oauth/start", "GET"),
            ("/api/youtube/oauth/status", "GET"),
            ("/api/youtube/oauth/verify", "POST"),
            ("/api/youtube/oauth/disconnect", "POST"),
        ):
            route = routes.get((path, (method,)))
            self.assertIsNotNone(route)
            self.assertIn("x_review_token", route.endpoint.__annotations__)

        from starlette.requests import Request
        request = Request({
            "type": "http", "method": "GET", "path": "/api/youtube/oauth/callback",
            "headers": [(b"cookie", b"youtube_oauth_state=state-123")],
            "query_string": b"",
        })
        with mock.patch.object(
            app_module.youtube_oauth_manager, "exchange_code",
            return_value={"connected": True},
        ) as exchange:
            response = app_module.youtube_oauth_callback(
                request, code="one-time-code", state="state-123"
            )
        exchange.assert_called_once_with("one-time-code", "state-123")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/?youtube_oauth=connected")
        self.assertIn("youtube_oauth_state", response.headers.get("set-cookie", ""))

    def test_youtube_oauth_callback_rejects_missing_or_mismatched_state_cookie(self):
        from starlette.requests import Request
        request = Request({
            "type": "http", "method": "GET", "path": "/api/youtube/oauth/callback",
            "headers": [(b"cookie", b"youtube_oauth_state=other-state")],
            "query_string": b"",
        })
        with mock.patch.object(app_module.youtube_oauth_manager, "exchange_code") as exchange:
            response = app_module.youtube_oauth_callback(
                request, code="one-time-code", state="attacker-state"
            )
        exchange.assert_not_called()
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/?youtube_oauth=error")

    def test_policy_evidence_input_accepts_platform_specific_blocking_flags(self):
        body = PolicyEvidenceInput(
            reviewer_id="reviewer-1",
            policy_flags={"tiktok_prohibited_aigc_minor_likeness": True},
        )
        self.assertTrue(body.policy_flags["tiktok_prohibited_aigc_minor_likeness"])

    def test_production_and_schedule_models_accept_platform_selection(self):
        production=ProductionBrief(
            brand="Brain Glitch",region="US",language="English",
            topic="Topic",platforms=["tiktok"]
        )
        schedule=ScheduleInput(
            name="TikTok daily",interval_seconds=86400,brand="Brain Glitch",
            region="US",language="English",topic="Topic",platform="tiktok"
        )
        self.assertEqual(production.platforms,["tiktok"])
        self.assertEqual(schedule.platform,"tiktok")

    def test_tiktok_operational_routes_are_registered_and_token_protected(self):
        protected_paths = {
            "/api/tiktok/oauth/start", "/api/tiktok/oauth/status",
            "/api/tiktok/oauth/disconnect", "/api/tiktok/creator-info",
            "/api/tiktok/publish/{job_id}", "/api/tiktok/publications/{job_id}",
            "/api/tiktok/publications/{job_id}/reconcile",
            "/api/tiktok/publications/{job_id}/refresh-status", "/api/tiktok/metrics",
        }
        routes={getattr(route,"path",""):route for route in app.routes}
        for path in protected_paths:
            with self.subTest(path=path):
                self.assertIn(path,routes)
                self.assertIn("x_review_token",routes[path].endpoint.__annotations__)
        self.assertIn("request",routes["/api/tiktok/oauth/callback"].endpoint.__annotations__)

    def test_youtube_analytics_routes_are_registered_and_token_protected(self):
        routes = {
            (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", []) or []))): route
            for route in app.routes
        }
        refresh = routes.get((
            "/api/youtube/videos/{video_id}/refresh-analytics", ("POST",)
        ))
        report = routes.get((
            "/api/youtube/videos/{video_id}/analytics", ("GET",)
        ))
        self.assertIsNotNone(refresh)
        self.assertIsNotNone(report)
        self.assertIn("x_review_token", refresh.endpoint.__annotations__)
        self.assertIn("x_review_token", report.endpoint.__annotations__)

    def test_youtube_oauth_start_status_and_disconnect_routes_are_registered_and_protected(self):
        routes = {
            (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", []) or []))): route
            for route in app.routes
        }
        for path, method in (
            ("/api/youtube/oauth/start", "GET"),
            ("/api/youtube/oauth/status", "GET"),
            ("/api/youtube/oauth/disconnect", "POST"),
        ):
            route = routes.get((path, (method,)))
            self.assertIsNotNone(route, path)
            self.assertIn("x_review_token", route.endpoint.__annotations__)
        callback = routes.get(("/api/youtube/oauth/callback", ("GET",)))
        self.assertIsNotNone(callback)
        # OAuth redirect callback is public by design; the one-time state and
        # secure HttpOnly cookie protect it instead of the dashboard token.
        self.assertNotIn("x_review_token", callback.endpoint.__annotations__)

    def test_late_upload_resolution_route_is_registered_and_token_protected(self):
        route = next((r for r in app.routes
                      if getattr(r,"path",None)=="/api/youtube/uploads/{job_id}/resolve-late-result"),None)
        self.assertIsNotNone(route)
        self.assertIn("x_review_token",route.endpoint.__annotations__)
        with self.assertRaises(ValidationError):
            YouTubeLateSuccessResolution(operator_id="operator",note="checked without video ID")
        valid=YouTubeLateSuccessResolution(
            attempt_id="attempt-1", operator_id="operator",video_id="yt-video-123",note="verified in Studio"
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

    def test_opportunity_score_includes_selected_competitor_evidence(self):
        body = OpportunityInput(
            title="AI agents explained", currency="USD",
            forecast_source="planning assumptions",
            forecast_views_low=10000, forecast_views_high=30000,
            rpm_low=1, rpm_high=3, cost_low=10, cost_high=20,
            monetization_eligible=True,
            competitor_channel_ids=["channel-1"],
        )
        videos = [
            {"channel_id":"channel-1","title":"AI agents explained for beginners",
             "view_count":9000,"published_at":"2026-11-14"},
            {"channel_id":"channel-1","title":"AI agents change the workplace",
             "view_count":11000,"published_at":"2026-11-13"},
        ]
        with (
            mock.patch("app.require_review_access"),
            mock.patch("app.competitor_store.list_videos", return_value=videos),
            mock.patch("app.opportunity_store.save", side_effect=lambda result: result),
        ):
            result = create_opportunity_score(body, x_review_token="test-token")
        self.assertEqual(result["competitive_context"]["observed_videos"], 2)
        self.assertEqual(result["competitive_context"]["topic_matched_videos"], 2)
        self.assertEqual(result["competitive_context"]["median_matched_views"], 10000)
        self.assertEqual(result["score_breakdown"]["competitor_pressure_penalty"], 6.67)
        self.assertLessEqual(result["priority_score"], 100)

    def test_trend_signal_creates_brand_aware_production_draft(self):
        trend = {
            "id": "trend-abc", "source": "google_news_rss", "region": "US",
            "title": "New AI agent research", "url": "https://news.example/ai",
            "summary": "A research group published new findings.",
            "published_at": "2026-11-15T00:00:00+00:00",
        }
        brand = {
            "slug": "future-leak", "name": "Future Leak", "active": True,
            "config": {
                "positioning": "Grounded emerging technology explainers",
                "audience": "technology-curious adults",
                "tone": ["clear", "grounded"], "risk_level": "elevated",
                "review_rules": ["Distinguish demos from shipped products"],
                "regions": ["US"], "languages": ["en"],
            },
        }
        body = TrendProductionDraft(brand="future-leak", language="en")
        with (
            mock.patch("app.require_review_access"),
            mock.patch("app.trend_store.get", return_value=trend),
            mock.patch("app.brand_store.list", return_value=[brand]),
            mock.patch("app.submit_production", return_value={"job": {"id": "job-from-trend"}}) as submit,
        ):
            result = draft_production_from_trend("trend-abc", body, x_review_token="test-token")
        self.assertEqual(result["job"]["id"], "job-from-trend")
        brief = submit.call_args.args[2]
        self.assertEqual(brief["topic"], "New AI agent research")
        self.assertEqual(brief["brand"], "Future Leak")
        self.assertEqual(brief["trend_context"]["url"], "https://news.example/ai")
        self.assertEqual(brief["brand_profile"]["review_rules"],
                         ["Distinguish demos from shipped products"])
        self.assertEqual(brief["idempotency_key"], "trend:trend-abc:future-leak:en:youtube")

    def test_trend_production_draft_rejects_missing_trend_and_unsupported_region(self):
        body = TrendProductionDraft(brand="future-leak", language="en")
        with (
            mock.patch("app.require_review_access"),
            mock.patch("app.trend_store.get", return_value=None),
        ):
            with self.assertRaises(HTTPException) as missing:
                draft_production_from_trend("missing", body, x_review_token="test-token")
        self.assertEqual(missing.exception.status_code, 404)

        trend = {"id": "trend-kr", "source": "google_news_rss", "region": "KR",
                 "title": "AI", "url": "https://news.example/ai"}
        brand = {"slug": "future-leak", "name": "Future Leak", "active": True,
                 "config": {"regions": ["US"], "languages": ["en"]}}
        with (
            mock.patch("app.require_review_access"),
            mock.patch("app.trend_store.get", return_value=trend),
            mock.patch("app.brand_store.list", return_value=[brand]),
        ):
            with self.assertRaises(HTTPException) as unsupported:
                draft_production_from_trend("trend-kr", body, x_review_token="test-token")
        self.assertEqual(unsupported.exception.status_code, 422)

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
            mock.patch.object(app_module.queue, "get", return_value=job),
            mock.patch.object(app_module.production_pipeline, "execute",
                              side_effect=ProductionLeaseConflict("stale lease")),
            mock.patch.object(app_module.queue, "fail") as fail,
            mock.patch.object(app_module.queue, "pause") as pause,
        ):
            with self.assertRaises(HTTPException) as caught:
                execute_production_job("job-1", body, x_review_token="test-token")
        self.assertEqual(caught.exception.status_code, 409)
        fail.assert_not_called()
        pause.assert_called_once()
    def test_api_policy_blocked_fails_only_the_job_without_pausing_workers(self):
        job = {"id": "job-policy-blocked", "job_type": "short_video_production",
               "status": "running", "worker_id": "worker-1",
               "lease_token": "lease-1", "payload": {"topic": "test"}}
        body = ProductionExecute(worker_id="worker-1", lease_token="lease-1")
        with (
            mock.patch("app.require_review_access"),
            mock.patch.object(app_module.queue, "get", return_value=job),
            mock.patch.object(
                app_module.production_pipeline, "execute",
                side_effect=PolicyBlocked(
                    "policy_preflight", "Production blocked by explicit policy risk flags: deceptive_impersonation",
                    retryable=False,
                ),
            ),
            mock.patch.object(app_module.queue, "fail") as fail,
            mock.patch.object(app_module.queue, "pause") as pause,
        ):
            with self.assertRaises(HTTPException) as caught:
                execute_production_job(
                    "job-policy-blocked", body, x_review_token="test-token"
                )
        self.assertEqual(caught.exception.status_code, 422)
        self.assertEqual(caught.exception.detail, {
            "stage": "policy_preflight",
            "error": "Production blocked by policy preflight.",
            "retryable": False,
        })
        fail.assert_called_once_with(
            "job-policy-blocked", "worker-1", "lease-1",
            "policy_blocked",
            "Production blocked by explicit policy risk flags: deceptive_impersonation",
            False,
        )
        pause.assert_not_called()

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
        self.assertEqual(caught.exception.detail, {
            "stage": "script",
            "error": "Provider request failed; inspect protected server logs for details.",
            "retryable": True,
        })
        self.assertNotIn("provider timeout", json.dumps(caught.exception.detail))
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
    def test_queue_control_endpoints_are_authenticated_and_audited(self):
        body = QueueControlAction(operator_id="operator-1", note="Reviewed worker state")
        control = {"paused": True, "pause_reason": body.note, "paused_job_id": "job-1"}
        events = [{"event_type": "paused", "actor": body.operator_id}]
        with (
            mock.patch("app.require_review_access"),
            mock.patch.object(app_module.queue, "pause", return_value=control) as pause,
            mock.patch.object(app_module.queue, "worker_control", return_value=control),
            mock.patch.object(app_module.queue, "worker_control_events", return_value=events),
        ):
            paused = pause_queue(body, x_review_token="test-token")
        pause.assert_called_once_with(body.note, actor=body.operator_id)
        self.assertTrue(paused["control"]["paused"])
        self.assertEqual(paused["events"], events)

        resumed_control = {"paused": False, "pause_reason": None, "paused_job_id": None}
        with (
            mock.patch("app.require_review_access"),
            mock.patch.object(app_module.queue, "resume", return_value=resumed_control) as resume,
            mock.patch.object(app_module.queue, "worker_control_events", return_value=[]),
        ):
            resumed = resume_queue(body, x_review_token="test-token")
        resume.assert_called_once_with(actor=body.operator_id, note=body.note)
        self.assertFalse(resumed["control"]["paused"])

    def test_queue_resume_rejects_unpaused_queue(self):
        body = QueueControlAction(operator_id="operator-1", note="Checked state")
        with (
            mock.patch("app.require_review_access"),
            mock.patch.object(app_module.queue, "resume", side_effect=ValueError("not paused")),
        ):
            with self.assertRaises(HTTPException) as caught:
                resume_queue(body, x_review_token="test-token")
        self.assertEqual(caught.exception.status_code, 409)
    def test_queue_control_rejects_whitespace_only_fields(self):
        with mock.patch("app.require_review_access"):
            for action in (pause_queue, resume_queue):
                body = QueueControlAction(operator_id="   ", note="   ")
                with self.assertRaises(HTTPException) as caught:
                    action(body, x_review_token="test-token")
                self.assertEqual(caught.exception.status_code, 422)
    def test_review_token_fails_closed(self):
        previous = os.environ.get("NEXUS_REVIEW_TOKEN")
        os.environ["NEXUS_REVIEW_TOKEN"] = "unit-test-secret-with-at-least-32-characters"
        try:
            with self.assertRaises(HTTPException) as missing:
                require_review_access(None)
            self.assertEqual(missing.exception.status_code, 401)
            with self.assertRaises(HTTPException) as invalid:
                require_review_access("wrong-secret")
            self.assertEqual(invalid.exception.status_code, 401)
            self.assertEqual(
                require_review_access("unit-test-secret-with-at-least-32-characters"),
                "legacy-operator",
            )
        finally:
            if previous is None:
                os.environ.pop("NEXUS_REVIEW_TOKEN", None)
            else:
                os.environ["NEXUS_REVIEW_TOKEN"] = previous


    def test_integrity_report_endpoint_enforces_production_read_permission(self):
        reviewer_token = "reviewer-token-" + ("r" * 40)
        analyst_token = "analyst-token-" + ("a" * 40)
        credentials = {"reviewer-one": reviewer_token, "analyst-one": analyst_token}
        roles = {"reviewer-one": ["reviewer"], "analyst-one": ["analyst"]}
        expected = {"unresolved": 0, "items": [], "worker_control": {"paused": False}}
        with mock.patch.dict(os.environ, {
            "NEXUS_REVIEW_CREDENTIALS_JSON": json.dumps(credentials),
            "NEXUS_REVIEW_ROLE_MAP_JSON": json.dumps(roles),
        }, clear=False):
            with mock.patch.object(
                app_module.production_store, "integrity_report", return_value=expected
            ) as report:
                self.assertEqual(
                    app_module.production_integrity_report(
                        limit=13, offset=0, cursor='page-cursor', x_review_token=reviewer_token
                    ), expected
                )
                report.assert_called_once_with(app_module.queue, limit=13, offset=0, cursor='page-cursor')
                with self.assertRaises(HTTPException) as denied:
                    app_module.production_integrity_report(
                        limit=13, offset=17, cursor='page-cursor', x_review_token=analyst_token
                    )
                self.assertEqual(denied.exception.status_code, 403)
                report.assert_called_once()
                with self.assertRaises(HTTPException) as unauthenticated:
                    app_module.production_integrity_report(limit=13, x_review_token=None)
                self.assertEqual(unauthenticated.exception.status_code, 401)
                report.assert_called_once()


    def test_integrity_report_rejects_ambiguous_offset_and_cursor(self):
        with mock.patch.object(app_module, "require_review_permission"):
            with self.assertRaises(HTTPException) as caught:
                app_module.production_integrity_report(
                    limit=10, offset=1, cursor="opaque", x_review_token="token"
                )
        self.assertEqual(caught.exception.status_code, 422)

    def test_integrity_report_maps_invalid_cursor_to_422(self):
        with (
            mock.patch.object(app_module, "require_review_permission"),
            mock.patch.object(app_module.production_store, "integrity_report",
                              side_effect=ValueError("Invalid integrity report cursor")),
        ):
            with self.assertRaises(HTTPException) as caught:
                app_module.production_integrity_report(
                    limit=10, offset=0, cursor="malformed", x_review_token="token"
                )
        self.assertEqual(caught.exception.status_code, 422)
        self.assertEqual(caught.exception.detail, "Invalid integrity report cursor")

    def test_integrity_report_keeps_storage_conflicts_as_409(self):
        with (
            mock.patch.object(app_module, "require_review_permission"),
            mock.patch.object(app_module.production_store, "integrity_report",
                              side_effect=ValueError("database path conflict")),
        ):
            with self.assertRaises(HTTPException) as caught:
                app_module.production_integrity_report(
                    limit=10, offset=0, cursor=None, x_review_token="token"
                )
        self.assertEqual(caught.exception.status_code, 409)

    def test_integrity_report_declares_query_parameter_bounds(self):
        route = next(r for r in app.routes
                     if getattr(r, "path", None) == "/api/production/integrity-report")
        params = {p.name: p for p in route.dependant.query_params}
        limit_constraints = {type(item).__name__: item
                             for item in params["limit"].field_info.metadata}
        offset_constraints = {type(item).__name__: item
                              for item in params["offset"].field_info.metadata}
        cursor_constraints = {type(item).__name__: item
                              for item in params["cursor"].field_info.metadata}
        self.assertEqual((limit_constraints["Ge"].ge, limit_constraints["Le"].le), (1, 200))
        self.assertEqual((offset_constraints["Ge"].ge, offset_constraints["Le"].le),
                         (0, 1000000))
        self.assertEqual(cursor_constraints["MaxLen"].max_length, 512)


    def test_provider_attempt_diagnostics_redact_raw_response_and_errors(self):
        token = "reviewer-token-" + ("r" * 40)
        attempts = [{
            "id": "attempt-1",
            "job_id": "job-safe",
            "stage": "rendering",
            "attempt_number": 1,
            "state": "response_received",
            "started_at": "2026-11-16T00:00:00Z",
            "completed_at": "2026-11-16T00:00:05Z",
            "idempotency_key": "internal-idempotency-secret",
            "provider_request_id": "provider-request-1",
            "response_json": (
                '{"video_url":"https://cdn.example/video.mp4?sig=signed-secret",'
                '"access_token":"provider-access-secret"}'
            ),
            "error": "Authorization: Bearer raw-provider-secret",
        }]
        with (
            mock.patch.object(app_module, "require_review_permission"),
            mock.patch.object(app_module.production_store, "get",
                              return_value={"id": "job-safe"}),
            mock.patch.object(app_module.production_store, "provider_attempts",
                              return_value=attempts),
        ):
            result = app_module.get_production_provider_attempts(
                "job-safe", x_review_token=token
            )
        serialized = json.dumps(result)
        for secret in (
            "signed-secret", "provider-access-secret",
            "raw-provider-secret", "internal-idempotency-secret",
        ):
            self.assertNotIn(secret, serialized)
        self.assertEqual(result["attempts"][0]["id"], "attempt-1")
        self.assertTrue(result["attempts"][0]["has_response"])
        self.assertTrue(result["attempts"][0]["has_error"])
        self.assertEqual(
            result["attempts"][0]["error_message"],
            "상세 오류는 보호된 서버 로그에서 확인하세요.",
        )
        self.assertNotIn("response_json", result["attempts"][0])
        self.assertNotIn("provider_request_id", result["attempts"][0])


    def test_platform_reconciliation_rejects_operator_id_spoofing(self):
        from app import (
            YouTubeUploadReconciliation, YouTubeLateSuccessResolution,
            TikTokPublicationReconciliation,
            reconcile_youtube_upload, resolve_late_youtube_upload,
            reconcile_tiktok_publication,
        )
        cases = [
            (
                reconcile_youtube_upload,
                YouTubeUploadReconciliation(
                    attempt_id="attempt-1", outcome="not_uploaded", confirmed=True,
                    note="Checked channel", operator_id="forged-operator",
                ),
                "youtube_upload_store", "reconcile",
            ),
            (
                resolve_late_youtube_upload,
                YouTubeLateSuccessResolution(
                    attempt_id="attempt-1", operator_id="forged-operator", video_id="late-video",
                    note="Verified late completion",
                ),
                "youtube_upload_store", "resolve_late_success",
            ),
            (
                reconcile_tiktok_publication,
                TikTokPublicationReconciliation(
                    attempt_id="attempt-1", outcome="not_published", confirmed=True,
                    note="Checked creator account", operator_id="forged-operator",
                ),
                "tiktok_publish_store", "reconcile",
            ),
        ]
        for endpoint, body, store_name, method_name in cases:
            with self.subTest(endpoint=endpoint.__name__):
                with (
                    mock.patch.object(
                        app_module, "require_review_permission",
                        return_value="authenticated-operator",
                    ) as authorize,
                    mock.patch.object(
                        getattr(app_module, store_name), method_name
                    ) as mutation,
                ):
                    with self.assertRaises(HTTPException) as caught:
                        endpoint("job-1", body, x_review_token="valid-review-token")
                self.assertEqual(caught.exception.status_code, 403)
                authorize.assert_called_once_with(
                    "valid-review-token", "publish.reconcile"
                )
                mutation.assert_not_called()

    def test_platform_reconciliation_accepts_authenticated_operator_identity(self):
        from app import (
            YouTubeUploadReconciliation, TikTokPublicationReconciliation,
            reconcile_youtube_upload, reconcile_tiktok_publication,
        )
        youtube_body = YouTubeUploadReconciliation(
            attempt_id="attempt-1", outcome="not_uploaded", confirmed=True,
            note="Verified no matching private upload", operator_id="operator-7",
        )
        tiktok_body = TikTokPublicationReconciliation(
            attempt_id="attempt-1", outcome="not_published", confirmed=True,
            note="Verified no matching creator post", operator_id="operator-7",
        )
        with (
            mock.patch.object(
                app_module, "require_review_permission", return_value="operator-7"
            ) as authorize,
            mock.patch.object(
                app_module.youtube_upload_store, "reconcile",
                return_value={"status": "failed"},
            ) as youtube_reconcile,
            mock.patch.object(
                app_module.tiktok_publish_store, "reconcile",
                return_value={"status": "failed"},
            ) as tiktok_reconcile,
        ):
            self.assertEqual(
                reconcile_youtube_upload(
                    "job-youtube", youtube_body, x_review_token="review-token"
                ),
                {"status": "failed"},
            )
            self.assertEqual(
                reconcile_tiktok_publication(
                    "job-tiktok", tiktok_body, x_review_token="review-token"
                ),
                {"status": "failed"},
            )
        self.assertEqual(authorize.call_count, 2)
        youtube_reconcile.assert_called_once_with(
            "job-youtube", "not_uploaded", None,
            "Verified no matching private upload", "operator-7",
            expected_attempt_id="attempt-1",
        )
        tiktok_reconcile.assert_called_once_with(
            "job-tiktok", "not_published", "operator-7",
            "Verified no matching creator post", video_id=None, confirmed=True,
            expected_attempt_id="attempt-1",
        )


    def test_youtube_reconciliation_requires_explicit_confirmation_before_store_mutation(self):
        from app import YouTubeUploadReconciliation, reconcile_youtube_upload
        body = YouTubeUploadReconciliation(
            attempt_id="attempt-1", outcome="not_uploaded", confirmed=False,
            note="Unable to verify", operator_id="operator-1",
        )
        with (
            mock.patch.object(
                app_module, "require_review_permission", return_value="operator-1"
            ) as authorize,
            mock.patch.object(app_module.youtube_upload_store, "reconcile") as mutation,
        ):
            with self.assertRaises(HTTPException) as caught:
                reconcile_youtube_upload("job-1", body, x_review_token="review-token")
        self.assertEqual(caught.exception.status_code, 422)
        authorize.assert_called_once_with("review-token", "publish.reconcile")
        mutation.assert_not_called()

    def test_tiktok_reconciliation_requires_explicit_confirmation_before_store_mutation(self):
        from app import TikTokPublicationReconciliation, reconcile_tiktok_publication
        body = TikTokPublicationReconciliation(
            attempt_id="attempt-1", outcome="not_published", confirmed=False,
            note="Unable to verify", operator_id="operator-1",
        )
        with (
            mock.patch.object(
                app_module, "require_review_permission", return_value="operator-1"
            ) as authorize,
            mock.patch.object(
                app_module.tiktok_publish_store, "reconcile",
                side_effect=app_module.TikTokPublishError(
                    "Explicit confirmation of the TikTok account's remote result is required"
                ),
            ) as mutation,
        ):
            with self.assertRaises(HTTPException) as caught:
                reconcile_tiktok_publication("job-1", body, x_review_token="review-token")
        self.assertEqual(caught.exception.status_code, 409)
        authorize.assert_called_once_with("review-token", "publish.reconcile")
        mutation.assert_called_once_with(
            "job-1", "not_published", "operator-1", "Unable to verify",
            video_id=None, confirmed=False, expected_attempt_id="attempt-1",
        )

    def test_youtube_reconciliation_requires_video_id_for_uploaded_outcome(self):
        from app import YouTubeUploadReconciliation, reconcile_youtube_upload
        body = YouTubeUploadReconciliation(
            attempt_id="attempt-1", outcome="uploaded", confirmed=True, video_id=None,
            note="Operator confirms upload", operator_id="operator-1",
        )
        with (
            mock.patch.object(
                app_module, "require_review_permission", return_value="operator-1"
            ),
            mock.patch.object(app_module.youtube_upload_store, "reconcile") as mutation,
        ):
            with self.assertRaises(HTTPException) as caught:
                reconcile_youtube_upload("job-1", body, x_review_token="review-token")
        self.assertEqual(caught.exception.status_code, 422)
        mutation.assert_not_called()

if __name__ == "__main__":
    unittest.main()


    def test_provider_attempt_reconciliation_requires_explicit_confirmation_and_admin_permission(self):
        from app import ProviderAttemptReconciliationAction, reconcile_provider_attempt
        body=ProviderAttemptReconciliationAction(
            operator_id="admin-1",evidence_reference="provider-console-case-123",
            note="Provider console confirms no job was created.",
            confirmed_not_executed=True)
        with (
            mock.patch.object(app_module,"require_review_permission") as auth,
            mock.patch.object(app_module.production_store,
                "confirm_provider_attempt_not_executed",
                return_value={"state":"not_executed_confirmed"}) as resolve,
        ):
            result=reconcile_provider_attempt(
                "job-1",body,provider_attempt_id="attempt-1",x_review_token="admin-token")
        auth.assert_called_once_with("admin-token","production.provider_reconcile")
        resolve.assert_called_once_with(
            "job-1","attempt-1","admin-1","provider-console-case-123",
            "Provider console confirms no job was created.")
        self.assertEqual(result["reconciliation"]["state"],"not_executed_confirmed")
        self.assertIn("separate operator-controlled",result["warning"])

    def test_provider_attempt_reconciliation_rejects_unconfirmed_outcome(self):
        from app import ProviderAttemptReconciliationAction, reconcile_provider_attempt
        body=ProviderAttemptReconciliationAction(
            operator_id="admin-1",evidence_reference="case-123",
            note="No remote job exists.",confirmed_not_executed=False)
        with mock.patch.object(app_module,"require_review_permission"):
            with self.assertRaises(HTTPException) as caught:
                reconcile_provider_attempt(
                    "job-1",body,provider_attempt_id="attempt-1")
        self.assertEqual(caught.exception.status_code,422)

