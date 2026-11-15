import sys, unittest
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock
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
        self.assertIn("competitor_video_sample_unavailable", ranked[0]["evidence_gaps"])

    def test_no_brand_match_is_not_invented(self):
        result = rank_trend_candidates(
            [{"id": "x", "title": "Local gardening", "region": "US"}],
            [{"slug": "future-leak", "name": "Future Leak", "active": True,
              "config": {"positioning": "AI technology", "regions": ["US"]}}],
            now=datetime(2026, 11, 15, tzinfo=timezone.utc))
        self.assertIsNone(result[0]["best_brand"])
        self.assertEqual(result[0]["recommendation_score"], 0)

    def test_competitor_evidence_is_region_scoped_and_does_not_change_editorial_score(self):
        store = Mock()
        store.list_channels.return_value = [
            *[{"channel_id": f"jp-channel-{index}", "country": "JP"} for index in range(12)],
            {"channel_id": "us-channel", "country": "US"},
        ]
        store.list_videos.side_effect = lambda channel_id, limit: [
            {"channel_id": channel_id, "title": "AI technology explained",
             "view_count": 1200, "published_at": "2026-11-14T00:00:00+00:00"}
        ]
        trend = {"id": "us-ai", "title": "AI technology explained", "region": "US",
                 "published_at": "2026-11-15T00:00:00+00:00"}
        brand = {"slug": "future-leak", "name": "Future Leak", "active": True,
                 "config": {"positioning": "AI technology", "regions": ["US"]}}
        result = rank_trend_candidates(
            [trend], [brand], competitor_store=store,
            now=datetime(2026, 11, 15, tzinfo=timezone.utc))[0]
        context = result["competitor_context"]
        self.assertEqual(context["selected_channels"], 1)
        self.assertEqual(context["observed_videos"], 1)
        self.assertEqual(context["topic_matched_videos"], 1)
        self.assertEqual(context["median_matched_views"], 1200)
        self.assertEqual(result["recommendation_score"], result["freshness_score"] +
                         result["best_brand"]["fit_score"])
        self.assertNotIn("competitor_video_sample_unavailable", result["evidence_gaps"])
        store.list_channels.assert_called_once_with(limit=200)
        store.list_videos.assert_called_once_with("us-channel", limit=30)


if __name__ == "__main__":
    unittest.main()
