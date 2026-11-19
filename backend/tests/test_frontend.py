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

    def test_analytics_history_platform_summary_uses_latest_per_video_snapshots(self):
        app_js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("platformLatest={youtube:[],tiktok:[]}", app_js)
        self.assertIn("최신 조회수 요약", app_js)
        self.assertIn("영상별 최신 스냅샷 기준", app_js)
        self.assertIn("플랫폼별 조회수 정의·수집 범위가 다르므로", app_js)
        self.assertIn(".analytics-platform-grid", css)
        self.assertIn(".analytics-platform-card", css)

    def test_analytics_history_renders_real_snapshot_trend_chart_safely(self):
        frontend = ROOT / "frontend"
        app_js = (frontend / "app.js").read_text(encoding="utf-8")
        html = (frontend / "index.html").read_text(encoding="utf-8")
        css = (frontend / "styles.css").read_text(encoding="utf-8")
        self.assertIn("analytics-trend-chart", app_js)
        self.assertIn("Date.parse(item.collected_at)", app_js)
        self.assertIn("Number.isFinite(point.value)", app_js)
        self.assertIn("group.points.length>=2", app_js)
        self.assertIn('raw===null||raw===undefined||raw===""', app_js)
        self.assertIn("chartMetricValue(item)", app_js)
        self.assertIn('item.platform==="youtube"?"views":"view_count"', app_js)
        self.assertIn("chartMetricDeltas", app_js)
        self.assertIn("Number(b.id||0)-Number(a.id||0)", app_js)
        self.assertIn("Number(a.item.id||0)-Number(b.item.id||0)", app_js)
        self.assertIn("medianInterval*3", app_js)
        self.assertIn("Math.floor((intervals.length-1)/2)", app_js)
        self.assertIn("48*60*60*1000", app_js)
        self.assertIn("데이터가 없으며 보간하지 않습니다", app_js)
        self.assertIn("수집 기간", app_js)
        self.assertIn("analyticsHistoryMetric", html)
        self.assertIn('value="like_count"', html)
        self.assertIn('value="comment_count"', html)
        self.assertIn('value="share_count"', html)
        self.assertIn('value="engaged_views"', html)
        self.assertIn('value="engaged_view_share"', html)
        self.assertIn('value="average_view_duration"', html)
        self.assertIn('engaged_views:"참여 조회수"', app_js)
        self.assertIn('item.engaged_views,item.engaged_view_share', app_js)
        self.assertIn('chartMetric==="engaged_view_share"?value*100:value', app_js)
        self.assertIn('Number(item.engaged_view_share)*100', app_js)
        self.assertIn('item.platform==="youtube"?retentionSummary(item.retention_curve):null', app_js)
        self.assertIn('retentionSparkline(item.retention_curve)', app_js)
        self.assertIn('retentionStatusLabels[item.retention_status]', app_js)
        self.assertIn('유지율 수집 상태', app_js)
        self.assertIn('<th>시청자 유지율</th>', app_js)
        self.assertIn('(Number(item.engaged_view_share)*100).toLocaleString()+"%"', app_js)
        self.assertIn("metricLabels[chartMetric]", app_js)
        self.assertIn('estimated_minutes_watched', app_js)
        self.assertIn('average_view_duration', app_js)
        self.assertIn('$("analyticsHistoryMetric").addEventListener("change"', app_js)
        self.assertIn('dataset.loaded="true"', app_js)
        self.assertIn('id="exportAnalyticsHistory"', html)
        self.assertIn('exportButton.disabled=rows.length===0', app_js)
        self.assertIn("표 최대 200개 표시 · CSV 전체 내보내기(페이지 단위)", app_js)
        self.assertIn("const exportRows=[]", app_js)
        self.assertIn("while(true)", app_js)
        self.assertIn("pageParams.before_collected_at=cursor.collected_at", app_js)
        self.assertIn("let exportAsOf=null", app_js)
        self.assertIn("pageParams.as_of=exportAsOf", app_js)
        self.assertIn("if(!exportAsOf)", app_js)
        self.assertIn("cursor={collected_at:lastItem.collected_at,id:Number(lastItem.id)}", app_js)
        self.assertIn("분석 이력 페이지 커서가 올바르지 않습니다.", app_js)
        self.assertIn("exportRows.map(item=>[", app_js)
        self.assertIn('if($("exportAnalyticsHistory"))$("exportAnalyticsHistory").disabled=true', app_js)
        self.assertIn('summaryPlatforms=platform==="all"?["youtube","tiktok"]:[platform]', app_js)
        self.assertIn('new Blob(["\\uFEFF",csv]', app_js)
        self.assertIn('cell.replace(/"/g,\'""\')', app_js)
        self.assertIn('if(/^[\\u0000-\\u0020]*[=+\\-@]/.test(cell))', app_js)
        self.assertIn("Number.isFinite(numeric)?numeric.toLocaleString():\"—\"", app_js)
        self.assertIn("Number.isFinite(numericValue)&&numericValue>=0", app_js)
        self.assertIn("선택 지표가 없는 영상은 제외됩니다", app_js)
        self.assertIn(".analytics-trend-chart", css)
        self.assertIn(".analytics-history-controls{display:grid;grid-template-columns:1fr 1fr 1.5fr auto auto", css)
        self.assertIn('id="analyticsHistory"', html)
        self.assertIn('id="analyticsHistoryStatus" class="analytics-history-status" role="status" aria-live="polite"', html)
        self.assertIn("조회 중 · 선택한 기간의 YouTube · TikTok 성과 이력을 불러옵니다.", app_js)
        self.assertIn("CSV 준비 중 · 플랫폼별 전체 이력을 페이지 단위로 조회합니다.", app_js)
        self.assertIn("CSV 다운로드 요청 완료", app_js)
        self.assertIn("CSV 내보내기 실패 · ", app_js)


    def test_dashboard_has_keyboard_skip_link_and_visible_focus_styles(self):
        frontend = ROOT / "frontend"
        html = (frontend / "index.html").read_text(encoding="utf-8")
        css = (frontend / "styles.css").read_text(encoding="utf-8")
        self.assertIn('class="skip-link" href="#home"', html)
        self.assertIn("본문으로 건너뛰기", html)
        self.assertIn(".skip-link:focus", css)
        self.assertIn(":focus-visible", css)


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
        self.assertIn('aria-label="작업공간 메뉴"', html)
        self.assertIn('AI Content Studio', html)
        self.assertIn('Approvals & Publishing', html)
        self.assertIn('position:fixed', css)
        self.assertIn('prefers-reduced-motion', css)

    def test_cyber_magic_calendar_uses_real_schedule_next_run_data(self):
        frontend = ROOT / "frontend"
        html = (frontend / "index.html").read_text(encoding="utf-8")
        app_js = (frontend / "app.js").read_text(encoding="utf-8")
        css = (frontend / "cyber-magic.css").read_text(encoding="utf-8")
        self.assertIn('id="cyberCalendarGrid"', html)
        self.assertIn('new Date(item.next_run_at)', app_js)
        self.assertIn('item.payload?.brand', app_js)
        self.assertIn('SCHEDULED PRODUCTION', html)
        self.assertIn('.cyber-calendar-grid', css)
        self.assertIn('실제 게시 예약과는 구분됩니다', html)

    def test_cyber_magic_dashboard_approval_queue_uses_review_api_data(self):
        frontend = ROOT / "frontend"
        html = (frontend / "index.html").read_text(encoding="utf-8")
        app_js = (frontend / "app.js").read_text(encoding="utf-8")
        css = (frontend / "cyber-magic.css").read_text(encoding="utf-8")
        self.assertIn('id="cyberApprovalList"', html)
        self.assertIn('dashboardApproval.innerHTML=items.length?', app_js)
        self.assertIn('items.slice(0,4)', app_js)
        self.assertIn('href="#review"', app_js)
        self.assertIn('.cyber-approval-list', css)



    def test_workspace_navigation_has_localized_tooltips_and_main_landmark_label(self):
        html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        for title in ("대시보드", "AI 콘텐츠 제작", "콘텐츠 기획 및 시장 분석", "검수 및 게시", "분석 및 운영"):
            self.assertIn(f'title="{title}"', html)
        self.assertIn('<main id="home" aria-label="주요 콘텐츠" tabindex="-1">', html)


    def test_dashboard_connection_status_and_skip_target_are_accessible(self):
        html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="connection" class="status-pill" role="status" aria-live="polite"', html)
        self.assertIn('<main id="home" aria-label="주요 콘텐츠" tabindex="-1">', html)
        self.assertIn('href="#home">본문으로 건너뛰기</a>', html)

    def test_mobile_workspace_navigation_preserves_minimum_touch_targets(self):
        css = (ROOT / "frontend" / "cyber-magic.css").read_text(encoding="utf-8")
        self.assertIn("@media(max-width:700px)", css)
        self.assertIn(".main-nav a{min-width:48px;min-height:48px}", css)
        self.assertIn(".top-actions .button{min-width:44px;min-height:44px}", css)

    def test_cyber_magic_workspace_navigation_is_accessible_and_tracks_active_section(self):
        frontend = ROOT / "frontend"
        html = (frontend / "index.html").read_text(encoding="utf-8")
        app_js = (frontend / "app.js").read_text(encoding="utf-8")
        css = (frontend / "cyber-magic.css").read_text(encoding="utf-8")
        for label in ("Dashboard", "AI Content Studio", "Content Planner and Intelligence", "Approvals and Publishing", "Analytics and Operations"):
            self.assertIn(f'aria-label="{label}"', html)
        self.assertIn("IntersectionObserver", app_js)
        self.assertIn('setAttribute("aria-current","page")', app_js)
        self.assertIn('removeAttribute("aria-current")', app_js)
        self.assertIn(".main-nav a[aria-current=\"page\"]", css)
        self.assertIn(".main-nav a:nth-child(5):before", css)
        self.assertIn("prefers-reduced-motion:reduce", css)


class AnalyticsFreshnessPresentationTests(unittest.TestCase):
    def test_analytics_status_displays_latest_snapshot_and_counts_stale_data(self):
        app_js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
        self.assertIn('coverage.stale_or_missing??(Number(coverage.without_snapshot||0)+Number(coverage.stale_snapshots||0))', app_js)
        self.assertIn('최근 스냅샷', app_js)
        self.assertIn('item.latest_snapshot_at', app_js)
