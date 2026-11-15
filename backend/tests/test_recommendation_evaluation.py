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

    @staticmethod
    def candidate_id(run, trend_id, brand_slug):
        return next(
            item["candidate_id"] for item in run["candidate_ids"]
            if item["trend_id"] == trend_id and item["brand_slug"] == brand_slug
        )

    def test_record_run_persists_all_brand_candidates_for_selection(self):
        item = self.item()
        item["brand_candidates"] = [
            {"brand": "alpha", "brand_name": "Alpha", "fit_score": 38},
            {"brand": "beta", "brand_name": "Beta", "fit_score": 34},
        ]
        result = self.store.record_run("US", [item])
        self.assertEqual(result["recorded_candidates"], 2)
        beta_id = self.candidate_id(result, "trend-1", "beta")
        linked = self.store.link_production(
            "trend-1", "beta", "job-beta", candidate_id=beta_id
        )
        self.assertTrue(linked["linked"])
        with self.store.db() as connection:
            row = connection.execute(
                "SELECT selected_job_id,decision FROM recommendation_candidates WHERE brand_slug='beta'"
            ).fetchone()
        self.assertEqual(row["selected_job_id"], "job-beta")
        self.assertEqual(row["decision"], "selected")

    def test_skip_feedback_is_audited_and_included_in_human_selection_summary(self):
        run = self.store.record_run("US", [self.item()])
        candidate_id = self.candidate_id(run, "trend-1", "future-leak")
        result = self.store.record_skip(
            "trend-1", "future-leak", "reviewer-1", "Topic is already overused",
            candidate_id=candidate_id,
        )
        self.assertTrue(result["recorded"])
        evaluation = self.store.evaluate({"videos": []})
        summary = evaluation["feedback_summary"]
        self.assertEqual(summary["skipped_count"], 1)
        self.assertEqual(summary["selected_count"], 0)
        self.assertEqual(summary["selection_rate"], 0.0)
        self.assertIn("not a platform performance metric", summary["interpretation"])

    def test_later_selection_supersedes_skip_but_preserves_feedback_event_history(self):
        run = self.store.record_run("US", [self.item()])
        candidate_id = self.candidate_id(run, "trend-1", "future-leak")
        self.store.record_skip(
            "trend-1", "future-leak", "reviewer-1", "Not suitable today",
            candidate_id=candidate_id,
        )
        linked = self.store.link_production(
            "trend-1", "future-leak", "job-after-reconsideration",
            candidate_id=candidate_id,
        )
        self.assertTrue(linked["linked"])
        evaluation = self.store.evaluate({"videos": []})
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
        self.assertEqual(first["candidate_ids"], repeated["candidate_ids"])
        self.assertTrue(repeated["deduplicated"])
        self.assertNotEqual(first["run_id"], later["run_id"])
        self.assertFalse(later["deduplicated"])

    def test_records_exposure_and_links_selected_production_job(self):
        run = self.store.record_run("US", [self.item(1, 82.5)],
                                    "2026-11-01T00:00:00+00:00")
        candidate_id = self.candidate_id(run, "trend-1", "future-leak")
        linked = self.store.link_production(
            "trend-1", "future-leak", "job-1",
            "2026-11-01T01:00:00+00:00", candidate_id=candidate_id,
        )
        self.assertTrue(linked["linked"])
        self.assertFalse(self.store.link_production(
            "trend-1", "future-leak", "job-2", candidate_id=candidate_id
        )["linked"])

    def test_holdout_is_chronological_and_reports_score_outcome_association(self):
        videos = []
        for index in range(10):
            timestamp = (datetime(2026, 11, 1, tzinfo=timezone.utc)
                         + timedelta(days=index)).isoformat()
            run = self.store.record_run(
                "US", [self.item(index, 50 + index * 2)], timestamp
            )
            candidate_id = self.candidate_id(
                run, f"trend-{index}", "future-leak"
            )
            self.store.link_production(
                f"trend-{index}", "future-leak", f"job-{index}",
                timestamp, candidate_id=candidate_id,
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
        self.assertEqual(result["pre_holdout_count"], 7)
        self.assertEqual(result["holdout_count"], 3)
        self.assertEqual(result["pre_holdout_run_count"], 7)
        self.assertEqual(result["holdout_run_count"], 3)
        self.assertEqual(result["holdout_score_views_spearman"], 1.0)
        self.assertFalse(result["ranking_score_adjustment_enabled"])
        self.assertIn("selection bias", result["warning"])

    def test_evaluation_rejects_boolean_nonfinite_and_duplicate_outcomes(self):
        videos = []
        for index in range(10):
            timestamp = (
                datetime(2026, 11, 1, tzinfo=timezone.utc)
                + timedelta(days=index)
            ).isoformat()
            run = self.store.record_run(
                "US", [self.item(index, 50 + index * 2)], timestamp
            )
            candidate_id = self.candidate_id(
                run, f"trend-{index}", "future-leak"
            )
            self.store.link_production(
                f"trend-{index}", "future-leak", f"job-{index}",
                timestamp, candidate_id=candidate_id,
            )
            videos.append({
                "job_id": f"job-{index}",
                "measurement_status": "measured",
                "views_per_hour": 100 + index * 10,
            })

        videos = [
            {"job_id": "job-0", "measurement_status": "measured",
             "views_per_hour": True},
            videos[0],
            {"job_id": "job-0", "measurement_status": "measured",
             "views_per_hour": 10000},
            *videos[1:],
            {"job_id": "not-selected-inf", "measurement_status": "measured",
             "views_per_hour": float("inf")},
            {"job_id": "not-selected-nan", "measurement_status": "measured",
             "views_per_hour": float("nan")},
            {"job_id": "not-selected-bool", "measurement_status": "measured",
             "views_per_hour": False},
            None,
        ]
        result = self.store.evaluate({"videos": videos})
        self.assertEqual(result["measured_outcome_count"], 10)
        self.assertEqual(result["holdout_score_views_spearman"], 1.0)

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
            run = self.store.record_run("US", items, timestamp)
            for candidate_index in range(3):
                trend_id = f"trend-{run_index * 3 + candidate_index}"
                job_id = f"within-job-{run_index}-{candidate_index}"
                candidate_id = self.candidate_id(run, trend_id, "future-leak")
                self.store.link_production(
                    trend_id, "future-leak", job_id, timestamp,
                    candidate_id=candidate_id,
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
        self.assertEqual(result["distinct_exposure_run_count"], 5)
        self.assertEqual(result["pre_holdout_run_count"], 3)
        self.assertEqual(result["holdout_run_count"], 2)
        self.assertEqual(result["pre_holdout_count"], 9)
        self.assertEqual(result["holdout_count"], 6)
        self.assertEqual(result["holdout_score_views_spearman"], 1.0)
        self.assertEqual(result["score_association_stability"], "consistent_positive")
        self.assertEqual(len(set(result["holdout_run_ids"])), 2)

    def test_primary_holdout_never_splits_an_exposure_run(self):
        videos = []
        for run_index in range(3):
            timestamp = (
                datetime(2026, 11, 1, tzinfo=timezone.utc)
                + timedelta(days=run_index)
            ).isoformat()
            items = [self.item(run_index * 5 + index, 90 - index * 10)
                     for index in range(5)]
            run = self.store.record_run("US", items, timestamp)
            for index in range(5):
                trend_id = f"trend-{run_index * 5 + index}"
                candidate_id = self.candidate_id(run, trend_id, "future-leak")
                job_id = f"grouped-job-{run_index}-{index}"
                self.store.link_production(
                    trend_id, "future-leak", job_id, timestamp,
                    candidate_id=candidate_id,
                )
                videos.append({
                    "job_id": job_id, "measurement_status": "measured",
                    "views_per_hour": 100 + run_index * 50 + index,
                })
        result = self.store.evaluate({"videos": videos})
        self.assertEqual(result["measured_outcome_count"], 15)
        self.assertEqual(result["status"], "insufficient_run_coverage")
        self.assertEqual(result["distinct_exposure_run_count"], 3)
        self.assertIsNone(result["holdout_score_views_spearman"])
        self.assertFalse(result["ranking_score_adjustment_enabled"])

    def test_evaluation_snapshot_is_immutable_and_deduplicated_by_input(self):
        videos = []
        for index in range(10):
            timestamp = (
                datetime(2026, 11, 1, tzinfo=timezone.utc)
                + timedelta(days=index)
            ).isoformat()
            run = self.store.record_run(
                "US", [self.item(index, 50 + index * 2)], timestamp
            )
            candidate_id = self.candidate_id(run, f"trend-{index}", "future-leak")
            self.store.link_production(
                f"trend-{index}", "future-leak", f"snapshot-job-{index}",
                timestamp, candidate_id=candidate_id,
            )
            videos.append({
                "job_id": f"snapshot-job-{index}",
                "measurement_status": "measured",
                "views_per_hour": 100 + index * 10,
            })
        result = self.store.evaluate({"videos": videos})
        first = self.store.record_evaluation_snapshot(result)
        repeated = self.store.record_evaluation_snapshot(result)
        history = self.store.list_evaluation_snapshots()
        self.assertFalse(first["deduplicated"])
        self.assertTrue(repeated["deduplicated"])
        self.assertEqual(first["snapshot_id"], repeated["snapshot_id"])
        self.assertEqual(history["count"], 1)
        self.assertEqual(history["items"][0]["input_fingerprint"],
                         result["input_fingerprint"])
        self.assertEqual(self.store.list_evaluation_snapshots(500)["limit"], 50)
        with self.store.db() as connection:
            with self.assertRaisesRegex(Exception, "immutable"):
                connection.execute(
                    "UPDATE recommendation_evaluation_snapshots SET status='changed'"
                )
            with self.assertRaisesRegex(Exception, "immutable"):
                connection.execute("DELETE FROM recommendation_evaluation_snapshots")

    def test_within_run_validation_excludes_unverified_requested_format(self):
        timestamp = "2026-11-01T00:00:00+00:00"
        items = [self.item(index, 90 - index * 10) for index in range(3)]
        run = self.store.record_run("US", items, timestamp)
        videos = []
        for index in range(3):
            trend_id = f"trend-{index}"
            job_id = f"requested-format-job-{index}"
            candidate_id = self.candidate_id(run, trend_id, "future-leak")
            self.store.link_production(
                trend_id, "future-leak", job_id, timestamp,
                candidate_id=candidate_id,
            )
            videos.append({
                "job_id": job_id,
                "measurement_status": "measured",
                "views_per_hour": 100 + index * 10,
                "brand": "Future Leak",
                "region": "US",
                "publication_age_bucket": "under_24h",
                "duration_bucket": "20_40s",
                "format": "vertical_short_requested",
            })
        result = self.store.evaluate({"videos": videos})
        within = result["within_run_validation"]
        self.assertEqual(within["eligible_run_count"], 0)
        self.assertEqual(within["status"], "insufficient_run_coverage")

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
            run = self.store.record_run("US", items, timestamp)
            for candidate_index in range(2):
                job_id = f"two-job-{run_index}-{candidate_index}"
                trend_id = f"trend-{run_index * 2 + candidate_index}"
                candidate_id = self.candidate_id(run, trend_id, "future-leak")
                self.store.link_production(
                    trend_id, "future-leak", job_id, timestamp,
                    candidate_id=candidate_id,
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
        run = self.store.record_run(
            "US", [self.item(1, 80)], "2026-11-01T00:00:00+00:00"
        )
        candidate_id = self.candidate_id(run, "trend-1", "future-leak")
        self.store.link_production(
            "trend-1", "future-leak", "job-1", candidate_id=candidate_id
        )
        result = self.store.evaluate({"videos": []})
        self.assertEqual(result["status"], "insufficient_data")
        self.assertEqual(result["selected_production_count"], 1)
        self.assertEqual(result["unmeasured_selected_count"], 1)
        self.assertFalse(result["ranking_score_adjustment_enabled"])

    def test_candidate_id_cannot_be_used_for_another_trend_or_brand(self):
        run = self.store.record_run("US", [self.item()])
        candidate_id = self.candidate_id(run, "trend-1", "future-leak")
        wrong_trend = self.store.link_production(
            "trend-other", "future-leak", "job-wrong-trend",
            candidate_id=candidate_id,
        )
        wrong_brand = self.store.link_production(
            "trend-1", "other-brand", "job-wrong-brand",
            candidate_id=candidate_id,
        )
        self.assertFalse(wrong_trend["linked"])
        self.assertFalse(wrong_brand["linked"])
        self.assertEqual(
            self.store.evaluate({"videos": []})["selected_production_count"], 0
        )

    def test_spearman_handles_ties_and_constant_values(self):
        self.assertEqual(_spearman([1, 2, 3], [10, 20, 30]), 1.0)
        self.assertIsNone(_spearman([1, 1, 1], [10, 20, 30]))





    def test_shadow_experiment_assignments_are_stable_and_do_not_claim_exposure(self):
        experiment = self.store.create_experiment(
            "thumbnail wording", "operator-1", allocation_basis_points=5000
        )
        first = self.store.assign_shadow(experiment["experiment_id"], "opaque-user-1")
        repeated = self.store.assign_shadow(experiment["experiment_id"], "opaque-user-1")
        self.assertIn(first["arm"], ("control", "treatment"))
        self.assertEqual(first["arm"], repeated["arm"])
        self.assertFalse(first["deduplicated"])
        self.assertTrue(repeated["deduplicated"])
        self.assertEqual(first["assignment_id"], repeated["assignment_id"])
        self.assertEqual(first["assignment_mode"], "shadow_only")
        self.assertFalse(first["recommendation_served"])
        self.assertFalse(first["production_behavior_changed"])
        self.assertFalse(first["measured_exposure"])
        self.assertFalse(first["participant_identifier_stored"])
        report = self.store.experiment_report(experiment["experiment_id"])
        self.assertEqual(report["shadow_assignment_count"], 1)
        self.assertEqual(report["measured_exposure_count"], 0)
        self.assertIsNone(report["effect_estimate"])
        self.assertFalse(report["live_assignment_enabled"])
        with self.store.db() as connection:
            row = connection.execute(
                "SELECT participant_fingerprint FROM recommendation_experiment_assignments"
            ).fetchone()
        self.assertEqual(len(row["participant_fingerprint"]), 64)
        self.assertNotIn("opaque-user-1", row["participant_fingerprint"])

    def test_experiment_allocation_validation_and_unknown_experiment(self):
        with self.assertRaises(ValueError):
            self.store.create_experiment("bad", "operator", allocation_basis_points=9500)
        experiment = self.store.create_experiment("valid", "operator")
        self.assertIsNone(self.store.assign_shadow("missing", "user-1"))
        self.assertIsNone(self.store.experiment_report("missing"))
        self.assertEqual(self.store.list_experiments()["count"], 1)

    def test_experiment_assignment_rejects_empty_or_oversized_participant_key(self):
        experiment = self.store.create_experiment("validation", "operator")
        with self.assertRaises(ValueError):
            self.store.assign_shadow(experiment["experiment_id"], "")
        with self.assertRaises(ValueError):
            self.store.assign_shadow(experiment["experiment_id"], "x" * 257)



    def test_participant_fingerprints_are_scoped_per_experiment(self):
        first_experiment = self.store.create_experiment("first", "operator")
        second_experiment = self.store.create_experiment("second", "operator")
        self.store.assign_shadow(first_experiment["experiment_id"], "same-private-key")
        self.store.assign_shadow(second_experiment["experiment_id"], "same-private-key")
        with self.store.db() as connection:
            rows = connection.execute(
                "SELECT participant_fingerprint FROM recommendation_experiment_assignments ORDER BY experiment_id"
            ).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0]["participant_fingerprint"], rows[1]["participant_fingerprint"])


    def test_rendered_exposure_records_only_candidates_in_captured_run_and_is_idempotent(self):
        run=self.store.record_run("US",[self.item(1),self.item(2)])
        event="b8d6f5e4-73b0-4f6d-91ab-2d5e5a1c0f01"
        first=self.store.record_rendered_exposures(run["run_id"],[{
            "event_id":event,"trend_id":"trend-1","visibility_ms":1200
        }])
        repeated=self.store.record_rendered_exposures(run["run_id"],[{
            "event_id":event,"trend_id":"trend-1","visibility_ms":1200
        }])
        self.assertEqual(first["recorded_count"],1)
        self.assertEqual(repeated["recorded_count"],0)
        self.assertEqual(repeated["duplicate_count"],1)
        self.assertFalse(first["randomized_assignment"])
        with self.assertRaises(ValueError):
            self.store.record_rendered_exposures(run["run_id"],[{
                "event_id":"b8d6f5e4-73b0-4f6d-91ab-2d5e5a1c0f02",
                "trend_id":"not-in-run","visibility_ms":1200
            }])
        report=self.store.rendered_exposure_report(run["run_id"])
        self.assertEqual(report["visible_trend_card_count"],1)
        self.assertEqual(report["unseen_trend_card_count"],1)
        self.assertEqual(report["render_impression_count"],1)
        self.assertEqual(report["causal_effect_status"],"not_estimable_nonrandomized")

    def test_rendered_exposure_report_counts_only_post_render_measured_outcomes(self):
        run=self.store.record_run("US",[self.item(1)])
        candidate=self.candidate_id(run,"trend-1","future-leak")
        self.store.record_rendered_exposures(run["run_id"],[{
            "event_id":"b8d6f5e4-73b0-4f6d-91ab-2d5e5a1c0f03",
            "trend_id":"trend-1","visibility_ms":1500
        }])
        self.store.link_production("trend-1","future-leak","job-after",
            selected_at="9999-01-01T00:00:00+00:00",candidate_id=candidate)
        report=self.store.rendered_exposure_report(run["run_id"],{"videos":[
            {"job_id":"job-after","measurement_status":"measured","views_per_hour":12.5},
            {"job_id":"unrelated","measurement_status":"measured","views_per_hour":99}
        ]})
        item=report["items"][0]
        self.assertEqual(item["selected_after_exposure_count"],1)
        self.assertEqual(item["measured_outcome_count"],1)
        self.assertEqual(item["median_views_per_hour"],12.5)
        self.assertEqual(report["measured_outcome_count"],1)
        self.assertEqual(report["ranking_score_adjustment"],0)

    def test_rendered_exposure_validation_and_immutable_storage(self):
        run=self.store.record_run("US",[self.item(1)])
        with self.assertRaises(ValueError):
            self.store.record_rendered_exposures(run["run_id"],[{
                "event_id":"not-a-uuid","trend_id":"trend-1","visibility_ms":1500
            }])
        with self.assertRaises(ValueError):
            self.store.record_rendered_exposures(run["run_id"],[{
                "event_id":"b8d6f5e4-73b0-4f6d-91ab-2d5e5a1c0f04",
                "trend_id":"trend-1","visibility_ms":999
            }])
        self.store.record_rendered_exposures(run["run_id"],[{
            "event_id":"b8d6f5e4-73b0-4f6d-91ab-2d5e5a1c0f05",
            "trend_id":"trend-1","visibility_ms":1500
        }])
        with self.store.db() as connection:
            with self.assertRaises(Exception):
                connection.execute("UPDATE recommendation_rendered_exposures SET visibility_ms=2000")
            with self.assertRaises(Exception):
                connection.execute("DELETE FROM recommendation_rendered_exposures")
        self.assertIsNone(self.store.rendered_exposure_report("missing-run"))

    def test_experiment_integrity_report_distinguishes_shadow_and_viewport_events(self):
        experiment = self.store.create_experiment("integrity", "operator")
        self.store.assign_shadow(experiment["experiment_id"], "opaque-participant")
        run = self.store.record_run("US", [self.item(1)])
        self.store.record_rendered_exposures(run["run_id"], [{
            "event_id": "b8d6f5e4-73b0-4f6d-91ab-2d5e5a1c0f06",
            "trend_id": "trend-1", "visibility_ms": 1500
        }])
        report = self.store.experiment_integrity_report()
        self.assertEqual(report["status"], "shadow_only_no_verified_exposure")
        self.assertEqual(report["shadow_assignment_count"], 1)
        self.assertEqual(report["rendered_viewport_acknowledgement_count"], 1)
        self.assertEqual(report["verified_randomized_served_exposure_count"], 0)
        self.assertFalse(report["assignment_exposure_join_available"])
        self.assertFalse(report["outcome_attribution_to_experiment_arm_available"])
        self.assertFalse(report["live_assignment_enabled"])
        self.assertEqual(report["ranking_score_adjustment"], 0)
        self.assertEqual(report["items"][0]["integrity_status"], "shadow_records_consistent")

    def test_experiment_integrity_report_flags_unexpected_assignment_mode(self):
        experiment = self.store.create_experiment("tamper audit", "operator")
        self.store.assign_shadow(experiment["experiment_id"], "opaque-participant")
        with self.store.db() as connection:
            connection.execute(
                "DROP TRIGGER recommendation_experiment_assignments_no_update"
            )
            connection.execute(
                "UPDATE recommendation_experiment_assignments SET assignment_mode='live'"
            )
        report = self.store.experiment_integrity_report()
        self.assertEqual(report["status"], "integrity_warning")
        self.assertEqual(report["integrity_warning_experiment_count"], 1)
        self.assertEqual(report["items"][0]["unexpected_mode_count"], 1)
        self.assertEqual(report["verified_randomized_served_exposure_count"], 0)

if __name__ == "__main__":
    unittest.main()
