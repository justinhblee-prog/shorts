import sys
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recommendation_evaluation import RecommendationEvaluationStore, _spearman


class RecommendationEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = RecommendationEvaluationStore(
            str(Path(self.temp.name) / "evaluation.sqlite3")
        )

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def item(index, score):
        return {
            "trend": {
                "id": f"trend-{index}",
                "title": f"AI topic {index}",
                "region": "US",
            },
            "recommendation_score": score,
            "score_breakdown": {"freshness": score},
            "best_brand": {
                "brand": "future-leak",
                "brand_name": "Future Leak",
                "comparable_cohort_performance": {
                    "ranking_score_adjustment": 0,
                    "matched_cohort_count": 1,
                },
            },
        }

    def test_records_exposure_and_links_selected_production_job(self):
        self.store.record_run("US", [self.item(1, 82.5)],
                              "2026-11-01T00:00:00+00:00")
        linked = self.store.link_production(
            "trend-1", "future-leak", "job-1",
            "2026-11-01T01:00:00+00:00"
        )
        self.assertTrue(linked["linked"])
        self.assertFalse(self.store.link_production(
            "trend-1", "future-leak", "job-2"
        )["linked"])

    def test_holdout_is_chronological_and_reports_score_outcome_association(self):
        videos = []
        for index in range(10):
            timestamp = (datetime(2026, 11, 1, tzinfo=timezone.utc)
                         + timedelta(days=index)).isoformat()
            self.store.record_run("US", [self.item(index, 50 + index * 2)],
                                  timestamp)
            self.store.link_production(
                f"trend-{index}", "future-leak", f"job-{index}",
                timestamp
            )
            videos.append({
                "job_id": f"job-{index}",
                "measurement_status": "measured",
                "views_per_hour": 100 + index * 10,
            })
        result = self.store.evaluate({"videos": videos})
        self.assertEqual(result["status"], "holdout_available")
        self.assertEqual(result["selected_production_count"], 10)
        self.assertEqual(result["measured_outcome_count"], 10)
        self.assertEqual(result["pre_holdout_count"], 5)
        self.assertEqual(result["holdout_count"], 5)
        self.assertEqual(result["holdout_score_views_spearman"], 1.0)
        self.assertFalse(result["ranking_score_adjustment_enabled"])
        self.assertIn("selection bias", result["warning"])

    def test_insufficient_or_unmeasured_outcomes_never_claim_validation(self):
        self.store.record_run("US", [self.item(1, 80)],
                              "2026-11-01T00:00:00+00:00")
        self.store.link_production("trend-1", "future-leak", "job-1")
        result = self.store.evaluate({"videos": []})
        self.assertEqual(result["status"], "insufficient_data")
        self.assertEqual(result["selected_production_count"], 1)
        self.assertEqual(result["unmeasured_selected_count"], 1)
        self.assertFalse(result["ranking_score_adjustment_enabled"])

    def test_spearman_handles_ties_and_constant_values(self):
        self.assertEqual(_spearman([1, 2, 3], [10, 20, 30]), 1.0)
        self.assertIsNone(_spearman([1, 1, 1], [10, 20, 30]))


if __name__ == "__main__":
    unittest.main()
