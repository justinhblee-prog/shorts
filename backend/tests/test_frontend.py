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
    def test_dashboard_has_single_page_workspaces(self):
        html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        for section in ("id=\"studio\"","id=\"discovery\"","id=\"review\"","id=\"operations\""):
            self.assertIn(section, html)
if __name__ == "__main__":
    unittest.main()
