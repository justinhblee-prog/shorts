import os
import unittest
from fastapi import Header
from app import app, require_review_access

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

    def test_review_token_fails_closed(self):
        previous = os.environ.get("NEXUS_REVIEW_TOKEN")
        os.environ["NEXUS_REVIEW_TOKEN"] = "unit-test-secret"
        try:
            with self.assertRaises(Exception):
                require_review_access(None)
            with self.assertRaises(Exception):
                require_review_access("wrong-secret")
            self.assertIsNone(require_review_access("unit-test-secret"))
        finally:
            if previous is None:
                os.environ.pop("NEXUS_REVIEW_TOKEN", None)
            else:
                os.environ["NEXUS_REVIEW_TOKEN"] = previous

if __name__ == "__main__":
    unittest.main()
