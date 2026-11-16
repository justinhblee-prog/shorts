import json
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

    def test_record_run_ignores_malformed_exposure_rows_and_scores(self):
        valid = self.item(90, 82.5)
        invalid_score_bool = self.item(91, 80)
        invalid_score_bool["recommendation_score"] = True
        invalid_score_nan = self.item(92, 80)
        invalid_score_nan["recommendation_score"] = float("nan")
        invalid_score_overflow = self.item(93, 80)
        invalid_score_overflow["recommendation_score"] = 10 ** 10000
        malformed_nested = self.item(94, 80)
        malformed_nested["trend"] = "not-an-object"
        malformed_nested["best_brand"] = ["not-an-object"]
        malformed_candidates = self.item(95, 80)
        malformed_candidates["brand_candidates"] = [
            None, "bad-row", {"brand": "  ", "brand_name": "Blank"},
            {"brand": "valid-brand", "brand_name": "Valid Brand",
             "fit_score": float("inf"),
             "comparable_cohort_performance": {"bad": float("nan")}},
        ]
        exposure = self.store.record_run("US", [
            None, "not-a-dict", invalid_score_bool, invalid_score_nan,
            invalid_score_overflow, malformed_nested, malformed_candidates, valid,
        ], "2026-11-01T00:00:00+00:00")
        self.assertEqual(exposure["recorded_candidates"], 2)
        with self.store.db() as connection:
            rows = connection.execute(
                "SELECT trend_id,recommendation_score,score_breakdown_json,cohort_context_json "
                "FROM recommendation_candidates WHERE run_id=? ORDER BY trend_id",
                (exposure["run_id"],),
            ).fetchall()
        self.assertEqual([row["trend_id"] for row in rows], ["trend-90", "trend-95"])
        self.assertEqual(rows[0]["recommendation_score"], 82.5)
        self.assertEqual(rows[1]["recommendation_score"], 80.0)
        self.assertIsNone(json.loads(rows[1]["cohort_context_json"])["bad"])


    def test_evaluate_ignores_malformed_retention_curve_containers(self):
        for curve in (None, 0, "invalid", {"point": 0}):
            with self.subTest(curve=curve):
                normalized = self.store.evaluate({"videos": [{
                    "job_id": "job-no-crash",
                    "platform": "youtube",
                    "measurement_status": "measured",
                    "views_per_hour": 12,
                    "audience_retention_curve": curve,
                }]})
                self.assertEqual(normalized["selected_production_count"], 0)
                self.assertEqual(normalized["measured_outcome_count"], 0)

    def test_record_run_rejects_invalid_timestamp_and_region_before_writing(self):
        for timestamp in ("not-a-date", "", [], "2026-99-99T00:00:00Z"):
            with self.subTest(timestamp=timestamp):
                with self.assertRaisesRegex(ValueError, "generated_at"):
                    self.store.record_run("US", [], timestamp)
        for region in ([], {"region": "US"}, "", "R" * 121):
            with self.subTest(region=region):
                with self.assertRaisesRegex(ValueError, "region"):
                    self.store.record_run(region, [], "2026-11-01T00:00:00Z")
        with self.store.db() as connection:
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM recommendation_runs"
            ).fetchone()[0], 0)

    def test_record_run_normalizes_timezone_and_naive_timestamps(self):
        aware = self.store.record_run(
            "US", [], "2026-11-01T00:00:00Z"
        )
        naive = self.store.record_run(
            "US", [], "2026-11-01T00:02:00"
        )
        with self.store.db() as connection:
            timestamps = [
                row[0] for row in connection.execute(
                    "SELECT generated_at FROM recommendation_runs ORDER BY generated_at"
                ).fetchall()
            ]
        self.assertEqual(timestamps[0], "2026-11-01T00:00:00+00:00")
        self.assertEqual(timestamps[1], "2026-11-01T00:02:00+00:00")

    def test_link_production_rejects_malformed_identity_and_timestamp(self):
        exposure = self.store.record_run(
            "US", [self.item(98, 80)], "2026-11-01T00:00:00Z"
        )
        for trend, brand, job in (
            ([], "future-leak", "job"),
            ("trend-98", [], "job"),
            ("trend-98", "future-leak", {"job": "id"}),
        ):
            with self.subTest(trend=trend, brand=brand, job=job):
                result = self.store.link_production(
                    trend, brand, job, run_id=exposure["run_id"]
                )
                self.assertFalse(result["linked"])
                self.assertEqual(result["reason"], "invalid_production_identity")
        with self.assertRaisesRegex(ValueError, "selected_at"):
            self.store.link_production(
                "trend-98", "future-leak", "job-valid",
                selected_at="yesterday", run_id=exposure["run_id"]
            )
        self.assertTrue(self.store.link_production(
            "trend-98", "future-leak", "job-valid",
            selected_at="2026-11-01T01:00:00Z", run_id=exposure["run_id"]
        )["linked"])

    def test_record_run_rejects_non_list_payload_without_crashing(self):
        exposure = self.store.record_run(
            "US", {"unexpected": "mapping"}, "2026-11-01T00:00:00+00:00"
        )
        self.assertEqual(exposure["recorded_candidates"], 0)

    def test_evaluate_ignores_unhashable_and_oversized_cohort_dimensions(self):
        exposure = self.store.record_run(
            "US", [self.item(96, 82.5)], "2026-11-01T00:00:00+00:00"
        )
        self.store.link_production(
            "trend-96", "future-leak", "job-malformed-cohort",
            "2026-11-01T01:00:00+00:00", run_id=exposure["run_id"],
        )
        result = self.store.evaluate({"videos": [{
            "job_id": "job-malformed-cohort",
            "platform": "youtube",
            "measurement_status": "measured",
            "views_per_hour": 120,
            "brand": {"unexpected": "mapping"},
            "region": ["US"],
            "publication_age_bucket": {"days": 1},
            "duration_bucket": ["short"],
            "format": "x" * 121,
        }]})
        self.assertEqual(result["selected_production_count"], 1)
        self.assertEqual(result["measured_outcome_count"], 1)
        self.assertEqual(result["any_metric_measured_outcome_count"], 1)
        self.assertEqual(result["within_run_validation"]["eligible_run_count"], 0)

    def test_evaluate_trims_valid_cohort_dimensions_and_job_ids(self):
        exposure = self.store.record_run(
            "US", [self.item(97, 82.5)], "2026-11-01T00:00:00+00:00"
        )
        self.store.link_production(
            "trend-97", "future-leak", "job-trimmed",
            "2026-11-01T01:00:00+00:00", run_id=exposure["run_id"],
        )
        result = self.store.evaluate({"videos": [{
            "job_id": " job-trimmed ",
            "platform": " youtube ",
            "measurement_status": "measured",
            "views_per_hour": 120,
            "brand": " Future Leak ",
            "region": " US ",
            "publication_age_bucket": " 1-7d ",
            "duration_bucket": " 30-60s ",
            "format": " vertical ",
        }]})
        self.assertEqual(result["measured_outcome_count"], 1)

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

    def test_exposure_records_every_brand_option_offered_in_the_dashboard(self):
        item = self.item(21, 86.0)
        item["brand_candidates"] = [
            {
                "brand": "future-leak", "brand_name": "Future Leak",
                "fit_score": 32.0,
                "comparable_cohort_performance": {"matched_cohort_count": 2},
            },
            {
                "brand": "brain-glitch", "brand_name": "Brain Glitch",
                "fit_score": 28.0,
                "comparable_cohort_performance": {"matched_cohort_count": 1},
            },
            {
                "brand": "silent-signals", "brand_name": "Silent Signals",
                "fit_score": 22.0,
            },
        ]
        exposure = self.store.record_run(
            "US", [item], "2026-11-01T00:00:00+00:00"
        )
        self.assertEqual(exposure["recorded_candidates"], 3)

        linked = self.store.link_production(
            "trend-21", "brain-glitch", "job-alternate-brand",
            run_id=exposure["run_id"],
        )
        self.assertTrue(linked["linked"])
        with self.store.db() as connection:
            rows = connection.execute(
                """SELECT brand_slug,selected_job_id,score_breakdown_json,
                          cohort_context_json
                   FROM recommendation_candidates WHERE run_id=?
                   ORDER BY brand_slug""",
                (exposure["run_id"],),
            ).fetchall()
        by_brand = {row["brand_slug"]: row for row in rows}
        self.assertEqual(set(by_brand), {
            "future-leak", "brain-glitch", "silent-signals"
        })
        self.assertEqual(
            by_brand["brain-glitch"]["selected_job_id"], "job-alternate-brand"
        )
        self.assertIsNone(by_brand["future-leak"]["selected_job_id"])
        self.assertEqual(
            json.loads(by_brand["brain-glitch"]["score_breakdown_json"])[
                "selected_brand_fit"
            ],
            28.0,
        )
        self.assertEqual(
            json.loads(by_brand["brain-glitch"]["cohort_context_json"])[
                "matched_cohort_count"
            ],
            1,
        )

    def test_exposure_signature_includes_alternative_brand_options(self):
        first_item = self.item(22, 86.0)
        first_item["brand_candidates"] = [
            {"brand": "future-leak", "brand_name": "Future Leak", "fit_score": 32.0},
            {"brand": "brain-glitch", "brand_name": "Brain Glitch", "fit_score": 28.0},
        ]
        changed_item = self.item(22, 86.0)
        changed_item["brand_candidates"] = [
            {"brand": "future-leak", "brand_name": "Future Leak", "fit_score": 32.0},
            {"brand": "silent-signals", "brand_name": "Silent Signals", "fit_score": 24.0},
        ]
        first = self.store.record_run(
            "US", [first_item], "2026-11-01T00:00:00+00:00"
        )
        changed = self.store.record_run(
            "US", [changed_item], "2026-11-01T00:00:30+00:00"
        )
        self.assertNotEqual(first["run_id"], changed["run_id"])
        self.assertFalse(changed["deduplicated"])

    def test_same_trend_exposures_are_isolated_by_platform(self):
        youtube = self.store.record_run(
            "US", [self.item(1, 82.5)], "2026-11-01T00:00:00+00:00",
            platform="youtube",
        )
        tiktok = self.store.record_run(
            "US", [self.item(1, 82.5)], "2026-11-01T00:00:00+00:00",
            platform="tiktok",
        )
        self.assertNotEqual(youtube["run_id"], tiktok["run_id"])
        yt_link = self.store.link_production(
            "trend-1","future-leak","job-youtube",
            "2026-11-01T01:00:00+00:00",platform="youtube",
            run_id=youtube["run_id"],
        )
        tt_link = self.store.link_production(
            "trend-1","future-leak","job-tiktok",
            "2026-11-01T01:00:00+00:00",platform="tiktok",
            run_id=tiktok["run_id"],
        )
        self.assertTrue(yt_link["linked"])
        self.assertTrue(tt_link["linked"])
        result=self.store.evaluate({"videos":[
            {"job_id":"job-youtube","platform":"youtube","measurement_status":"measured","views_per_hour":100},
            {"job_id":"job-tiktok","platform":"tiktok","measurement_status":"measured","views_per_hour":200},
        ]},platform="tiktok")
        self.assertEqual(result["platform"],"tiktok")
        self.assertEqual(result["selected_production_count"],1)
        self.assertEqual(result["measured_outcome_count"],1)

    def test_records_exposure_and_links_selected_production_job(self):
        exposure = self.store.record_run(
            "US", [self.item(1, 82.5)], "2026-11-01T00:00:00+00:00"
        )
        linked = self.store.link_production(
            "trend-1", "future-leak", "job-1",
            "2026-11-01T01:00:00+00:00", run_id=exposure["run_id"]
        )
        self.assertTrue(linked["linked"])
        self.assertFalse(self.store.link_production(
            "trend-1", "future-leak", "job-2",
            run_id=exposure["run_id"],
        )["linked"])

    def test_selection_links_to_the_exact_exposure_not_a_later_refresh(self):
        first = self.store.record_run(
            "US", [self.item(7, 88.0)], "2026-11-01T00:00:00+00:00"
        )
        second = self.store.record_run(
            "US", [self.item(7, 91.0)], "2026-11-01T00:02:00+00:00"
        )
        self.assertNotEqual(first["run_id"], second["run_id"])

        linked = self.store.link_production(
            "trend-7", "future-leak", "job-from-first-screen",
            "2026-11-01T00:03:00+00:00", run_id=first["run_id"],
        )
        self.assertTrue(linked["linked"])
        self.assertEqual(linked["run_id"], first["run_id"])

        with self.store.db() as connection:
            first_row = connection.execute(
                "SELECT selected_job_id FROM recommendation_candidates WHERE run_id=?",
                (first["run_id"],),
            ).fetchone()
            second_row = connection.execute(
                "SELECT selected_job_id FROM recommendation_candidates WHERE run_id=?",
                (second["run_id"],),
            ).fetchone()
        self.assertEqual(first_row["selected_job_id"], "job-from-first-screen")
        self.assertIsNone(second_row["selected_job_id"])

    def test_missing_or_unknown_exposure_never_falls_back_to_latest_run(self):
        self.store.record_run(
            "US", [self.item(8, 88.0)], "2026-11-01T00:00:00+00:00"
        )
        missing = self.store.link_production(
            "trend-8", "future-leak", "job-without-run"
        )
        stale = self.store.link_production(
            "trend-8", "future-leak", "job-with-stale-run",
            run_id="stale-run-id",
        )
        self.assertFalse(missing["linked"])
        self.assertEqual(missing["reason"], "recommendation_run_id_required")
        self.assertFalse(stale["linked"])
        self.assertEqual(
            stale["reason"], "no_matching_candidate_in_recommendation_run"
        )
        with self.store.db() as connection:
            row = connection.execute(
                "SELECT selected_job_id FROM recommendation_candidates"
            ).fetchone()
        self.assertIsNone(row["selected_job_id"])

    def test_holdout_is_chronological_and_reports_score_outcome_association(self):
        videos = []
        for index in range(10):
            timestamp = (datetime(2026, 11, 1, tzinfo=timezone.utc)
                         + timedelta(days=index)).isoformat()
            exposure = self.store.record_run(
                "US", [self.item(index, 50 + index * 2)], timestamp
            )
            self.store.link_production(
                f"trend-{index}", "future-leak", f"job-{index}",
                timestamp, run_id=exposure["run_id"]
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
            exposure = self.store.record_run("US", items, timestamp)
            for candidate_index in range(3):
                trend_id = f"trend-{run_index * 3 + candidate_index}"
                job_id = f"within-job-{run_index}-{candidate_index}"
                self.store.link_production(
                    trend_id, "future-leak", job_id, timestamp,
                    run_id=exposure["run_id"],
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
            exposure = self.store.record_run("US", items, timestamp)
            for candidate_index in range(2):
                job_id = f"two-job-{run_index}-{candidate_index}"
                self.store.link_production(
                    f"trend-{run_index * 2 + candidate_index}",
                    "future-leak", job_id, timestamp,
                    run_id=exposure["run_id"],
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
        exposure = self.store.record_run(
            "US", [self.item(1, 80)], "2026-11-01T00:00:00+00:00"
        )
        self.store.link_production(
            "trend-1", "future-leak", "job-1", run_id=exposure["run_id"]
        )
        result = self.store.evaluate({"videos": []})
        self.assertEqual(result["status"], "insufficient_data")
        self.assertEqual(result["selected_production_count"], 1)
        self.assertEqual(result["unmeasured_selected_count"], 1)
        self.assertFalse(result["ranking_score_adjustment_enabled"])


    def test_analytics_only_outcomes_are_evaluated_in_separate_chronological_holdouts(self):
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
            exposure = self.store.record_run("US", items, timestamp)
            videos = []
            for candidate_index, (percentage, duration, retention) in enumerate(
                ((90.0, 20.0, 0.9), (70.0, 15.0, 0.6), (50.0, 10.0, 0.3))
            ):
                job_id = f"analytics-job-{run_index}-{candidate_index}"
                self.store.link_production(
                    f"trend-{run_index * 3 + candidate_index}",
                    "future-leak", job_id, timestamp,
                    run_id=exposure["run_id"],
                )
                videos.append({
                    "job_id": job_id,
                    "platform": "youtube",
                    "measurement_status": "insufficient_snapshots",
                    "views_per_hour": None,
                    "engaged_view_share": retention,
                    "average_view_percentage": percentage,
                    "average_view_duration_seconds": duration,
                    "audience_retention_curve": [
                        {"elapsed_video_time_ratio": 0.25,
                         "audience_watch_ratio": retention},
                        {"elapsed_video_time_ratio": 0.50,
                         "audience_watch_ratio": retention - 0.1},
                        {"elapsed_video_time_ratio": 0.75,
                         "audience_watch_ratio": retention - 0.2},
                    ],
                    "brand": "Future Leak",
                    "region": "US",
                    "publication_age_bucket": "1_7d",
                    "duration_bucket": "under_20s",
                    "format": "vertical_short",
                })
            if run_index == 0:
                all_videos = videos
            else:
                all_videos.extend(videos)

        result = self.store.evaluate({"videos": all_videos})
        self.assertEqual(result["measured_outcome_count"], 0)
        self.assertEqual(result["analytics_measured_outcome_count"], 15)
        self.assertEqual(result["any_metric_measured_outcome_count"], 15)
        analytics = result["analytics_outcome_validation"]
        for metric in (
            "engaged_view_share", "average_view_percentage", "average_view_duration_seconds",
            "audience_watch_ratio_25", "audience_watch_ratio_50",
            "audience_watch_ratio_75",
        ):
            self.assertEqual(analytics[metric]["status"], "holdout_available")
            self.assertEqual(analytics[metric]["eligible_run_count"], 5)
            self.assertEqual(analytics[metric]["holdout_run_count"], 2)
            self.assertFalse(analytics[metric]["score_adjustment_enabled"])
        self.assertFalse(result["ranking_score_adjustment_enabled"])

    def test_evaluation_rejects_boolean_nonfinite_and_out_of_range_metrics(self):
        exposure = self.store.record_run(
            "US", [self.item(31, 80), self.item(32, 70), self.item(33, 60)],
            "2026-11-01T00:00:00+00:00",
        )
        jobs = ["invalid-bool", "invalid-overflow", "valid-average"]
        for index, job_id in enumerate(jobs):
            self.store.link_production(
                f"trend-{31 + index}", "future-leak", job_id,
                run_id=exposure["run_id"],
            )
        result = self.store.evaluate({"videos": [
            {
                "job_id": jobs[0], "measurement_status": "measured",
                "views_per_hour": True, "engaged_view_share": True,
                "average_view_percentage": False,
                "average_view_duration_seconds": float("inf"),
                "audience_retention_curve": [
                    {"elapsed_video_time_ratio": True, "audience_watch_ratio": 0.9},
                    {"elapsed_video_time_ratio": 0.5, "audience_watch_ratio": 1.2},
                ],
            },
            {
                "job_id": jobs[1], "measurement_status": "measured",
                "views_per_hour": 10 ** 10000,
                "average_view_percentage": float("nan"),
                "average_view_duration_seconds": -1,
                "audience_retention_curve": [
                    {"elapsed_video_time_ratio": float("inf"),
                     "audience_watch_ratio": 0.8},
                ],
            },
            {
                "job_id": jobs[2], "measurement_status": "insufficient_snapshots",
                "views_per_hour": None, "engaged_view_share": 0.8,
                "average_view_percentage": 125.0,
                "average_view_duration_seconds": 12.5,
                "audience_retention_curve": [
                    {"elapsed_video_time_ratio": 0.25, "audience_watch_ratio": 0.7},
                    {"elapsed_video_time_ratio": 0.5, "audience_watch_ratio": 0.6},
                ],
                "brand": "Future Leak", "region": "US",
                "publication_age_bucket": "under_24h",
                "duration_bucket": "15_30s", "format": "vertical_short",
            },
        ]})
        self.assertEqual(result["selected_production_count"], 3)
        self.assertEqual(result["measured_outcome_count"], 0)
        self.assertEqual(result["analytics_measured_outcome_count"], 1)
        self.assertEqual(result["any_metric_measured_outcome_count"], 1)
        self.assertEqual(result["unmeasured_selected_count"], 2)
        self.assertFalse(result["ranking_score_adjustment_enabled"])

    def test_spearman_handles_ties_and_constant_values(self):
        self.assertEqual(_spearman([1, 2, 3], [10, 20, 30]), 1.0)
        self.assertIsNone(_spearman([1, 1, 1], [10, 20, 30]))


if __name__ == "__main__":
    unittest.main()


    def test_pooled_holdout_orders_outcomes_by_selection_timestamp(self):
        videos = []
        base = datetime(2026, 11, 1, tzinfo=timezone.utc)
        for index in range(10):
            exposure_at = (base + timedelta(days=index)).isoformat()
            selected_at = (base + timedelta(days=9 - index)).isoformat()
            exposure = self.store.record_run(
                "US", [self.item(index, 50 + index * 2)], exposure_at
            )
            self.store.link_production(
                f"trend-{index}", "future-leak", f"chronological-job-{index}",
                selected_at, run_id=exposure["run_id"],
            )
            videos.append({
                "job_id": f"chronological-job-{index}",
                "measurement_status": "measured",
                "views_per_hour": 100 + (9 - index) * 10,
            })

        result = self.store.evaluate({"videos": videos})
        self.assertEqual(result["status"], "holdout_available")
        self.assertEqual(result["holdout_count"], 5)
        self.assertEqual(
            result["holdout_start"], (base + timedelta(days=5)).isoformat()
        )
        self.assertEqual(
            result["holdout_end"], (base + timedelta(days=9)).isoformat()
        )
        self.assertEqual(result["holdout_score_views_spearman"], -1.0)


    def test_pooled_holdout_orders_mixed_timezone_offsets_by_absolute_time(self):
        videos = []
        base = datetime(2026, 11, 1, tzinfo=timezone.utc)
        for index in range(10):
            exposure_at = (base + timedelta(days=index)).isoformat()
            offset = timezone(timedelta(hours=5 if index % 2 else -4))
            selected_at = (base + timedelta(days=index)).astimezone(offset).isoformat()
            exposure = self.store.record_run(
                "US", [self.item(100 + index, 60 + index)], exposure_at
            )
            self.store.link_production(
                f"trend-{100 + index}", "future-leak", f"offset-job-{index}",
                selected_at, run_id=exposure["run_id"],
            )
            videos.append({
                "job_id": f"offset-job-{index}",
                "measurement_status": "measured",
                "views_per_hour": 100 + index * 10,
            })

        result = self.store.evaluate({"videos": videos})
        self.assertEqual(
            datetime.fromisoformat(result["holdout_start"]),
            base + timedelta(days=5),
        )
        self.assertEqual(
            datetime.fromisoformat(result["holdout_end"]),
            base + timedelta(days=9),
        )


    def test_exposure_deduplication_uses_a_bounded_symmetric_time_window(self):
        later = self.store.record_run(
            "US", [self.item(150, 82.5)], "2026-11-01T00:05:00Z"
        )
        earlier = self.store.record_run(
            "US", [self.item(150, 82.5)], "2026-11-01T00:00:00Z"
        )
        self.assertNotEqual(later["run_id"], earlier["run_id"])
        self.assertFalse(earlier["deduplicated"])

        near = self.store.record_run(
            "US", [self.item(151, 82.5)], "2026-11-01T00:00:00Z"
        )
        repeated = self.store.record_run(
            "US", [self.item(151, 82.5)], "2026-11-01T00:01:00Z"
        )
        self.assertEqual(near["run_id"], repeated["run_id"])
        self.assertTrue(repeated["deduplicated"])

    def test_timestamp_ingress_canonicalizes_offsets_to_utc_for_storage(self):
        exposure = self.store.record_run(
            "US", [self.item(152, 82.5)], "2026-11-01T09:00:00+09:00"
        )
        with self.store.db() as connection:
            stored = connection.execute(
                "SELECT generated_at FROM recommendation_runs WHERE id=?",
                (exposure["run_id"],),
            ).fetchone()["generated_at"]
        self.assertEqual(stored, "2026-11-01T00:00:00+00:00")
        same_instant = self.store.record_run(
            "US", [self.item(152, 82.5)], "2026-11-01T00:00:30Z"
        )
        self.assertEqual(same_instant["run_id"], exposure["run_id"])
        self.assertTrue(same_instant["deduplicated"])


    def test_exposure_deduplication_handles_legacy_offset_timestamps(self):
        exposure = self.store.record_run(
            "US", [self.item(153, 82.5)], "2026-11-01T09:00:00+09:00"
        )
        with self.store.db() as connection:
            connection.execute(
                "UPDATE recommendation_runs SET generated_at=? WHERE id=?",
                ("2026-11-01T09:00:00+09:00", exposure["run_id"]),
            )
        repeated = self.store.record_run(
            "US", [self.item(153, 82.5)], "2026-11-01T00:00:30Z"
        )
        self.assertEqual(repeated["run_id"], exposure["run_id"])
        self.assertTrue(repeated["deduplicated"])
