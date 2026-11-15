import os
import unittest
import logging
import tempfile
import threading
from pathlib import Path
import app as app_module
from unittest import mock
from fastapi import HTTPException, Response
from types import SimpleNamespace
from pydantic import ValidationError
from app import (app, require_review_access, YouTubeLateSuccessResolution, Enqueue,
                 enqueue, IdempotencyConflict, ProductionExecute, execute_production_job,
                 ProductionLeaseConflict, ProductionBrief, create_production_job,
                 QueueControlAction, queue_control, pause_queue, resume_queue,
                 TrendProductionDraft, draft_production_from_trend,
                 OpportunityInput, create_opportunity_score, TikTokPublishRequest,
                 publish_tiktok_video, refresh_tiktok_publication_status,
                 get_tiktok_publication, approved_reviews, start_tiktok_oauth,
                 tiktok_oauth_status, tiktok_oauth_callback, disconnect_tiktok_oauth,
                 TikTokOAuthAccessLogRedaction, RecommendationSkipFeedback,
                 skip_recommendation_feedback, capture_trend_recommendations,
                 get_job_lifecycle, get_job_lifecycle_consistency, get_lifecycle_queue,
                 operational_health, operational_recovery_plan, get_job_failure_analysis, get_job_lifecycle_overview, metrics_collection_status,
                 capture_recommendation_evaluation_snapshot, list_recommendation_evaluation_snapshots,
                 require_canonical_staged_media, stage_production_media, approve_review,
                 publishing_dashboard, tiktok_metrics, youtube_analytics_metrics)
from production_pipeline import ProviderError
from queue_store import LeaseConflict

class ApiSecurityTests(unittest.TestCase):
    def test_canonical_staged_media_accepts_only_current_job_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            expected=root/"job-1.mp4"
            expected.write_bytes(b"approved-media")
            with mock.patch.object(app_module,"media_stager",SimpleNamespace(
                media_dir=root,staged_path=lambda job_id:root/(job_id+".mp4")
            )):
                self.assertEqual(require_canonical_staged_media("job-1",expected.name),str(expected))
                with self.assertRaises(HTTPException) as caught:
                    require_canonical_staged_media("job-1","other-job.mp4")
                self.assertEqual(caught.exception.status_code,409)

    def test_stage_media_refreshes_existing_job_file_from_current_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            existing=root/"job-1.mp4"
            existing.write_bytes(b"stale-render")
            stager=SimpleNamespace(
                media_dir=root,
                staged_path=lambda job_id:root/(job_id+".mp4"),
                stage=mock.Mock(return_value={"media_path":"job-1.mp4","size_bytes":12}),
            )
            production={"status":"review_pending","artifacts":[{
                "artifact_type":"video","artifact_url":"https://cdn.example/current.mp4"
            }]}
            with mock.patch("app.require_review_access"), \
                 mock.patch.object(app_module,"media_stager",stager), \
                 mock.patch.object(app_module.production_store,"get",return_value=production):
                result=stage_production_media("job-1",x_review_token="test-token")
            stager.stage.assert_called_once_with(
                "job-1","https://cdn.example/current.mp4"
            )
            self.assertEqual(result["media_path"],"job-1.mp4")

    def test_approve_review_binds_canonical_staged_file_into_decision(self):
        staged = Path("test-staged-media.mp4")
        with mock.patch("app.require_review_access"), \
             mock.patch.object(app_module.media_stager, "staged_path", return_value=staged), \
             mock.patch.object(app_module.review_store, "decide", return_value={"decision": "approved"}) as decide:
            result = approve_review(
                "job-1", SimpleNamespace(reviewer_id="reviewer-1", comment="Reviewed"),
                x_review_token="test-token",
            )
        self.assertEqual(result["decision"], "approved")
        self.assertEqual(decide.call_args.kwargs["staged_media_path"], staged)

    def test_canonical_staged_media_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            expected=root/"job-1.mp4"
            expected.write_bytes(b"approved-media")
            other=root/"other.mp4"
            other.write_bytes(b"unapproved-media")
            link=root/"job-1-link.mp4"
            link.symlink_to(other)
            with mock.patch.object(app_module,"media_stager",SimpleNamespace(
                media_dir=root,staged_path=lambda job_id:expected
            )):
                with self.assertRaises(HTTPException) as caught:
                    require_canonical_staged_media("job-1",str(link))
                self.assertEqual(caught.exception.status_code,409)

    def test_failure_analysis_requires_review_access_and_classifies_latest_failure(self):
        job={"id":"job-1","job_type":"short_video_production","status":"failed_retriable",
             "error_code":"provider_rendering","error_message":"Provider connection failed",
             "attempt":1,"max_attempts":3}
        events=[{"event_type":"failed","created_at":"2026-11-15T00:00:00Z",
                 "from_status":"running","to_status":"failed_retriable",
                 "details":{"error_code":"provider_rendering","retryable":True}}]
        with mock.patch("app.require_review_access") as access, \
             mock.patch.object(app_module.queue,"get",return_value=job), \
             mock.patch.object(app_module.queue,"events",return_value=events):
            result=get_job_failure_analysis("job-1",x_review_token="test-token")
        access.assert_called_once_with("test-token")
        self.assertEqual(result["latest_failure"]["category"],"external_outcome_ambiguous")
        self.assertFalse(result["latest_failure"]["retry_authorized"])
        self.assertEqual(result["actions_taken"],[])

    def test_failure_analysis_returns_empty_when_job_has_no_failure_event(self):
        job={"id":"job-2","job_type":"short_video_production","status":"running"}
        with mock.patch("app.require_review_access"), \
             mock.patch.object(app_module.queue,"get",return_value=job), \
             mock.patch.object(app_module.queue,"events",return_value=[]):
            result=get_job_failure_analysis("job-2",x_review_token="test-token")
        self.assertIsNone(result["latest_failure"])
        self.assertTrue(result["read_only"])
    def test_operational_health_requires_review_access_and_returns_snapshot(self):
        with mock.patch("app.require_review_access") as access, \
             mock.patch.object(app_module.queue, "operational_health",
                               return_value={"status":"healthy","read_only":True}) as snapshot:
            result = operational_health(x_review_token="test-token")
        access.assert_called_once_with("test-token")
        snapshot.assert_called_once_with()
        self.assertEqual(result["status"], "healthy")
        self.assertTrue(result["read_only"])

    def test_all_operational_routes_require_review_token(self):
        public = {"/api/health", "/api/brands", "/api/brands/{slug}", "/api/tiktok/oauth/callback"}
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

    def test_tiktok_publish_request_requires_explicit_private_visibility(self):
        required = {
            "media_path": "/media/video.mp4",
            "title": "Approved video",
            "operator_id": "operator-1",
            "explicit_consent": True,
            "brand_content_toggle": False,
            "brand_organic_toggle": False,
        }
        with self.assertRaises(Exception):
            TikTokPublishRequest(**required)
        valid = TikTokPublishRequest(**required, privacy_level="SELF_ONLY")
        self.assertEqual(valid.privacy_level, "SELF_ONLY")
        with self.assertRaises(Exception):
            TikTokPublishRequest(**required, privacy_level="PUBLIC_TO_EVERYONE")

    def test_tiktok_publish_and_status_routes_are_token_protected(self):
        expected = {
            "/api/tiktok/creator-info",
            "/api/tiktok/publish/{job_id}",
            "/api/tiktok/publications/{job_id}",
            "/api/tiktok/publications/{job_id}/refresh-status",
        }
        found = {getattr(route, "path", ""): route for route in app.routes
                 if getattr(route, "path", "") in expected}
        self.assertEqual(set(found), expected)
        for route in found.values():
            self.assertIn("x_review_token", route.endpoint.__annotations__)

    def test_unified_publishing_dashboard_is_authenticated_read_only_and_keeps_platform_states_separate(self):
        youtube = [{
            "job_id": "job-youtube", "status": "reconciliation_required",
            "attempt_id": "yt-attempt", "video_id": None,
            "updated_at": "2026-11-15T10:00:00Z", "events": [
                {"event_type": "upload_timeout", "created_at": "2026-11-15T09:59:00Z"}
            ], "reconciliation_required": True, "last_error": "timeout",
        }]
        tiktok = [{
            "job_id": "job-tiktok", "status": "processing",
            "attempt_id": "tt-attempt", "publish_id": "publish-1",
            "video_id": None, "privacy_level": "SELF_ONLY",
            "updated_at": "2026-11-15T10:01:00Z", "events": [],
            "error": None, "fail_reason": None,
        }]
        with mock.patch("app.require_review_access") as access, \
             mock.patch.object(app_module.youtube_upload_store, "list_recent", return_value=youtube) as yt_list, \
             mock.patch.object(app_module.tiktok_publish_store, "list_recent", return_value=tiktok) as tt_list:
            result = publishing_dashboard(limit=25, x_review_token="test-token")
        access.assert_called_once_with("test-token")
        yt_list.assert_called_once_with(25)
        tt_list.assert_called_once_with(25)
        self.assertEqual(result["platforms"]["youtube"]["status_counts"], {"reconciliation_required": 1})
        self.assertEqual(result["platforms"]["tiktok"]["status_counts"], {"processing": 1})
        self.assertEqual(result["items"][0]["platform"], "tiktok")
        self.assertEqual(result["items"][1]["platform"], "youtube")
        self.assertTrue(result["items"][1]["reconciliation_required"])
        self.assertEqual(result["items"][0]["privacy_level"], "SELF_ONLY")
        self.assertTrue(result["read_only"])
        self.assertEqual(result["actions_taken"], [])

    def test_unified_publishing_dashboard_rejects_invalid_limit(self):
        with mock.patch("app.require_review_access"):
            with self.assertRaises(HTTPException) as caught:
                publishing_dashboard(limit=201, x_review_token="test-token")
        self.assertEqual(caught.exception.status_code, 422)

    def test_unified_publishing_dashboard_route_is_token_protected(self):
        route = next(route for route in app.routes
                     if getattr(route, "path", "") == "/api/publishing/dashboard")
        self.assertIn("x_review_token", route.endpoint.__annotations__)

    def test_approved_review_queue_includes_tiktok_status_for_selected_platform(self):
        item = {
            "job_id": "job-tiktok",
            "artifacts": [{
                "stage": "script", "artifact_type": "text",
                "metadata": {"policy_preflight": {
                    "policy_version": app_module.POLICY_VERSION,
                    "status": "ready_for_human_review",
                    "platforms": ["youtube", "tiktok"],
                    "approval_blockers": [],
                }},
            }],
        }
        publication = {"status": "processing", "publish_id": "publish-1",
                       "video_id": None, "events": [], "is_aigc": True}
        with (
            mock.patch("app.require_review_access"),
            mock.patch("app.review_store.list_approved", return_value=[item]),
            mock.patch("app.youtube_upload_store.get", return_value=None),
            mock.patch("app.tiktok_publish_store.get", return_value=publication),
        ):
            result = approved_reviews(limit=50, x_review_token="test-token")
        self.assertEqual(result["items"][0]["tiktok_status"], "processing")
        self.assertTrue(result["items"][0]["tiktok_eligible"])
        self.assertEqual(result["items"][0]["tiktok_publish_id"], "publish-1")

    def test_unified_lifecycle_overview_combines_all_stages_read_only(self):
        trace={"job":{"id":"job-1","status":"review_pending","updated_at":"2026-11-15"},
               "production":{"status":"review_pending","current_stage":"rendering",
                             "brand":"Brand","topic":"Topic","updated_at":"2026-11-15",
                             "artifacts":[{"id":"artifact-1"}]},
               "review":{"latest":{"decision":"approved","id":"review-1"}},
               "publishing":{"youtube":{"status":"uploaded","video_id":"yt-1"},
                             "tiktok":{"status":"send_to_inbox","publish_id":"tt-1"}},
               "timeline":[]}
        consistency={"status":"consistent","findings":[],"read_only":True}
        recovery={"steps":[],"retry_policy":"operator-only","read_only":True}
        failure={"latest_failure":None,"read_only":True}
        with mock.patch("app.require_review_access") as access, \
             mock.patch("app.get_job_lifecycle",return_value=trace), \
             mock.patch("app.get_job_lifecycle_consistency",return_value=consistency), \
             mock.patch("app.get_job_recovery_plan",return_value=recovery), \
             mock.patch("app.get_job_failure_analysis",return_value=failure):
            result=get_job_lifecycle_overview("job-1",x_review_token="test-token")
        access.assert_called_once_with("test-token")
        self.assertEqual(result["summary"]["brand"],"Brand")
        self.assertEqual([x["stage"] for x in result["stages"]],
                         ["queue","production","human_review","youtube","tiktok"])
        self.assertEqual(result["stages"][-1]["status"],"send_to_inbox")
        self.assertTrue(result["read_only"])
        self.assertFalse(result["automatic_retry_performed"])
        self.assertFalse(result["remote_status_refresh_performed"])
        self.assertFalse(result["publishing_performed"])
    def test_lifecycle_endpoint_returns_joined_authoritative_records(self):
        job={"id":"job-1","job_type":"short_video_production","status":"review_pending"}
        production={"job_id":"job-1","status":"review_pending","artifacts":[{"id":7,"stage":"rendering","created_at":"2026-11-15T08:00:00Z"}]}
        decisions=[{"id":1,"job_id":"job-1","decision":"approved","created_at":"2026-11-15T08:02:00Z"}]
        youtube={"job_id":"job-1","status":"uploaded","video_id":"yt-1","events":[{"event_type":"upload_completed","outcome":"uploaded","created_at":"2026-11-15T08:04:00Z","attempt_id":"yt-attempt-1","video_id":"yt-1"}]}
        tiktok={"job_id":"job-1","status":"send_to_inbox","publish_id":"tt-1","events":[{"event_type":"status_refreshed","outcome":"SEND_TO_USER_INBOX","created_at":"2026-11-15T08:05:00Z","attempt_id":"tt-attempt-1","publish_id":"tt-1"}]}
        with (
            mock.patch("app.require_review_access"),
            mock.patch("app.queue.get",return_value=job),
            mock.patch("app.queue.events",return_value=[{"event_type":"completed"}]),
            mock.patch("app.production_store.get",return_value=production),
            mock.patch("app.review_store.history",return_value=decisions),
            mock.patch("app.youtube_upload_store.get",return_value=youtube),
            mock.patch("app.tiktok_publish_store.get",return_value=tiktok),
        ):
            result=get_job_lifecycle("job-1",x_review_token="test-token")
        self.assertEqual(result["job"]["status"],"review_pending")
        self.assertEqual(result["production"]["status"],"review_pending")
        self.assertEqual(result["review"]["latest"]["decision"],"approved")
        self.assertEqual(result["publishing"]["youtube"]["video_id"],"yt-1")
        self.assertEqual(result["publishing"]["tiktok"]["status"],"send_to_inbox")
        self.assertEqual(result["queue_events"][0]["event_type"],"completed")
        timeline=result["timeline"]
        self.assertEqual([item["stage"] for item in timeline],
                         ["queue","production","human_review","youtube","tiktok"])
        self.assertEqual(timeline[-1]["attempt_id"],"tt-attempt-1")
        self.assertEqual(timeline[-1]["outcome"],"SEND_TO_USER_INBOX")

    def test_lifecycle_consistency_endpoint_returns_read_only_report(self):
        job = {
            "id": "job-1", "job_type": "short_video_production",
            "status": "review_pending", "worker_id": None,
            "lease_token": None, "lease_expires_at": None,
        }
        with (
            mock.patch("app.require_review_access") as access,
            mock.patch("app.queue.get", return_value=job),
            mock.patch("app.production_store.get", return_value={"status": "approved"}),
            mock.patch("app.review_store.history", return_value=[
                {"decision": "approved", "id": 1}
            ]),
            mock.patch("app.youtube_upload_store.get", return_value=None),
            mock.patch("app.tiktok_publish_store.get", return_value=None),
        ):
            result = get_job_lifecycle_consistency(
                "job-1", x_review_token="test-token"
            )
        access.assert_called_once_with("test-token")
        self.assertEqual(result["status"], "consistent")
        self.assertTrue(result["read_only"])
        self.assertFalse(result["automatic_retry_performed"])
        self.assertEqual(result["findings"], [])

    def test_lifecycle_consistency_endpoint_rejects_nonproduction_jobs(self):
        with (
            mock.patch("app.require_review_access"),
            mock.patch("app.queue.get", return_value={
                "id": "job-2", "job_type": "other", "status": "completed"
            }),
        ):
            with self.assertRaises(HTTPException) as caught:
                get_job_lifecycle_consistency(
                    "job-2", x_review_token="test-token"
                )
        self.assertEqual(caught.exception.status_code, 409)

    def test_global_lifecycle_queue_is_bounded_and_returns_risk_summary(self):
        jobs = [{
            "id":"job-global-1","job_type":"short_video_production",
            "status":"review_pending","attempt":1,"max_attempts":3,
            "updated_at":"2026-11-15T08:00:00Z","error_code":None,
        }]
        with (
            mock.patch("app.require_review_access") as access,
            mock.patch("app.queue.list_jobs",return_value={
                "items":jobs,"total":121,"limit":25,"offset":50,
                "status_counts":{"review_pending":121},
            }) as listing,
            mock.patch("app.queue.lifecycle_summaries",return_value={
                "job-global-1":{
                    "production_status":"approved","current_stage":"review",
                    "brand":"NEXUS","topic":"AI trends",
                    "latest_review_decision":"approved",
                    "youtube_status":None,"youtube_attempt_id":None,"youtube_video_id":None,
                    "youtube_events":[],"tiktok_status":None,"tiktok_attempt_id":None,
                    "tiktok_video_id":None,"tiktok_events":[],
                }
            }) as summaries,
        ):
            result=get_lifecycle_queue(limit=25,offset=50,status="review_pending",
                                       x_review_token="test-token")
        access.assert_called_once_with("test-token")
        listing.assert_called_once_with(job_type="short_video_production",
                                        limit=25,offset=50,status="review_pending")
        summaries.assert_called_once_with(["job-global-1"])
        self.assertEqual(result["total"],121)
        self.assertEqual(result["items"][0]["job_id"],"job-global-1")
        self.assertEqual(result["risk_counts"]["consistent"],1)
        self.assertEqual(result["production_status_counts"]["approved"],1)
        self.assertTrue(result["read_only"])
        self.assertFalse(result["automatic_retry_performed"])
        self.assertNotIn("payload",result["items"][0])

    def test_global_lifecycle_queue_marks_missing_production_as_blocker(self):
        with (
            mock.patch("app.require_review_access"),
            mock.patch("app.queue.list_jobs",return_value={
                "items":[{"id":"job-missing","status":"queued","attempt":0,
                          "max_attempts":3}],
                "total":1,"limit":50,"offset":0,"status_counts":{"queued":1},
            }),
            mock.patch("app.queue.lifecycle_summaries",return_value={"job-missing":{}}),
        ):
            result=get_lifecycle_queue(x_review_token="test-token")
        self.assertEqual(result["items"][0]["risk_status"],"blocked")
        self.assertEqual(result["items"][0]["blocker_count"],1)
        self.assertEqual(result["risk_counts"]["missing_production"],1)

    def test_global_lifecycle_queue_rejects_unknown_status_filter(self):
        with mock.patch("app.require_review_access"):
            with self.assertRaises(HTTPException) as caught:
                get_lifecycle_queue(status="all_jobs",x_review_token="test-token")
        self.assertEqual(caught.exception.status_code,422)

    def test_lifecycle_endpoint_rejects_nonproduction_queue_jobs(self):
        with (
            mock.patch("app.require_review_access"),
            mock.patch("app.queue.get",return_value={
                "id":"job-2","job_type":"other","status":"completed"}),
        ):
            with self.assertRaises(HTTPException) as caught:
                get_job_lifecycle("job-2",x_review_token="test-token")
        self.assertEqual(caught.exception.status_code,409)

    def test_tiktok_oauth_start_and_status_routes_are_token_protected(self):
        expected = {"/api/tiktok/oauth/start", "/api/tiktok/oauth/status",
                    "/api/tiktok/oauth/disconnect"}
        found = {getattr(route, "path", ""): route for route in app.routes
                 if getattr(route, "path", "") in expected}
        self.assertEqual(set(found), expected)
        for route in found.values():
            self.assertIn("x_review_token", route.endpoint.__annotations__)

    def test_tiktok_oauth_start_returns_authorization_url(self):
        response = Response()
        with (
            mock.patch("app.require_review_access"),
            mock.patch("app.tiktok_oauth_manager.start_authorization",
                       return_value={"authorization_url": "https://www.tiktok.com/v2/auth/authorize/?state=x",
                                     "state": "state-x", "expires_in": 600}),
        ):
            result = start_tiktok_oauth(response=response, x_review_token="test-token")
        self.assertIn("authorization_url", result)
        self.assertIn("tiktok_oauth_state=state-x", response.headers["set-cookie"])
        self.assertIn("httponly", response.headers["set-cookie"].lower())
        self.assertIn("secure", response.headers["set-cookie"].lower())

    def test_tiktok_oauth_disconnect_revokes_connected_account(self):
        with (
            mock.patch("app.require_review_access"),
            mock.patch("app.os.getenv", return_value=None),
            mock.patch("app.tiktok_oauth_manager.disconnect",
                       return_value={"connected": False, "status": "disconnected"}) as disconnect,
        ):
            result = disconnect_tiktok_oauth(x_review_token="test-token")
        self.assertEqual(result["status"], "disconnected")
        disconnect.assert_called_once()

    def test_tiktok_oauth_callback_consumes_code_and_redirects_back_to_portal(self):
        with mock.patch("app.tiktok_oauth_manager.exchange_code",
                        return_value={"connected": True, "open_id": "creator-1"}) as exchange:
            result = tiktok_oauth_callback(
                request=SimpleNamespace(cookies={"tiktok_oauth_state": "state-1"}),
                code="code-1", state="state-1"
            )
        self.assertEqual(result.status_code, 303)
        self.assertIn("tiktok_oauth=connected", result.headers["location"])
        exchange.assert_called_once_with("code-1", "state-1")

    def test_recommendation_snapshot_returns_stable_candidate_ids(self):
        ranked = [{
            "trend": {"id": "trend-1", "title": "AI"},
            "brand_candidates": [{"brand": "alpha", "brand_name": "Alpha"}],
        }]
        exposure = {
            "run_id": "run-1",
            "recorded_candidates": 1,
            "candidate_ids": [{
                "candidate_id": "candidate-1",
                "trend_id": "trend-1",
                "brand_slug": "alpha",
            }],
            "deduplicated": False,
        }
        with (
            mock.patch("app.require_review_access"),
            mock.patch("app._build_trend_recommendations", return_value=ranked),
            mock.patch("app.recommendation_evaluation_store.record_run",
                       return_value=exposure),
        ):
            result = capture_trend_recommendations(
                region="US", limit=20, x_review_token="test-token"
            )
        self.assertEqual(
            result["items"][0]["brand_candidates"][0]["evaluation_candidate_id"],
            "candidate-1",
        )
        self.assertEqual(result["evaluation_run_id"], "run-1")

    def test_evaluation_snapshot_capture_requires_review_access_and_persists(self):
        evaluation = {
            "status": "holdout_available", "selected_production_count": 12,
            "measured_outcome_count": 12, "holdout_run_count": 2,
            "holdout_score_views_spearman": 0.75,
            "ranking_score_adjustment_enabled": False,
        }
        snapshot = {
            "snapshot_id": "snapshot-1", "created_at": "2026-11-15T00:00:00+00:00",
            "deduplicated": False, "input_fingerprint": "fingerprint-1",
        }
        with (
            mock.patch("app.require_review_access") as access,
            mock.patch.object(app_module.performance_analyzer, "analyze",
                              return_value=evaluation),
            mock.patch.object(app_module.recommendation_evaluation_store,
                              "evaluate", return_value=evaluation),
            mock.patch.object(app_module.recommendation_evaluation_store,
                              "record_evaluation_snapshot", return_value=snapshot) as record,
        ):
            result = capture_recommendation_evaluation_snapshot(x_review_token="test-token")
        access.assert_called_once_with("test-token")
        record.assert_called_once_with(evaluation)
        self.assertEqual(result["snapshot_id"], "snapshot-1")
        self.assertFalse(result["ranking_score_adjustment_enabled"])

    def test_evaluation_snapshot_history_is_authenticated_and_bounded(self):
        with (
            mock.patch("app.require_review_access") as access,
            mock.patch.object(app_module.recommendation_evaluation_store,
                              "list_evaluation_snapshots",
                              return_value={"items": [], "count": 0, "limit": 20,
                                            "immutable": True}) as listing,
        ):
            result = list_recommendation_evaluation_snapshots(
                limit=500, x_review_token="test-token"
            )
        access.assert_called_once_with("test-token")
        listing.assert_called_once_with(500)
        self.assertTrue(result["immutable"])

    def test_recommendation_skip_feedback_is_token_protected(self):
        route = next(route for route in app.routes
                     if getattr(route, "path", "") == "/api/recommendations/feedback/skip")
        self.assertIn("x_review_token", route.endpoint.__annotations__)

    def test_recommendation_skip_feedback_records_operator_decision(self):
        body = RecommendationSkipFeedback(
            trend_id="trend-1", brand_slug="alpha",
            recommendation_candidate_id="candidate-1",
            reviewer_id="reviewer-1", reason="Already covered",
        )
        with (
            mock.patch("app.require_review_access"),
            mock.patch("app.recommendation_evaluation_store.record_skip",
                       return_value={"recorded": True, "candidate_id": "candidate-1"}) as record,
        ):
            result = skip_recommendation_feedback(body, x_review_token="test-token")
        self.assertTrue(result["recorded"])
        record.assert_called_once_with(
            "trend-1", "alpha", "reviewer-1", "Already covered",
            candidate_id="candidate-1",
        )

    def test_tiktok_oauth_callback_query_is_redacted_from_access_logs(self):
        record = logging.LogRecord(
            "uvicorn.access", logging.INFO, __file__, 1,
            '%s - "%s %s HTTP/%s" %s',
            ("127.0.0.1", "GET",
             "/api/tiktok/oauth/callback?code=secret-code&state=secret-state",
             "1.1", 303),
            None,
        )
        self.assertTrue(TikTokOAuthAccessLogRedaction().filter(record))
        message = record.getMessage()
        self.assertNotIn("secret-code", message)
        self.assertNotIn("secret-state", message)
        self.assertIn("[REDACTED]", message)

    def test_tiktok_oauth_callback_rejects_state_not_bound_to_browser_cookie(self):
        with mock.patch("app.tiktok_oauth_manager.exchange_code") as exchange:
            result = tiktok_oauth_callback(
                request=SimpleNamespace(cookies={"tiktok_oauth_state": "different"}),
                code="code-1", state="state-1"
            )
        self.assertIn("tiktok_oauth=error", result.headers["location"])
        exchange.assert_not_called()

    def test_tiktok_oauth_status_never_returns_token_values(self):
        with (
            mock.patch("app.require_review_access"),
            mock.patch("app.tiktok_oauth_manager.status",
                       return_value={"connected": True, "open_id": "creator-1"}),
        ):
            result = tiktok_oauth_status(x_review_token="test-token")
        self.assertTrue(result["connected"])
        self.assertNotIn("access_token", result)
        self.assertNotIn("refresh_token", result)

    def test_tiktok_creator_info_route_returns_available_privacy_options(self):
        with (
            mock.patch("app.require_review_access"),
            mock.patch("app.tiktok_publisher.creator_info",
                       return_value={"privacy_level_options": ["SELF_ONLY"]}),
        ):
            result = app_module.get_tiktok_creator_info(x_review_token="test-token")
        self.assertEqual(result["privacy_level_options"], ["SELF_ONLY"])

    def test_tiktok_publish_requires_explicit_consent_and_passes_it_through(self):
        body = TikTokPublishRequest(
            media_path="video.mp4", title="Test AI short",
            operator_id="operator-1", privacy_level="SELF_ONLY", explicit_consent=True,
            brand_content_toggle=False, brand_organic_toggle=False
        )
        with (
            mock.patch("app.require_review_access"),
            mock.patch("app.require_canonical_staged_media",return_value="/staged/job-1.mp4") as validate_path,
            mock.patch("app.tiktok_publisher.publish_private_approved",
                       return_value={"status": "uploading"}) as publish,
        ):
            result = publish_tiktok_video("job-1", body, x_review_token="test-token")
        self.assertEqual(result["status"], "uploading")
        self.assertTrue(publish.call_args.kwargs["explicit_consent"])
        self.assertEqual(publish.call_args.kwargs["privacy_level"], "SELF_ONLY")
        self.assertFalse(publish.call_args.kwargs["brand_content_toggle"])
        self.assertFalse(publish.call_args.kwargs["brand_organic_toggle"])
        self.assertEqual(publish.call_args.args[0], "job-1")
        validate_path.assert_called_once_with("job-1","video.mp4")
        self.assertEqual(publish.call_args.args[1],"/staged/job-1.mp4")

    def test_tiktok_publication_status_endpoints_return_missing_record_as_404(self):
        with (
            mock.patch("app.require_review_access"),
            mock.patch("app.tiktok_publish_store.get", return_value=None),
        ):
            with self.assertRaises(HTTPException) as caught:
                get_tiktok_publication("missing", x_review_token="test-token")
        self.assertEqual(caught.exception.status_code, 404)

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
        body = TrendProductionDraft(
            brand="future-leak", language="en",
            recommendation_candidate_id="exposure-candidate-1",
        )
        with (
            mock.patch("app.require_review_access"),
            mock.patch("app.trend_store.get", return_value=trend),
            mock.patch("app.brand_store.list", return_value=[brand]),
            mock.patch("app.submit_production", return_value={"job": {"id": "job-from-trend"}}) as submit,
            mock.patch("app.recommendation_evaluation_store.link_production",
                       return_value={"linked": True, "candidate_id": "exposure-candidate-1"}) as link,
        ):
            result = draft_production_from_trend("trend-abc", body, x_review_token="test-token")
        self.assertEqual(result["job"]["id"], "job-from-trend")
        brief = submit.call_args.args[2]
        self.assertEqual(brief["topic"], "New AI agent research")
        self.assertEqual(brief["brand"], "Future Leak")
        self.assertEqual(brief["trend_context"]["url"], "https://news.example/ai")
        self.assertEqual(brief["brand_profile"]["review_rules"],
                         ["Distinguish demos from shipped products"])
        self.assertEqual(brief["idempotency_key"], "trend:trend-abc:future-leak:en")
        link.assert_called_once_with(
            "trend-abc", "future-leak", "job-from-trend",
            candidate_id="exposure-candidate-1",
        )
        self.assertTrue(result["recommendation_evaluation_link"]["linked"])

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
            "job-1", job["payload"], worker_id="worker-1",
            lease_token="lease-1", stop_event=mock.ANY
        )
        self.assertIsInstance(execute.call_args.kwargs["stop_event"], __import__("threading").Event)
        finish.assert_called_once()
        reconcile.assert_called_once_with(app_module.queue)

    def test_api_production_execution_stops_when_heartbeat_loses_lease(self):
        job = {"id": "job-heartbeat", "job_type": "short_video_production",
               "status": "running", "worker_id": "worker-1",
               "lease_token": "lease-1", "payload": {"topic": "test"}}
        body = ProductionExecute(worker_id="worker-1", lease_token="lease-1")
        observed_stop = threading.Event()

        def wait_for_lease_loss(*args, **kwargs):
            stop_event = kwargs["stop_event"]
            if stop_event.wait(timeout=2):
                observed_stop.set()
            return {"artifacts": []}

        with (
            mock.patch("app.require_review_access"),
            mock.patch.object(app_module.queue, "lease_seconds", 0.3),
            mock.patch.object(app_module.queue, "get", return_value=job),
            mock.patch.object(app_module.queue, "heartbeat",
                              side_effect=LeaseConflict("lease ownership lost")),
            mock.patch.object(app_module.queue, "pause") as pause,
            mock.patch.object(app_module.queue, "finish") as finish,
            mock.patch.object(app_module.production_pipeline, "execute",
                              side_effect=wait_for_lease_loss),
        ):
            with self.assertRaises(HTTPException) as caught:
                execute_production_job(
                    "job-heartbeat", body, x_review_token="test-token"
                )

        self.assertEqual(caught.exception.status_code, 409)
        self.assertTrue(observed_stop.is_set())
        finish.assert_not_called()
        pause.assert_called_once()

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
            mock.patch.object(app_module.queue, "fail",
                              return_value={"status": "failed_retriable"}) as fail,
            mock.patch.object(app_module.queue, "pause") as pause,
        ):
            with self.assertRaises(HTTPException) as caught:
                execute_production_job("job-provider", body, x_review_token="test-token")
        self.assertEqual(caught.exception.status_code, 502)
        fail.assert_called_once()
        self.assertTrue(caught.exception.detail["retryable"])
        pause.assert_not_called()

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
        body = QueueControlAction(operator_id="operator-1", note="Reviewed worker state", recovery_confirmed=True)
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

    def test_queue_resume_requires_explicit_recovery_confirmation(self):
        body = QueueControlAction(operator_id="operator-1", note="Checked state")
        with mock.patch("app.require_review_access"):
            with self.assertRaises(HTTPException) as caught:
                resume_queue(body, x_review_token="test-token")
        self.assertEqual(caught.exception.status_code, 422)

    def test_queue_resume_is_blocked_by_operational_health_signals(self):
        body = QueueControlAction(operator_id="operator-1", note="Checked state", recovery_confirmed=True)
        with mock.patch("app.require_review_access"), \
             mock.patch.object(app_module.queue, "operational_health", return_value={"blockers":[{"code":"worker_lease_expired"}]}), \
             mock.patch.object(app_module.queue, "resume") as resume:
            with self.assertRaises(HTTPException) as caught:
                resume_queue(body, x_review_token="test-token")
        self.assertEqual(caught.exception.status_code, 409)
        resume.assert_not_called()

    def test_recovery_plan_requires_review_access_and_returns_operator_checks(self):
        snapshot={"blockers":[],"queue":{"paused":True},"leases":{"expired_running":0,"running_missing_ownership":0}}
        with mock.patch("app.require_review_access") as access, \
             mock.patch.object(app_module.queue, "operational_health", return_value=snapshot):
            result=operational_recovery_plan(x_review_token="test-token")
        access.assert_called_once_with("test-token")
        self.assertTrue(result["resume_allowed"])
        self.assertEqual(len(result["operator_checks"]),4)
        self.assertEqual(result["actions_taken"],[])
    def test_queue_resume_rejects_unpaused_queue(self):
        body = QueueControlAction(operator_id="operator-1", note="Checked state", recovery_confirmed=True)
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

    def test_youtube_analytics_metrics_endpoint_is_authenticated_bounded_and_read_only(self):
        sample = [{"video_id": "video-1", "views": 100, "average_view_percentage": 75.5}]
        with mock.patch("app.require_review_access") as access, \
             mock.patch.object(app_module.youtube_analytics_store, "recent_metrics",
                               return_value=sample) as recent:
            result = youtube_analytics_metrics(limit=999, x_review_token="test-token")
        access.assert_called_once_with("test-token")
        recent.assert_called_once_with(app_module.youtube_upload_store, 200)
        self.assertEqual(result["items"], sample)
        self.assertEqual(result["limit"], 200)
        self.assertEqual(result["ranking_score_adjustment"], 0)
        self.assertTrue(result["read_only"])

    def test_tiktok_metrics_endpoint_is_authenticated_bounded_and_read_only(self):
        sample = [{"video_id": "video-1", "view_count": 10, "privacy_level": "SELF_ONLY"}]
        with mock.patch("app.require_review_access") as access, \
             mock.patch.object(app_module.tiktok_metrics_store, "recent_metrics",
                               return_value=sample) as recent:
            result = tiktok_metrics(limit=500, x_review_token="test-token")
        access.assert_called_once_with("test-token")
        recent.assert_called_once_with(app_module.tiktok_publish_store, 200)
        self.assertEqual(result["items"], sample)
        self.assertEqual(result["limit"], 200)
        self.assertEqual(result["ranking_score_adjustment"], 0)
        self.assertTrue(result["read_only"])

    def test_metrics_collection_status_is_authenticated_and_discloses_platform_scopes(self):
        with mock.patch("app.require_review_access") as access, \
             mock.patch.object(app_module.youtube_upload_store, "metrics_collection_status",
                               return_value={"platform": "youtube", "status": "succeeded",
                                             "coverage": {}, "read_only": True}), \
             mock.patch.object(app_module.youtube_analytics_store, "status",
                               return_value={"platform": "youtube_analytics", "status": "not_started",
                                             "last_success_at": None, "requested": 0,
                                             "available_metrics": ["averageViewPercentage"],
                                             "scope_required": "https://www.googleapis.com/auth/yt-analytics.readonly",
                                             "read_only": True}), \
             mock.patch.object(app_module.tiktok_metrics_store, "status",
                               return_value={"platform": "tiktok", "status": "not_started",
                                             "coverage": {}, "available_metrics": ["view_count", "like_count", "comment_count", "share_count"],
                                             "read_only": True}), \
             mock.patch.object(app_module.tiktok_oauth_manager, "status",
                               return_value={"connected": False, "scope": ""}):
            result = metrics_collection_status(x_review_token="test-token")
        access.assert_called_once_with("test-token")
        self.assertTrue(result["read_only"])
        tiktok = result["platforms"]["tiktok"]
        self.assertEqual(tiktok["status"], "scope_missing")
        self.assertEqual(tiktok["required_scope"], "video.list")
        self.assertFalse(tiktok["scope_authorized"])
        self.assertIn("share_count", tiktok["available_metrics"])
        self.assertIn("swipe_away_rate",
                      result["platforms"]["youtube"]["unavailable_metrics"])
        analytics = result["platforms"]["youtube_analytics"]
        self.assertEqual(analytics["status"], "scope_unverified")
        self.assertEqual(analytics["scope_required"], "https://www.googleapis.com/auth/yt-analytics.readonly")
        self.assertFalse(analytics["scope_authorized"])




    def test_recommendation_experiment_routes_are_authenticated_and_shadow_only(self):
        from app import (
            create_recommendation_experiment, list_recommendation_experiments,
            assign_recommendation_experiment_shadow, recommendation_experiment_report,
            RecommendationExperimentCreate, RecommendationExperimentAssignment,
        )
        created = {
            "experiment_id":"exp-1","status":"draft","assignment_mode":"shadow_only",
            "live_assignment_enabled":False,"ranking_score_adjustment":0,
        }
        with mock.patch("app.require_review_access") as access, \
             mock.patch.object(app_module.recommendation_evaluation_store,
                               "create_experiment",return_value=created):
            result=create_recommendation_experiment(
                RecommendationExperimentCreate(name="test",operator_id="operator"),
                x_review_token="token",
            )
        self.assertEqual(result["experiment_id"],"exp-1")
        access.assert_called_once_with("token")
        with mock.patch("app.require_review_access"), \
             mock.patch.object(app_module.recommendation_evaluation_store,
                               "assign_shadow",return_value={
                                   "assignment_mode":"shadow_only",
                                   "recommendation_served":False,
                                   "production_behavior_changed":False,
                               }):
            assigned=assign_recommendation_experiment_shadow(
                "exp-1",RecommendationExperimentAssignment(participant_key="user"),
                x_review_token="token",
            )
        self.assertFalse(assigned["recommendation_served"])
        with mock.patch("app.require_review_access"), \
             mock.patch.object(app_module.recommendation_evaluation_store,
                               "list_experiments",return_value={"items":[],"count":0}), \
             mock.patch.object(app_module.recommendation_evaluation_store,
                               "experiment_report",return_value={"live_assignment_enabled":False}):
            self.assertEqual(list_recommendation_experiments(x_review_token="token")["count"],0)
            self.assertFalse(recommendation_experiment_report("exp-1",x_review_token="token")["live_assignment_enabled"])

    def test_recommendation_experiment_integrity_route_is_authenticated_and_read_only(self):
        from app import recommendation_experiment_integrity_report
        expected = {
            "status": "shadow_only_no_verified_exposure",
            "verified_randomized_served_exposure_count": 0,
            "ranking_score_adjustment": 0,
            "deployment_authorized": False,
        }
        with mock.patch("app.require_review_access") as access, \
             mock.patch.object(app_module.recommendation_evaluation_store,
                               "experiment_integrity_report",return_value=expected) as audit:
            result = recommendation_experiment_integrity_report(x_review_token="token")
        access.assert_called_once_with("token")
        audit.assert_called_once_with()
        self.assertEqual(result, expected)

    def test_recommendation_experiment_integrity_route_is_included_in_auth_audit(self):
        route = next(route for route in app.routes
                     if getattr(route,"path","") == "/api/recommendations/experiments/integrity")
        self.assertIn("x_review_token",route.endpoint.__annotations__)

    def test_recommendation_experiment_routes_are_included_in_auth_audit(self):
        protected = {
            "/api/recommendations/experiments",
            "/api/recommendations/experiments/{experiment_id}/shadow-assignment",
            "/api/recommendations/experiments/{experiment_id}/report",
        }
        found = {getattr(route,"path",""):route for route in app.routes
                 if getattr(route,"path","") in protected}
        self.assertEqual(set(found),protected)
        for route in found.values():
            self.assertIn("x_review_token",route.endpoint.__annotations__)



    def test_rendered_recommendation_exposure_routes_require_auth_and_report_evidence(self):
        from app import (record_recommendation_rendered_exposures,
            recommendation_rendered_exposure_report,RecommendationRenderedExposureBatch,
            RecommendationRenderedExposure)
        batch=RecommendationRenderedExposureBatch(run_id="run-1",exposures=[
            RecommendationRenderedExposure(event_id="b8d6f5e4-73b0-4f6d-91ab-2d5e5a1c0f11",
                trend_id="trend-1",visibility_ms=1200)])
        with mock.patch("app.require_review_access") as access, \
             mock.patch.object(app_module.recommendation_evaluation_store,
                "record_rendered_exposures",return_value={"recorded_count":1,"randomized_assignment":False}):
            result=record_recommendation_rendered_exposures(batch,x_review_token="token")
        self.assertEqual(result["recorded_count"],1)
        access.assert_called_once_with("token")
        with mock.patch("app.require_review_access"), \
             mock.patch.object(app_module.performance_analyzer,"analyze",return_value={"videos":[]}), \
             mock.patch.object(app_module.recommendation_evaluation_store,
                "rendered_exposure_report",return_value={"causal_effect_status":"not_estimable_nonrandomized"}):
            report=recommendation_rendered_exposure_report("run-1",x_review_token="token")
        self.assertEqual(report["causal_effect_status"],"not_estimable_nonrandomized")

    def test_rendered_recommendation_exposure_routes_are_included_in_auth_audit(self):
        protected={"/api/recommendations/exposures/rendered",
                   "/api/recommendations/exposures/{run_id}/report"}
        found={getattr(route,"path",""):route for route in app.routes
               if getattr(route,"path","") in protected}
        self.assertEqual(set(found),protected)
        for route in found.values():
            self.assertIn("x_review_token",route.endpoint.__annotations__)


if __name__ == "__main__":
    unittest.main()
