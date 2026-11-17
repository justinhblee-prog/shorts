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
        self.assertIn("EDITORIAL MATCH", html)
        self.assertIn("trendRecommendations", html)
        self.assertIn("성과가 충분히 검증되기 전까지 추천 점수는 자동 변경하지 않습니다", html)
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

    def test_dashboard_has_single_page_workspaces(self):
        html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        for section in ("id=\"studio\"","id=\"discovery\"","id=\"review\"","id=\"operations\""):
            self.assertIn(section, html)


    def test_scheduler_outbox_dashboard_exposes_readiness_counts_and_dead_letter_retry(self):
        frontend = ROOT / "frontend"
        app_js = (frontend / "app.js").read_text(encoding="utf-8")
        self.assertIn("outbox.pending_ready", app_js)
        self.assertIn("outbox.pending_retries", app_js)
        self.assertIn("counts.dead_letter", app_js)
        self.assertIn("data-schedule-outbox-retry", app_js)
        self.assertIn("encodeURIComponent(outboxId)", app_js)
        self.assertIn("/api/schedules/outbox/", app_js)
        self.assertIn("기존 실행 식별자는 유지됩니다", app_js)
        self.assertIn("격리된 예약 실행을 다시 대기열에 넣으시겠습니까?", app_js)

    def test_review_cards_disclose_recovered_provider_artifact_provenance(self):
        app_js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
        self.assertIn("recovered_from_provider_attempt", app_js)
        self.assertIn("recoveryFingerprint.sha256", app_js)
        self.assertIn("외부 AI 생성 결과 복구", app_js)
        self.assertIn("사람의 최종 검수 및 별도 승인 전에는 게시할 수 없습니다", app_js)

    def test_external_media_urls_require_https_without_embedded_credentials(self):
        app_js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
        self.assertIn("function safeExternalMediaUrl(value)", app_js)
        self.assertIn('url.protocol!=="https:"', app_js)
        self.assertIn("url.username||url.password", app_js)
        self.assertIn("safeExternalMediaUrl(audioArtifact?.artifact_url)", app_js)
        self.assertGreaterEqual(app_js.count("safeExternalMediaUrl(video?.artifact_url)"), 2)
        self.assertGreaterEqual(app_js.count('rel="noopener noreferrer"'), 2)
        self.assertNotIn("esc(video.artifact_url)", app_js)
        self.assertNotIn("esc(audioArtifact.artifact_url)", app_js)

    def test_integrity_report_is_visible_as_read_only_operator_diagnostic(self):
        frontend = ROOT / "frontend"
        app_js = (frontend / "app.js").read_text(encoding="utf-8")
        html = (frontend / "index.html").read_text(encoding="utf-8")
        css = (frontend / "styles.css").read_text(encoding="utf-8")
        self.assertIn('id="integritySummary"', html)
        self.assertIn('id="integrityList"', html)
        self.assertIn('id="loadIntegrity"', html)
        self.assertIn('id="integrityMore"', html)
        self.assertIn('/api/production/integrity-report?limit=50', app_js)
        self.assertIn('integrityNextCursor', app_js)
        self.assertIn('&cursor=', app_js)
        self.assertIn('integrityMore").style.display=report.has_more', app_js)
        self.assertIn('approval_or_upload_boundary', app_js)
        self.assertIn('ambiguous_external_outcome', app_js)
        self.assertIn('item.recommended_action', app_js)
        self.assertIn('진단 전용 · 자동 복구·재시도·승인·게시 없음', app_js)
        self.assertIn('.integrity-item', css)
        self.assertIn('loadIntegrityReport()', app_js)

    def test_cyber_magic_theme_is_loaded_after_base_styles(self):
        html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "frontend" / "cyber-magic.css").read_text(encoding="utf-8")
        self.assertIn('/assets/cyber-magic.css', html)
        self.assertLess(html.index('/assets/styles.css'), html.index('/assets/cyber-magic.css'))
        self.assertIn('Workspace navigation', html)
        self.assertIn('AI Content Studio', html)
        self.assertIn('Approvals & Publishing', html)
        self.assertIn('position:fixed', css)
        self.assertIn('prefers-reduced-motion', css)
