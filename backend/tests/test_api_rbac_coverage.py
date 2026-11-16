import re
import unittest
from pathlib import Path


class ApiRbacCoverageTests(unittest.TestCase):
    PUBLIC_API_ROUTES = {
        "/api/brands",
        "/api/brands/{slug}",
        "/api/health",
        "/api/ready",
        "/api/tiktok/oauth/callback",
        "/api/youtube/oauth/callback",
    }

    def test_every_non_public_api_route_has_an_explicit_role_guard(self):
        app_path = Path(__file__).resolve().parents[1] / "app.py"
        lines = app_path.read_text(encoding="utf-8").splitlines()
        found = []
        for index, line in enumerate(lines):
            match = re.match(r'\s*@app\.(?:get|post|put|patch|delete)\("([^"]+)"', line)
            if not match or not match.group(1).startswith("/api/"):
                continue
            path = match.group(1)
            end = next((i for i in range(index + 1, len(lines))
                        if lines[i].startswith("@app.")), len(lines))
            block = "\n".join(lines[index:end])
            found.append(path)
            if path not in self.PUBLIC_API_ROUTES:
                self.assertIn(
                    "require_review_permission(x_review_token,", block,
                    f"{path} must declare an explicit RBAC permission guard",
                )
        self.assertGreaterEqual(len(found), 60)
        self.assertEqual(
            {path for path in found if path in self.PUBLIC_API_ROUTES},
            self.PUBLIC_API_ROUTES,
        )


if __name__ == "__main__":
    unittest.main()
