import sys
import unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as app_module
from app import trend_recommendations


class TrendRecommendationApiTests(unittest.TestCase):
    def test_endpoint_requires_review_token_and_returns_explained_editorial_rank(self):
        route = next(r for r in app_module.app.routes
                     if getattr(r, "path", None) == "/api/trends/recommendations")
        self.assertIn("x_review_token", route.endpoint.__annotations__)
        trend = {"id": "t1", "title": "AI technology research", "region": "US",
                 "published_at": "2026-11-15T00:00:00+00:00"}
        brand = {"slug": "future-leak", "name": "Future Leak", "active": True,
                 "config": {"positioning": "AI technology", "regions": ["US"],
                            "languages": ["en"]}}
        with (mock.patch("app.require_review_access"),
              mock.patch("app.trend_store.list", return_value=[trend]),
              mock.patch("app.brand_store.list", return_value=[brand])):
            result = trend_recommendations(region="US", limit=10, x_review_token="valid")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["best_brand"]["brand"], "future-leak")
        self.assertIn("not a profitability forecast", result["warning"])


if __name__ == "__main__":
    unittest.main()
