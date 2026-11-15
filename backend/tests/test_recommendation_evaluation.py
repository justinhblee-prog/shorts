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
    def item(index=1, score=80):
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

    def test_record_run_persists_all_brand_candidates_for_selection(self):
        item = self.item()
        item["brand_candidates"] = [
            {"brand": "alpha", "brand_name": "Alpha", "fit_score": 38},
            {"brand": "beta", "brand_name": "Beta", "fit_score": 34},
        ]
        result = self.store.record_run("US", [item])
        self.assertEqual(result["recorded_candidates"], 2)
        linked = self.store.link_production("trend-1", "beta", "job-beta")
        self.assertTrue(linked["linked"])
        with self.store.db() as connection:
            row = connection.execute(
                "SELECT selected_job_id,decision FROM recommendation_candidates WHERE brand_slug='beta'"
            ).fetchone()
        self.assertEqual(row["selected_job_id"], "job-beta")
        self.assertEqual(row["decision"], "selected")

    def test_skip_feedback_is_audited_and_included_in_human_selection_summary(self):
        self.store.record_run("US", [self.item()])
        result = self.store.record_skip(
            "trend-1", "alpha", "reviewer-1", "Topic is already overused"
        )
        self.assertTrue(result["recorded"])
        evaluation = self.store.evaluate()
        summary = evaluation["feedback_summary"]
        self.assertEqual(summary["skipped_count"], 1)
        self.assertEqual(summary["selected_count"], 0)
        self.assertEqual(summary["selection_rate"], 0.0)
        self.assertIn("not a platform performance metric", summary["interpretation"])

    def test_later_selection_supersedes_skip_but_preserves_feedback_event_history(self):
        self.store.record_run("US", [self.item()])
        self.store.record_skip("trend-1", "alpha", "reviewer-1", "Not suitable today")
        linked = self.store.link_production("trend-1", "alpha", "job-after-reconsideration")
        self.assertTrue(linked["linked"])
        evaluation = self.store.evaluate()
        self.assertEqual(evaluation["feedback_summary"]["selected_count"], 1)
        self.assertEqual(evaluation["feedback_summary"]["skipped_count"], 0)
        with self.store.db() as connection:
            events = connection.execute(
                "SELECT decision FROM recommendation_feedback_events WHERE candidate_id=? ORDER BY rowid",
                (linked["candidate_id"],),
            ).fetchall()
        self.assertEqual([row["decision"] for row in events], ["skipped", "selected"])

    def test_identical_api_result_is_deduplicated_within_one_minute(self):
        first = self.store.record_run(
            "US", [self.item(1, 82.5)], "2026-11-01T00:00:00+00:00"
        )
        repeated = self.store.record_run(
            "US", [self.item(1, 82.5)], "2026-11-01T00:00:45+00:00"
        )
        later = self.store.record_run(
            "US", [self.item(1, 82.5)], "2026-11-01T00:02:00+00:00"
        )
        self.assertEqual(first["run_id"], repeated["run_id"])
        self.assertTrue(repeated["deduplicated"])
        self.assertNotEqual(first["run_id"], later["run_id"])
        self.assertFalse(later["deduplicated"])

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

    def test_within_run_holdout_compares_only_candidates_from_same_exposure(self):
        videos = []
        for run_index in range(5):
            timestamp = (
                datetime(2026, 11, 1, tzinfo=timezone.utc)
                + timedelta(days=run_index)
            ).isoformat()
            items = [
                self.item(run_index * 3 + 0, 90),
                self.item(run_index * 3 + 1, 80),
                self.item(run_index * 3 + 2, 70),
            ]
            self.store.record_run("US", items, timestamp)
            for candidate_index in range(3):
                trend_id = f"trend-{run_index * 3 + candidate_index}"
                job_id = f"within-job-{run_index}-{candidate_index}"
                self.store.link_production(
                    trend_id, "future-leak", job_id, timestamp
                )
                videos.append({
                    "job_id": job_id,
                    "measurement_status": "measured",
                    "views_per_hour": [300, 200, 100][candidate_index],
                    "brand": "Future Leak", "region": "US",
                    "publication_age_bucket": "under_24h",
                    "duration_bucket": "15_30s", "format": "vertical_short",
                })
        result = self.store.evaluate({"videos": videos})
        within = result["within_run_validation"]
        self.assertEqual(within["status"], "holdout_available")
        self.assertEqual(within["eligible_run_count"], 5)
        self.assertEqual(within["pre_holdout_run_count"], 3)
        self.assertEqual(within["holdout_run_count"], 2)
        self.assertEqual(within["holdout_median_score_views_spearman"], 1.0)
        self.assertEqual(within["holdout_median_rank_views_spearman"], 1.0)
        self.assertEqual(within["holdout_positive_score_association_share"], 1.0)
        self.assertFalse(within["score_adjustment_enabled"])

    def test_within_run_validation_rejects_runs_with_fewer_than_three_outcomes(self):
        videos = []
        for run_index in range(5):
            timestamp = (
                datetime(2026, 11, 1, tzinfo=timezone.utc)
                + timedelta(days=run_index)
            ).isoformat()
            items = [
                self.item(run_index * 2 + 0, 90),
                self.item(run_index * 2 + 1, 70),
            ]
            self.store.record_run("US", items, timestamp)
            for candidate_index in range(2):
                job_id = f"two-job-{run_index}-{candidate_index}"
                self.store.link_production(
                    f"trend-{run_index * 2 + candidate_index}",
                    "future-leak", job_id, timestamp,
                )
                videos.append({
                    "job_id": job_id, "measurement_status": "measured",
                    "views_per_hour": [200, 100][candidate_index],
                    "brand": "Future Leak", "region": "US",
                    "publication_age_bucket": "under_24h",
                    "duration_bucket": "15_30s", "format": "vertical_short",
                })
        result = self.store.evaluate({"videos": videos})
        self.assertEqual(result["status"], "holdout_available")
        self.assertEqual(result["within_run_validation"]["status"],
                         "insufficient_run_coverage")
        self.assertEqual(result["within_run_validation"]["eligible_run_count"], 0)
        self.assertFalse(result["ranking_score_adjustment_enabled"])

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
