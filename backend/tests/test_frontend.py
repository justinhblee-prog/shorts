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

    def test_trend_signals_can_be_converted_into_production_drafts(self):
        frontend = ROOT / "frontend"
        app_js = (frontend / "app.js").read_text(encoding="utf-8")
        self.assertIn("/api/trends?limit=12", app_js)
        self.assertIn("data-trend-draft", app_js)
        self.assertIn("/draft-production", app_js)
        self.assertIn("제작 기획 등록 완료", app_js)
        self.assertIn("data-trend-brand", app_js)

    def test_dashboard_has_single_page_workspaces(self):
        html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        for section in ("id=\"studio\"","id=\"discovery\"","id=\"review\"","id=\"operations\""):
            self.assertIn(section, html)
if __name__ == "__main__":
    unittest.main()
