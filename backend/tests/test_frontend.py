import unittest
from pathlib import Path
from app import app

ROOT = Path(__file__).resolve().parents[2]
class FrontendPortalTests(unittest.TestCase):
    def test_dashboard_assets_are_packaged(self):
        frontend = ROOT / "frontend"
        self.assertTrue((frontend / "index.html").is_file())
        self.assertTrue((frontend / "app.js").is_file())
        self.assertTrue((frontend / "styles.css").is_file())
    def test_fastapi_serves_dashboard_and_assets(self):
        paths = {getattr(route, "path", None) for route in app.routes}
        self.assertIn("/", paths)
        self.assertIn("/assets", paths)

    def test_docker_preserves_backend_frontend_relative_layout(self):
        dockerfile = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("COPY backend/ ./backend/", dockerfile)
        self.assertIn("COPY frontend/ ./frontend/", dockerfile)
        self.assertIn("WORKDIR /app/backend", dockerfile)
    def test_late_upload_resolution_controls_are_wired(self):
        frontend = ROOT / "frontend"
        app_js = (frontend / "app.js").read_text(encoding="utf-8")
        self.assertIn("data-resolve-late-id", app_js)
        self.assertIn("/resolve-late-result", app_js)
        self.assertIn("lateIdSummary", app_js)
        self.assertIn("existingIdSummary", app_js)
    def test_review_workspace_shows_frozen_brand_editorial_guidance(self):
        frontend = ROOT / "frontend"
        app_js = (frontend / "app.js").read_text(encoding="utf-8")
        self.assertIn("item.brand_profile", app_js)
        self.assertIn("profile.review_rules", app_js)
        self.assertIn("review-guidance", app_js)
        self.assertIn("risk-level", app_js)
        self.assertIn("생성 대본 검수", app_js)
        self.assertIn("내레이션 미리 듣기", app_js)
        self.assertIn("audio controls", app_js)
        self.assertIn("esc(scriptText)", app_js)
        self.assertIn("policy_preflight", app_js)
        self.assertIn("policySummary", app_js)
        self.assertIn("영상 전체 검사나 플랫폼 승인", app_js)

    def test_trend_signals_can_be_converted_into_production_drafts(self):
        frontend = ROOT / "frontend"
        app_js = (frontend / "app.js").read_text(encoding="utf-8")
        self.assertIn("/api/trends?limit=12", app_js)
        self.assertIn("data-trend-draft", app_js)
        self.assertIn("/draft-production", app_js)
        self.assertIn("제작 기획 등록 완료", app_js)
        self.assertIn("data-trend-brand", app_js)


    def test_trend_recommendation_ranking_is_rendered_and_can_create_drafts(self):
        frontend = ROOT / "frontend"
        app_js = (frontend / "app.js").read_text(encoding="utf-8")
        html = (frontend / "index.html").read_text(encoding="utf-8")
        self.assertIn("/api/trends/recommendations", app_js)
        self.assertIn("data-recommend-draft", app_js)
        self.assertIn("loadTrendRecommendations()", app_js)
        self.assertIn("data-recommend-brand", app_js)
        self.assertIn("evaluation_candidate_id", app_js)
        self.assertIn("recommendation_candidate_id", app_js)
        self.assertIn("data-candidate-id", app_js)
        self.assertIn("EDITORIAL MATCH", html)
        self.assertIn("trendRecommendations", html)
        self.assertIn("수익성이나 조회수 예측 점수가 아닙니다", html)
        self.assertIn("competitor_context", app_js)
        self.assertIn("median_matched_views", app_js)
        self.assertIn("경쟁 영상 표본 미수집", app_js)

    def test_competitor_evidence_can_adjust_opportunity_priority(self):
        app_js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
        self.assertIn("data-inspect-channel", app_js)
        self.assertIn("data-competitor-select", app_js)
        self.assertIn("competitor_channel_ids", app_js)
        self.assertIn("competitive_context", app_js)
        self.assertIn("최근 영상 분석", app_js)

    def test_saved_opportunity_ranking_is_loaded_and_rendered(self):
        frontend = ROOT / "frontend"
        app_js = (frontend / "app.js").read_text(encoding="utf-8")
        html = (frontend / "index.html").read_text(encoding="utf-8")
        self.assertIn("/api/opportunities?limit=20", app_js)
        self.assertIn("opportunityList", app_js)
        self.assertIn("loadOpportunities()", app_js)
        self.assertIn('id="opportunityList"', html)
        self.assertIn("경쟁 조정", app_js)

    def test_approved_workspace_exposes_private_tiktok_publish_and_status_controls(self):
        app_js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
        self.assertIn("/api/tiktok/creator-info", app_js)
        self.assertIn("/api/tiktok/publish/", app_js)
        self.assertIn("data-tiktok-publish-id", app_js)
        self.assertIn("data-tiktok-refresh-id", app_js)
        self.assertIn("explicit_consent:true", app_js)
        self.assertIn("brand_content_toggle", app_js)
        self.assertIn("brand_organic_toggle", app_js)
        self.assertIn("commercial_relationship_disclosed", app_js)
        self.assertIn("SELF_ONLY", app_js)

    def test_recommendation_workspace_records_human_skip_feedback(self):
        app_js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
        self.assertIn("data-recommend-skip", app_js)
        self.assertIn("/api/recommendations/feedback/skip", app_js)
        self.assertIn("이번 후보 제외", app_js)
        self.assertIn("reviewer_id:reviewer||\"operator\"", app_js)
        self.assertIn("recommendation_candidate_id:candidateId", app_js)
        self.assertIn("selectedOption?.dataset.candidateId", app_js)

    def test_tiktok_oauth_connection_is_available_from_integration_readiness(self):
        frontend = ROOT / "frontend"
        app_js = (frontend / "app.js").read_text(encoding="utf-8")
        html = (frontend / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="connectTikTok"', html)
        self.assertIn('id="disconnectTikTok"', html)
        self.assertIn("/api/tiktok/oauth/disconnect", app_js)
        self.assertIn("/api/tiktok/oauth/start", app_js)
        self.assertIn("window.location.assign", app_js)
        self.assertIn('get("tiktok_oauth")', app_js)
        self.assertIn('tiktokOAuthResult==="connected"', app_js)
        self.assertIn("/api/tiktok/oauth/status", app_js)

    def test_approved_workspace_exposes_joined_lifecycle_trace(self):
        app_js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
        self.assertIn("data-lifecycle-id", app_js)
        self.assertIn("/api/lifecycle/jobs/", app_js)
        self.assertIn("renderLifecycleTrace", app_js)
        self.assertIn("data.timeline", app_js)
        self.assertIn("통합 작업 이력", app_js)
        self.assertIn("최근 큐 이벤트", app_js)

    def test_lifecycle_trace_renders_cross_platform_timeline(self):
        app_js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
        self.assertIn("data.timeline", app_js)
        self.assertIn("stageLabels", app_js)
        self.assertIn("human_review", app_js)
        self.assertIn("최대 20개", app_js)
        self.assertIn("attempt_id", app_js)
        self.assertIn("reference_id", app_js)

    def test_dashboard_has_single_page_workspaces(self):
        html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        for section in ("id=\"studio\"","id=\"discovery\"","id=\"review\"","id=\"operations\""):
            self.assertIn(section, html)
if __name__ == "__main__":
    unittest.main()
