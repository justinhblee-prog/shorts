import sys, unittest
from pathlib import Path
from datetime import datetime, timezone, timedelta
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from trend_recommendations import rank_trend_candidates


class TrendRecommendationTests(unittest.TestCase):
    def test_ranks_fresh_brand_relevant_trends_and_marks_missing_evidence(self):
        now = datetime(2026, 11, 15, 3, tzinfo=timezone.utc)
        brands = [{
            "slug": "future-leak", "name": "Future Leak", "active": True,
            "config": {"positioning": "AI technology and emerging technology",
                       "vertical": "ai_future_technology", "audience": "technology curious",
                       "regions": ["US"], "languages": ["en", "ko"]},
        }]
        trends = [
            {"id": "old", "title": "AI technology research", "region": "US",
             "published_at": (now - timedelta(days=20)).isoformat()},
            {"id": "fresh", "title": "New AI technology research", "region": "US",
             "published_at": (now - timedelta(hours=2)).isoformat()},
            {"id": "wrong-region", "title": "AI technology launch", "region": "JP",
             "published_at": now.isoformat()},
        ]
        ranked = rank_trend_candidates(trends, brands, now=now)
        self.assertEqual([x["trend"]["id"] for x in ranked], ["fresh", "old"])
        self.assertEqual(ranked[0]["best_brand"]["brand"], "future-leak")
        self.assertEqual(ranked[0]["score_type"], "editorial_signal_not_profitability")
        self.assertIn("revenue_and_cost_not_estimated", ranked[0]["evidence_gaps"])

    def test_no_brand_match_is_not_invented(self):
        result = rank_trend_candidates(
            [{"id": "x", "title": "Local gardening", "region": "US"}],
            [{"slug": "future-leak", "name": "Future Leak", "active": True,
              "config": {"positioning": "AI technology", "regions": ["US"]}}],
            now=datetime(2026, 11, 15, tzinfo=timezone.utc))
        self.assertIsNone(result[0]["best_brand"])
        self.assertEqual(result[0]["recommendation_score"], 0)


if __name__ == "__main__":
    unittest.main()
