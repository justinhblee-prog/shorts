import sys
import unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as app_module
from app import trend_recommendations, capture_trend_recommendations, draft_production_from_trend, TrendProductionDraft


class TrendRecommendationApiTests(unittest.TestCase):

    def test_read_only_recommendation_get_does_not_record_an_exposure(self):
        with (mock.patch("app.require_review_access"),
              mock.patch("app.trend_store.list", return_value=[]),
              mock.patch("app.brand_store.list", return_value=[]),
              mock.patch("app.performance_analyzer.analyze", return_value={"brands": [], "videos": [], "cohorts": []}),
              mock.patch("app.recommendation_evaluation_store.record_run") as record_run):
            result = trend_recommendations(
                region="US", limit=10, x_review_token="valid"
            )
        self.assertEqual(result["count"], 0)
        self.assertNotIn("evaluation_run_id", result)
        record_run.assert_not_called()

    def test_holdout_evaluation_endpoint_is_review_protected_and_delegates_report(self):
        route = next(r for r in app_module.app.routes
                     if getattr(r, "path", None) == "/api/recommendations/evaluation")
        self.assertIn("x_review_token", route.endpoint.__annotations__)
        expected = {"status": "insufficient_data", "ranking_score_adjustment_enabled": False}
        with (mock.patch("app.require_review_access"),
              mock.patch("app.recommendation_evaluation_store.evaluate",
                         return_value=expected) as evaluate,
              mock.patch("app.performance_analyzer.analyze", return_value={"videos": []})):
            result = app_module.recommendation_evaluation(x_review_token="valid")
        self.assertEqual(result, expected)
        evaluate.assert_called_once_with({"videos": []})


    def test_recommendation_run_id_is_required_for_auditable_production_link(self):
        trend = {
            "id": "trend-a", "title": "AI research", "region": "US",
            "source": "test", "url": "https://example.invalid", "summary": "summary",
        }
        brand = {
            "slug": "future-leak", "name": "Future Leak", "active": True,
            "config": {"regions": ["US"], "languages": ["en"]},
        }
        body = TrendProductionDraft(
            brand="future-leak", language="en", recommendation_run_id="run-exact"
        )
        submitted = {"job": {"id": "job-exact"}}
        with (
            mock.patch("app.require_review_access"),
            mock.patch("app.trend_store.get", return_value=trend),
            mock.patch("app.brand_store.list", return_value=[brand]),
            mock.patch("app.submit_production", return_value=submitted),
            mock.patch("app.recommendation_evaluation_store.link_production") as link,
        ):
            result = draft_production_from_trend(
                "trend-a", body, x_review_token="valid"
            )
        self.assertEqual(result, submitted)
        link.assert_called_once_with(
            "trend-a", "future-leak", "job-exact", run_id="run-exact"
        )

    def test_endpoint_requires_review_token_and_returns_explained_editorial_rank(self):
        route = next(r for r in app_module.app.routes
                     if getattr(r, "path", None) == "/api/trends/recommendations/snapshot")
        self.assertIn("POST", route.methods)
        self.assertIn("x_review_token", route.endpoint.__annotations__)
        trend = {"id": "t1", "title": "AI technology research", "region": "US",
                 "published_at": "2026-11-15T00:00:00+00:00"}
        brand = {"slug": "future-leak", "name": "Future Leak", "active": True,
                 "config": {"positioning": "AI technology", "regions": ["US"],
                            "languages": ["en"]}}
        performance = {
            "brands": [{
                "brand": "Future Leak", "measured_videos": 4, "rate_sample_count": 3,
                "median_views_per_hour": 90.0, "interaction_rate_sample_count": 2,
                "median_interactions_per_1000_view_delta": 14.0
            }],
            "videos": [{
                "brand": "Future Leak", "region": "US", "topic": "AI technology research",
                "measurement_status": "measured", "views_per_hour": 90.0,
                "interactions_per_1000_view_delta": 14.0
            }],
            "cohorts": [{
                "brand": "Future Leak", "region": "US",
                "publication_age_bucket": "under_24h", "duration_bucket": "20_40s",
                "format": "vertical_short", "topic_signature": "ai research technology",
                "sample_count": 3, "median_views_per_hour": 90.0,
                "interaction_rate_sample_count": 2,
                "median_interactions_per_1000_view_delta": 14.0,
                "evidence_status": "observed",
            }]
        }
        with (mock.patch("app.require_review_access"),
              mock.patch("app.trend_store.list", return_value=[trend]),
              mock.patch("app.brand_store.list", return_value=[brand]),
              mock.patch("app.performance_analyzer.analyze", return_value=performance),
              mock.patch("app.recommendation_evaluation_store.record_run",
                         return_value={"run_id": "run-123", "recorded_candidates": 1}) as record_run):
            result = capture_trend_recommendations(
                region="US", limit=10, x_review_token="valid"
            )
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["evaluation_run_id"], "run-123")
        self.assertEqual(result["evaluation_candidates_recorded"], 1)
        record_run.assert_called_once_with("US", result["items"])
        self.assertEqual(result["items"][0]["best_brand"]["brand"], "future-leak")
        historical = result["items"][0]["best_brand"]["historical_performance"]
        self.assertEqual(historical["median_views_per_hour"], 90.0)
        self.assertEqual(historical["ranking_score_adjustment"], 0)
        topic_history = result["items"][0]["best_brand"]["topic_performance"]
        self.assertEqual(topic_history["matched_video_count"], 1)
        self.assertEqual(topic_history["median_views_per_hour"], 90.0)
        cohort_context = result["items"][0]["best_brand"]["comparable_cohort_performance"]
        self.assertEqual(cohort_context["matched_cohort_count"], 1)
        self.assertEqual(cohort_context["cohorts"][0]["sample_count"], 3)
        self.assertEqual(cohort_context["ranking_score_adjustment"], 0)
        self.assertIn("held-out validation", result["warning"])


if __name__ == "__main__":
    unittest.main()
