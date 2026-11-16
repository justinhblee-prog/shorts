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
        self.assertIn("trend_source_provenance_incomplete", ranked[0]["evidence_gaps"])
        self.assertEqual(ranked[0]["recommendation_score"],
                         round(sum(ranked[0]["score_breakdown"].values()), 2))

    def test_recommendations_are_labeled_for_selected_platform(self):
        now=datetime(2026,11,15,tzinfo=timezone.utc)
        result=rank_trend_candidates(
            [{"id":"tt","title":"AI technology research","region":"US",
              "published_at":now.isoformat()}],
            [{"slug":"future-leak","name":"Future Leak","active":True,
              "config":{"positioning":"AI technology","regions":["US"],"languages":["en"]}}],
            now=now,platform="tiktok",
        )
        self.assertEqual(result[0]["platform"],"tiktok")

    def test_no_brand_match_is_not_invented(self):
        result = rank_trend_candidates(
            [{"id": "x", "title": "Local gardening", "region": "US"}],
            [{"slug": "future-leak", "name": "Future Leak", "active": True,
              "config": {"positioning": "AI technology", "regions": ["US"]}}],
            now=datetime(2026, 11, 15, tzinfo=timezone.utc))
        self.assertIsNone(result[0]["best_brand"])
        self.assertEqual(result[0]["recommendation_score"], 0)

    def test_provenance_and_topic_distinctiveness_fill_only_editorial_evidence_points(self):
        now = datetime(2026, 11, 15, tzinfo=timezone.utc)
        brands = [{
            "slug": "future-leak", "name": "Future Leak", "active": True,
            "config": {"positioning": "AI technology", "regions": ["US"]}
        }]
        trends = [
            {"id": "a", "title": "AI technology in healthcare", "region": "US",
             "source": "google_news_rss", "url": "https://news.example/a",
             "published_at": now.isoformat()},
            {"id": "b", "title": "AI technology in healthcare", "region": "US",
             "source": "google_news_rss", "url": "https://news.example/b",
             "published_at": now.isoformat()},
            {"id": "c", "title": "AI technology in robotics", "region": "US",
             "source": "google_news_rss", "url": "https://news.example/c",
             "published_at": now.isoformat()},
        ]
        ranked = rank_trend_candidates(trends, brands, now=now)
        duplicate = next(item for item in ranked if item["trend"]["id"] == "a")
        distinct = next(item for item in ranked if item["trend"]["id"] == "c")
        self.assertEqual(duplicate["source_evidence_score"], 10)
        self.assertLess(duplicate["topic_distinctiveness_score"],
                        distinct["topic_distinctiveness_score"])
        self.assertEqual(duplicate["recommendation_score"],
                         round(sum(duplicate["score_breakdown"].values()), 2))
        self.assertEqual(duplicate["score_type"],
                         "editorial_signal_not_profitability")

    def test_brand_fit_uses_weighted_profile_terms_and_explicit_exclusions(self):
        now = datetime(2026, 11, 15, tzinfo=timezone.utc)
        brands = [
            {"slug": "future", "name": "Future Leak", "active": True,
             "config": {"vertical": "ai_future_technology",
                        "positioning": "AI technology explainers",
                        "keywords": ["machine learning", "robotics"],
                        "exclude_keywords": ["cryptocurrency"],
                        "regions": ["US"]}},
            {"slug": "money", "name": "Money Glitch", "active": True,
             "config": {"vertical": "economics_finance",
                        "positioning": "financial literacy and markets",
                        "regions": ["US"]}},
        ]
        trends = [
            {"id": "ai", "title": "AI technology and robotics", "region": "US",
             "published_at": now.isoformat()},
            {"id": "excluded", "title": "AI technology cryptocurrency", "region": "US",
             "published_at": now.isoformat()},
        ]
        ranked = rank_trend_candidates(trends, brands, now=now)
        ai = next(item for item in ranked if item["trend"]["id"] == "ai")
        self.assertEqual(ai["best_brand"]["brand"], "future")
        self.assertEqual(ai["best_brand"]["match_method"], "weighted_profile_term_coverage")
        self.assertIn("ai", ai["best_brand"]["matched_terms"])
        excluded = next(item for item in ranked if item["trend"]["id"] == "excluded")
        self.assertNotIn("future", [item["brand"] for item in excluded["brand_candidates"]])

    def test_historical_performance_is_exposed_but_does_not_change_recommendation_score(self):
        now = datetime(2026, 11, 15, tzinfo=timezone.utc)
        trend = {"id": "ai", "title": "AI technology explained", "region": "US",
                 "published_at": now.isoformat()}
        brand = {"slug": "future-leak", "name": "Future Leak", "active": True,
                 "config": {"positioning": "AI technology", "regions": ["US"]}}
        baseline = rank_trend_candidates(
            [trend], [brand], now=now
        )[0]
        enriched = rank_trend_candidates(
            [trend], [brand], now=now,
            performance_by_brand={"Future Leak": {
                "measured_videos": 5, "rate_sample_count": 4,
                "median_views_per_hour": 125.5,
                "interaction_rate_sample_count": 3,
                "median_interactions_per_1000_view_delta": 18.2
            }}
        )[0]
        historical = enriched["best_brand"]["historical_performance"]
        self.assertEqual(enriched["recommendation_score"], baseline["recommendation_score"])
        self.assertEqual(historical["evidence_status"], "observed")
        self.assertEqual(historical["median_views_per_hour"], 125.5)
        self.assertEqual(historical["ranking_score_adjustment"], 0)
        self.assertIn("not yet topic-matched", historical["reason"])

    def test_topic_matched_performance_uses_only_measured_same_region_videos(self):
        now = datetime(2026, 11, 15, tzinfo=timezone.utc)
        trend = {"id": "ai", "title": "AI robotics explained", "region": "US",
                 "published_at": now.isoformat()}
        brand = {"slug": "future-leak", "name": "Future Leak", "active": True,
                 "config": {"positioning": "AI robotics technology", "regions": ["US"]}}
        videos = [
            {"brand": "Future Leak", "region": "US", "topic": "AI robotics",
             "measurement_status": "measured", "views_per_hour": 100.0,
             "interactions_per_1000_view_delta": 20.0},
            {"brand": "Future Leak", "region": "US", "topic": "AI robotics research",
             "measurement_status": "measured", "views_per_hour": 200.0,
             "interactions_per_1000_view_delta": 30.0},
            {"brand": "Future Leak", "region": "US", "topic": "AI robotics future",
             "measurement_status": "measured", "views_per_hour": 300.0,
             "interactions_per_1000_view_delta": 40.0},
            {"brand": "Future Leak", "region": "JP", "topic": "AI robotics",
             "measurement_status": "measured", "views_per_hour": 999.0,
             "interactions_per_1000_view_delta": 99.0},
            {"brand": "Future Leak", "region": "US", "topic": "Cooking recipes",
             "measurement_status": "measured", "views_per_hour": 888.0,
             "interactions_per_1000_view_delta": 88.0},
        ]
        result = rank_trend_candidates(
            [trend], [brand], now=now, performance_videos=videos
        )[0]
        context = result["best_brand"]["topic_performance"]
        self.assertEqual(context["matched_video_count"], 3)
        self.assertEqual(context["median_views_per_hour"], 200.0)
        self.assertEqual(context["median_interactions_per_1000_view_delta"], 30.0)
        self.assertEqual(context["evidence_status"], "observed")
        self.assertEqual(context["ranking_score_adjustment"], 0)


    def test_topic_matched_analytics_only_videos_supply_watch_quality_context(self):
        now = datetime(2026, 11, 15, tzinfo=timezone.utc)
        trend = {"id": "ai", "title": "AI robotics explained", "region": "US",
                 "published_at": now.isoformat()}
        brand = {"slug": "future-leak", "name": "Future Leak", "active": True,
                 "config": {"positioning": "AI robotics technology", "regions": ["US"]}}
        videos = [
            {
                "brand": "Future Leak", "region": "US",
                "topic": "AI robotics explained for beginners",
                "measurement_status": "insufficient_snapshots",
                "views_per_hour": None,
                "engaged_view_share": retention,
                "average_view_percentage": percentage,
                "average_view_duration_seconds": duration,
                "audience_retention_curve": [
                    {"elapsed_video_time_ratio": 0.25, "audience_watch_ratio": retention},
                    {"elapsed_video_time_ratio": 0.50, "audience_watch_ratio": retention - 0.1},
                    {"elapsed_video_time_ratio": 0.75, "audience_watch_ratio": retention - 0.2},
                ],
            }
            for percentage, duration, retention in (
                (80.0, 18.0, 0.8), (70.0, 16.0, 0.7), (60.0, 14.0, 0.6)
            )
        ]
        baseline = rank_trend_candidates([trend], [brand], now=now)[0]
        result = rank_trend_candidates(
            [trend], [brand], now=now, performance_videos=videos
        )[0]
        context = result["best_brand"]["topic_performance"]
        self.assertEqual(context["matched_video_count"], 3)
        self.assertEqual(context["view_velocity_sample_count"], 0)
        self.assertEqual(context["engaged_view_share_sample_count"], 3)
        self.assertEqual(context["median_engaged_view_share"], 0.7)
        self.assertEqual(context["average_view_percentage_sample_count"], 3)
        self.assertEqual(context["median_average_view_percentage"], 70.0)
        self.assertEqual(context["median_average_view_duration_seconds"], 16.0)
        self.assertEqual(
            context["audience_retention_samples"]["audience_watch_ratio_50"]["median_audience_watch_ratio"],
            0.6,
        )
        self.assertEqual(result["recommendation_score"], baseline["recommendation_score"])
        self.assertEqual(context["ranking_score_adjustment"], 0)

    def test_topic_performance_rejects_boolean_nonfinite_and_out_of_range_metrics(self):
        now = datetime(2026, 11, 15, tzinfo=timezone.utc)
        trend = {"id": "ai", "title": "AI robotics explained", "region": "US",
                 "published_at": now.isoformat()}
        brand = {"slug": "future-leak", "name": "Future Leak", "active": True,
                 "config": {"positioning": "AI robotics technology", "regions": ["US"]}}
        videos = [
            {
                "brand": "Future Leak", "region": "US", "topic": "AI robotics explained",
                "views_per_hour": True, "engaged_view_share": False,
                "average_view_percentage": float("nan"),
                "average_view_duration_seconds": float("inf"),
                "interactions_per_1000_view_delta": True,
                "audience_retention_curve": [
                    {"elapsed_video_time_ratio": True, "audience_watch_ratio": 0.8},
                    {"elapsed_video_time_ratio": 0.5, "audience_watch_ratio": 1.2},
                ],
            },
            {
                "brand": "Future Leak", "region": "US", "topic": "AI robotics explained",
                "average_view_percentage": 125.0,
                "audience_retention_curve": [
                    {"elapsed_video_time_ratio": 0.5, "audience_watch_ratio": 0.7},
                ],
            },
        ]
        result = rank_trend_candidates(
            [trend], [brand], now=now, performance_videos=videos
        )[0]
        context = result["best_brand"]["topic_performance"]
        self.assertEqual(context["matched_video_count"], 1)
        self.assertEqual(context["view_velocity_sample_count"], 0)
        self.assertEqual(context["engaged_view_share_sample_count"], 0)
        self.assertEqual(context["average_view_percentage_sample_count"], 1)
        self.assertEqual(context["median_average_view_percentage"], 125.0)
        self.assertEqual(
            context["audience_retention_samples"]["audience_watch_ratio_50"]["median_audience_watch_ratio"],
            0.7,
        )
        self.assertEqual(context["interaction_rate_sample_count"], 0)

    def test_comparable_cohorts_are_brand_region_topic_scoped_and_display_only(self):
        now = datetime(2026, 11, 15, tzinfo=timezone.utc)
        trend = {"id": "ai", "title": "AI robotics explained", "region": "US",
                 "published_at": now.isoformat()}
        brand = {"slug": "future-leak", "name": "Future Leak", "active": True,
                 "config": {"positioning": "AI robotics technology", "regions": ["US"]}}
        cohorts = [
            {"brand": "Future Leak", "region": "US",
             "publication_age_bucket": "under_24h", "duration_bucket": "20_40s",
             "format": "vertical_short", "topic_signature": "ai explained robotics",
             "sample_count": 4, "median_views_per_hour": 150.0,
             "interaction_rate_sample_count": 3,
             "median_interactions_per_1000_view_delta": 22.0,
             "evidence_status": "observed"},
            {"brand": "Future Leak", "region": "JP",
             "publication_age_bucket": "under_24h", "duration_bucket": "20_40s",
             "format": "vertical_short", "topic_signature": "ai explained robotics",
             "sample_count": 10, "median_views_per_hour": 900.0,
             "evidence_status": "observed"},
            {"brand": "Money Glitch", "region": "US",
             "publication_age_bucket": "under_24h", "duration_bucket": "20_40s",
             "format": "vertical_short", "topic_signature": "ai explained robotics",
             "sample_count": 20, "median_views_per_hour": 999.0,
             "evidence_status": "observed"},
            {"brand": "Future Leak", "region": "US",
             "publication_age_bucket": "under_24h", "duration_bucket": "20_40s",
             "format": "vertical_short", "topic_signature": "cooking recipes",
             "sample_count": 20, "median_views_per_hour": 888.0,
             "evidence_status": "observed"},
        ]
        baseline = rank_trend_candidates([trend], [brand], now=now)[0]
        enriched = rank_trend_candidates(
            [trend], [brand], now=now, performance_cohorts=cohorts
        )[0]
        context = enriched["best_brand"]["comparable_cohort_performance"]
        self.assertEqual(enriched["recommendation_score"], baseline["recommendation_score"])
        self.assertEqual(context["matched_cohort_count"], 1)
        self.assertEqual(context["cohorts"][0]["sample_count"], 4)
        self.assertEqual(context["cohorts"][0]["median_views_per_hour"], 150.0)
        self.assertEqual(context["ranking_score_adjustment"], 0)

    def test_comparable_cohort_evidence_rejects_malformed_counts_and_metrics(self):
        now = datetime(2026, 11, 15, tzinfo=timezone.utc)
        trend = {"id": "ai", "title": "AI robotics explained", "region": "US",
                 "published_at": now.isoformat()}
        brand = {"slug": "future-leak", "name": "Future Leak", "active": True,
                 "config": {"positioning": "AI robotics technology", "regions": ["US"]}}
        cohorts = [
            {"brand": "Future Leak", "region": "US", "format": "vertical_short",
             "topic_signature": "AI robotics explained", "sample_count": True,
             "median_views_per_hour": float("nan"),
             "interaction_rate_sample_count": "3",
             "median_interactions_per_1000_view_delta": float("inf"),
             "evidence_status": "observed"},
            {"brand": "Future Leak", "region": "US", "format": "vertical_short",
             "topic_signature": "AI robotics explained", "sample_count": 4,
             "median_views_per_hour": 125.5,
             "interaction_rate_sample_count": 3,
             "median_interactions_per_1000_view_delta": 18.25,
             "evidence_status": "no_data"},
            None,
            {"brand": "Future Leak", "region": "US", "format": "vertical_short",
             "topic_signature": "AI robotics explained", "sample_count": -2,
             "median_views_per_hour": -1,
             "interaction_rate_sample_count": False,
             "median_interactions_per_1000_view_delta": "invalid"},
        ]
        baseline = rank_trend_candidates([trend], [brand], now=now)[0]
        result = rank_trend_candidates(
            [trend], [brand], now=now, performance_cohorts=cohorts
        )[0]
        context = result["best_brand"]["comparable_cohort_performance"]
        self.assertEqual(result["recommendation_score"], baseline["recommendation_score"])
        self.assertEqual(context["matched_cohort_count"], 3)
        by_count = {item["sample_count"]: item for item in context["cohorts"]}
        self.assertEqual(by_count[0]["evidence_status"], "no_data")
        self.assertIsNone(by_count[0]["median_views_per_hour"])
        self.assertEqual(by_count[0]["interaction_rate_sample_count"], 0)
        self.assertIsNone(by_count[0]["median_interactions_per_1000_view_delta"])
        self.assertEqual(by_count[4]["evidence_status"], "observed")
        self.assertEqual(by_count[4]["median_views_per_hour"], 125.5)
        self.assertEqual(by_count[4]["median_interactions_per_1000_view_delta"], 18.25)
        self.assertEqual(context["ranking_score_adjustment"], 0)

    def test_competitor_evidence_is_region_scoped_and_does_not_change_editorial_score(self):
        store = Mock()
        store.list_channels.return_value = [
            *[{"channel_id": f"jp-channel-{index}", "country": "JP"} for index in range(12)],
            {"channel_id": "us-channel", "country": "US"},
        ]
        store.list_videos.side_effect = lambda channel_id, limit: [
            {"channel_id": channel_id, "title": "AI technology explained",
             "view_count": True, "published_at": "2026-11-14T00:00:00+00:00"},
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
        self.assertEqual(result["recommendation_score"],
                         round(sum(result["score_breakdown"].values()), 2))
        self.assertNotIn("competitor_video_sample_unavailable", result["evidence_gaps"])
        store.list_channels.assert_called_once_with(limit=200)
        store.list_videos.assert_called_once_with("us-channel", limit=30)


    def test_trends_remain_rankable_when_no_brands_are_active(self):
        now = datetime(2026, 11, 15, tzinfo=timezone.utc)
        trends = [{
            "id": "standalone-trend",
            "title": "AI technology explained",
            "region": "US",
            "published_at": now.isoformat(),
            "source": "google_news_rss",
            "url": "https://news.example/standalone",
        }]
        for brands in ([], [{
            "slug": "inactive-brand", "name": "Inactive Brand", "active": False,
            "config": {"positioning": "AI technology", "regions": ["US"]},
        }]):
            with self.subTest(brands=brands):
                ranked = rank_trend_candidates(trends, brands, now=now)
                self.assertEqual(len(ranked), 1)
                self.assertEqual(ranked[0]["trend"]["id"], "standalone-trend")
                self.assertIsNone(ranked[0]["best_brand"])
                self.assertEqual(ranked[0]["brand_candidates"], [])
                self.assertEqual(ranked[0]["score_breakdown"]["brand_fit"], 0)


    def test_malformed_trend_batch_entries_are_isolated(self):
        now = datetime(2026, 11, 15, tzinfo=timezone.utc)
        valid = {
            "id": "valid-after-invalid",
            "title": "AI technology explained",
            "region": "US",
            "published_at": now.isoformat(),
            "source": "google_news_rss",
            "url": "https://news.example/valid",
        }
        ranked = rank_trend_candidates(
            [None, "invalid", 42, [], {"title": None}, valid],
            [None, "invalid", {"name": "AI Brand", "active": True,
                               "config": {"positioning": "AI technology",
                                          "regions": ["US"]}}],
            now=now,
        )
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["trend"]["id"], "valid-after-invalid")

    def test_non_list_trend_and_brand_batches_fail_closed_to_empty(self):
        self.assertEqual(rank_trend_candidates(None, [], now=datetime.now(timezone.utc)), [])
        self.assertEqual(rank_trend_candidates("not-a-list", {}, now=datetime.now(timezone.utc)), [])


    def test_malformed_brand_profile_config_is_isolated(self):
        now = datetime(2026, 11, 15, tzinfo=timezone.utc)
        trend = {
            "id": "brand-profile-safe",
            "title": "AI technology explained",
            "region": "US",
            "published_at": now.isoformat(),
            "source": "google_news_rss",
            "url": "https://news.example/brand-profile",
        }
        brands = [
            {"slug": "bad-config", "name": "Bad Config", "active": True,
             "config": "not-a-dictionary"},
            {"slug": "numeric-config", "name": 42, "active": True,
             "config": {"positioning": 17, "vertical": None, "audience": ["bad"]}},
            {"slug": "good-config", "name": "AI Brand", "active": True,
             "config": {"positioning": "AI technology", "regions": ["US"]}},
        ]
        ranked = rank_trend_candidates([trend], brands, now=now)
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["best_brand"]["brand"], "good-config")


    def test_malformed_historical_performance_aggregates_are_display_safe(self):
        now = datetime(2026, 11, 15, tzinfo=timezone.utc)
        trend = {
            "id": "aggregate-safe", "title": "AI technology explained",
            "region": "US", "published_at": now.isoformat(),
        }
        brand = {
            "slug": "future-leak", "name": "Future Leak", "active": True,
            "config": {"positioning": "AI technology", "regions": ["US"]},
        }
        baseline = rank_trend_candidates([trend], [brand], now=now)[0]
        for aggregate in (None, "invalid", {
            "measured_videos": "five",
            "rate_sample_count": True,
            "interaction_rate_sample_count": -2,
            "median_views_per_hour": 125.5,
        }):
            with self.subTest(aggregate=aggregate):
                result = rank_trend_candidates(
                    [trend], [brand], now=now,
                    performance_by_brand={"Future Leak": aggregate},
                )[0]
                historical = result["best_brand"]["historical_performance"]
                self.assertEqual(historical["measured_videos"], 0)
                self.assertEqual(historical["rate_sample_count"], 0)
                self.assertEqual(historical["interaction_rate_sample_count"], 0)
                self.assertEqual(historical["evidence_status"], "no_data")
                self.assertEqual(result["recommendation_score"], baseline["recommendation_score"])

        for invalid_container in ("not-a-dictionary", None, []):
            with self.subTest(performance_by_brand=invalid_container):
                safe = rank_trend_candidates(
                    [trend], [brand], now=now,
                    performance_by_brand=invalid_container,
                )
                self.assertEqual(len(safe), 1)
                self.assertEqual(
                    safe[0]["best_brand"]["historical_performance"]["evidence_status"],
                    "no_data",
                )


if __name__ == "__main__":
    unittest.main()
