import os
import sqlite3
import tempfile
import unittest
from datetime import date

from youtube_analytics import YouTubeAnalyticsCollector, YouTubeAnalyticsStore


class FakeRequest:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return self.result


class FakeReports:
    def __init__(self, metrics=None, retention=None, retention_error=None):
        self.metrics = metrics if metrics is not None else {
            "columnHeaders": [{"name": name} for name in (
                "views", "engagedViews", "estimatedMinutesWatched",
                "averageViewDuration", "averageViewPercentage",
            )],
            "rows": [],
        }
        self.retention = retention if retention is not None else {
            "columnHeaders": [{"name": name} for name in (
                "elapsedVideoTimeRatio", "audienceWatchRatio",
                "relativeRetentionPerformance",
            )],
            "rows": [],
        }
        self.retention_error = retention_error
        self.calls = []

    def query(self, **kwargs):
        self.calls.append(kwargs)
        if "dimensions" not in kwargs:
            return FakeRequest(self.metrics)
        if self.retention_error:
            raise self.retention_error
        return FakeRequest(self.retention)


class FakeService:
    def __init__(self, reports):
        self._reports = reports

    def reports(self):
        return self._reports


class YouTubeAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "nexus.sqlite3")
        self.store = YouTubeAnalyticsStore(self.db)

    def tearDown(self):
        self.tmp.cleanup()


    def test_metrics_parser_rejects_malformed_headers_and_rows(self):
        invalid_responses = [
            {"columnHeaders": [{"name": []}], "rows": []},
            {"columnHeaders": [{"name": "views"}] * 2, "rows": []},
            {"columnHeaders": [{"name": "views"}], "rows": []},
            {"columnHeaders": [
                {"name": name} for name in (
                    "views", "engagedViews", "estimatedMinutesWatched",
                    "averageViewDuration", "averageViewPercentage",
                )
            ], "rows": [[1, 2]]},
        ]
        for response in invalid_responses:
            with self.subTest(response=response):
                with self.assertRaises(RuntimeError):
                    YouTubeAnalyticsCollector._row_map(response)

    def test_metrics_parser_rejects_boolean_nonfinite_and_negative_values(self):
        headers = [{"name": name} for name in (
            "views", "engagedViews", "estimatedMinutesWatched",
            "averageViewDuration", "averageViewPercentage",
        )]
        for invalid in (True, float("nan"), float("inf"), -1):
            with self.subTest(value=invalid):
                with self.assertRaises(RuntimeError):
                    YouTubeAnalyticsCollector._row_map({
                        "columnHeaders": headers,
                        "rows": [[1, invalid, 3, 4, 5]],
                    })

    def test_metrics_parser_checks_returned_video_id_when_present(self):
        headers = [{"name": name} for name in (
            "video", "views", "engagedViews", "estimatedMinutesWatched",
            "averageViewDuration", "averageViewPercentage",
        )]
        with self.assertRaisesRegex(RuntimeError, "unexpected video ID"):
            YouTubeAnalyticsCollector._row_map({
                "columnHeaders": headers,
                "rows": [["different-video", 1, 1, 1.0, 1.0, 100.0]],
            }, expected_video_id="requested-video")

    def test_metrics_parser_rejects_more_than_one_row(self):
        headers = [{"name": name} for name in (
            "views", "engagedViews", "estimatedMinutesWatched",
            "averageViewDuration", "averageViewPercentage",
        )]
        with self.assertRaisesRegex(RuntimeError, "single-video row limit"):
            YouTubeAnalyticsCollector._row_map({
                "columnHeaders": headers,
                "rows": [[1, 2, 3, 4, 5], [1, 2, 3, 4, 5]],
            })

    def test_retention_parser_rejects_out_of_range_and_oversized_responses(self):
        headers = [{"name": name} for name in (
            "elapsedVideoTimeRatio", "audienceWatchRatio",
            "relativeRetentionPerformance",
        )]
        for row in ((1.2, 0.5, 0.2), (0.5, 1.2, 0.2), (0.5, True, 0.2)):
            with self.subTest(row=row):
                with self.assertRaises(RuntimeError):
                    YouTubeAnalyticsCollector._parse_retention_response({
                        "columnHeaders": headers, "rows": [list(row)],
                    })
        with self.assertRaisesRegex(RuntimeError, "200-row limit"):
            YouTubeAnalyticsCollector._parse_retention_response({
                "columnHeaders": headers,
                "rows": [[0.5, 0.5, 0.1]] * 201,
            })

    def test_collects_watch_time_and_retention_using_header_names(self):
        reports = FakeReports(
            metrics={
                "columnHeaders": [
                    {"name": "video"}, {"name": "views"}, {"name": "engagedViews"},
                    {"name": "estimatedMinutesWatched"},
                    {"name": "averageViewDuration"}, {"name": "averageViewPercentage"},
                ],
                "rows": [["video-1", 1000, 620, 250.5, 15.03, 72.4]],
            },
            retention={
                "columnHeaders": [
                    {"name": "elapsedVideoTimeRatio"},
                    {"name": "audienceWatchRatio"},
                    {"name": "relativeRetentionPerformance"},
                ],
                "rows": [[0.5, 0.42, 1.1], [0.01, 1.0, 0.8], [1.0, 0.1, 0.7]],
            },
        )
        collector = YouTubeAnalyticsCollector(
            self.store, service=FakeService(reports),
            today=lambda: date(2026, 11, 16),
        )
        result = collector.collect_video("video-1", "2026-11-01", "2026-11-14")

        self.assertEqual(result["analytics_status"], "available")
        self.assertEqual(result["retention_status"], "available")
        self.assertEqual(result["metrics"]["average_view_duration_seconds"], 15.03)
        self.assertEqual(result["metrics"]["average_view_percentage"], 72.4)
        self.assertEqual(result["retention_points"], 3)
        saved = self.store.get("video-1")
        self.assertEqual(saved["views"], 1000)
        self.assertEqual(saved["engaged_views"], 620)
        self.assertEqual(saved["engaged_view_share"], 0.62)
        self.assertEqual(saved["retention_curve"][0]["elapsed_video_time_ratio"], 0.01)
        self.assertEqual(saved["retention_curve"][1]["audience_watch_ratio"], 0.42)
        self.assertEqual(reports.calls[0]["ids"], "channel==MINE")
        self.assertEqual(reports.calls[0]["filters"], "video==video-1")
        self.assertNotIn("dimensions", reports.calls[0])
        self.assertEqual(reports.calls[0]["metrics"],
                         "views,engagedViews,estimatedMinutesWatched,averageViewDuration,averageViewPercentage")

    def test_retention_permission_error_does_not_discard_watch_time_metrics(self):
        reports = FakeReports(
            metrics={
                "columnHeaders": [{"name": name} for name in (
                    "views", "engagedViews", "estimatedMinutesWatched",
                    "averageViewDuration", "averageViewPercentage",
                )],
                "rows": [[25, 20, 4.5, 9.5, 50.0]],
            },
            retention_error=PermissionError("not eligible"),
        )
        collector = YouTubeAnalyticsCollector(self.store, service=FakeService(reports))
        result = collector.collect_video("video-2", "2026-11-01", "2026-11-14")
        self.assertEqual(result["analytics_status"], "available")
        self.assertEqual(result["retention_status"], "unavailable")
        saved = self.store.get("video-2")
        self.assertEqual(saved["average_view_duration"], 9.5)
        self.assertEqual(saved["retention_error"], "PermissionError")
        self.assertEqual(saved["retention_curve"], [])

    def test_no_data_is_not_reported_as_live_metrics(self):
        reports = FakeReports()
        collector = YouTubeAnalyticsCollector(self.store, service=FakeService(reports))
        result = collector.collect_video("video-3", "2026-11-01", "2026-11-14")
        self.assertEqual(result["analytics_status"], "no_data")
        self.assertEqual(result["retention_status"], "no_data")
        self.assertFalse(self.store.get("video-3")["views"])



    def test_existing_analytics_table_is_migrated_for_engaged_view_columns(self):
        legacy_db = os.path.join(self.tmp.name, "legacy.sqlite3")
        with sqlite3.connect(legacy_db) as connection:
            connection.execute("""
                CREATE TABLE youtube_analytics_snapshots(
                  video_id TEXT PRIMARY KEY,start_date TEXT NOT NULL,end_date TEXT NOT NULL,
                  views REAL,estimated_minutes_watched REAL,average_view_duration REAL,
                  average_view_percentage REAL,retention_json TEXT NOT NULL DEFAULT '[]',
                  analytics_status TEXT NOT NULL,retention_status TEXT NOT NULL,
                  retention_error TEXT,collected_at TEXT NOT NULL
                )
            """)
        migrated = YouTubeAnalyticsStore(legacy_db)
        with migrated.db() as connection:
            columns = {
                row["name"] for row in connection.execute(
                    "PRAGMA table_info(youtube_analytics_snapshots)"
                ).fetchall()
            }
        self.assertIn("engaged_views", columns)
        self.assertIn("engaged_view_share", columns)
        migrated.save("migrated-video", "2026-11-01", "2026-11-14", {
            "views": 100, "engagedViews": 45,
        }, [])
        self.assertEqual(migrated.get("migrated-video")["engaged_view_share"], 0.45)

    def test_recent_upload_is_pending_not_a_zero_metrics_report(self):
        from youtube_publishing import YouTubeUploadStore
        uploads = YouTubeUploadStore(self.db)
        with uploads.db() as connection:
            connection.execute(
                "INSERT INTO youtube_uploads(job_id,video_id,status,title,description,uploaded_at,updated_at) "
                "VALUES('recent-job','recent-video','uploaded','title','','2026-11-15T12:00:00+00:00','2026-11-15T12:00:00+00:00')"
            )
        reports = FakeReports()
        collector = YouTubeAnalyticsCollector(
            self.store, service=FakeService(reports),
            today=lambda: date(2026, 11, 16),
        )
        result = collector.collect_video("recent-video")
        self.assertEqual(result["analytics_status"], "pending_availability")
        self.assertFalse(result["live_connectivity_verified"])
        self.assertEqual(reports.calls, [])
        self.assertIsNone(self.store.get("recent-video")["views"])

    def test_relative_retention_performance_preserves_negative_values(self):
        reports = FakeReports(retention={
            "columnHeaders": [
                {"name": "elapsedVideoTimeRatio"},
                {"name": "audienceWatchRatio"},
                {"name": "relativeRetentionPerformance"},
            ],
            "rows": [[0.5, 0.2, -0.35]],
        })
        collector = YouTubeAnalyticsCollector(self.store, service=FakeService(reports))
        collector.collect_video("negative-retention", "2026-11-01", "2026-11-14")
        saved = self.store.get("negative-retention")
        self.assertEqual(
            saved["retention_curve"][0]["relative_retention_performance"], -0.35
        )

    def test_rejects_invalid_video_ids_and_date_ranges(self):
        collector = YouTubeAnalyticsCollector(self.store, service=FakeService(FakeReports()))
        with self.assertRaises(ValueError):
            collector.collect_video("", "2026-11-01", "2026-11-14")
        with self.assertRaises(ValueError):
            collector.collect_video("video-4", "2026-11-15", "2026-11-14")

    def test_due_collection_is_limited_to_uploaded_video_ids(self):
        from youtube_publishing import YouTubeUploadStore
        uploads = YouTubeUploadStore(self.db)
        # Insert only the minimal upload rows needed to exercise the due selector.
        with uploads.db() as connection:
            connection.execute(
                "INSERT INTO youtube_uploads(job_id,video_id,status,title,description,updated_at) "
                "VALUES('job-1','video-1','uploaded','title','','2026-11-10')"
            )
            connection.execute(
                "INSERT INTO youtube_uploads(job_id,video_id,status,title,description,updated_at) "
                "VALUES('job-2','video-2','pending','title','','2026-11-10')"
            )
        self.assertEqual(self.store.due_video_ids(limit=10, min_age_seconds=86400), ["video-1"])
        self.store.save("video-1", "2026-11-01", "2026-11-14", {}, [])
        self.assertEqual(self.store.due_video_ids(limit=10, min_age_seconds=86400), [])


    def test_lease_renewal_extends_only_the_live_owner_token(self):
        token = self.store.acquire_lease("worker-a", 300, now=1000)
        self.assertTrue(token)
        self.assertTrue(self.store.renew_lease("worker-a", token, 600, now=1001))
        self.assertIsNone(self.store.acquire_lease("worker-b", 300, now=1002))
        self.assertTrue(self.store.release_lease("worker-a", token))
        replacement = self.store.acquire_lease("worker-b", 300, now=1002)
        self.assertTrue(replacement)
        self.assertFalse(self.store.renew_lease("worker-a", token, 600, now=1003))

    def test_expired_lease_cannot_be_resurrected_by_old_owner(self):
        token = self.store.acquire_lease("worker-a", 300, now=1000)
        self.assertTrue(token)
        with self.store.db() as connection:
            connection.execute(
                "UPDATE youtube_analytics_collector_lease SET lease_until=0 WHERE id=1"
            )
        self.assertFalse(self.store.renew_lease("worker-a", token, 300, now=1001))
        replacement = self.store.acquire_lease("worker-b", 300, now=1001)
        self.assertTrue(replacement)
        self.assertFalse(self.store.release_lease("worker-a", token))

    def test_analytics_snapshot_and_collection_state_reject_replaced_lease_token(self):
        token = self.store.acquire_lease("worker-a", 300)
        with self.store.db() as connection:
            connection.execute(
                "UPDATE youtube_analytics_collector_lease SET token='replacement' WHERE id=1"
            )
        with self.assertRaisesRegex(RuntimeError, "stale write rejected"):
            self.store.save(
                "video-stale", "2026-11-01", "2026-11-14", {"views": 1}, [],
                lease_owner="worker-a", lease_token=token,
            )
        with self.assertRaisesRegex(RuntimeError, "stale write rejected"):
            self.store.record_collection(
                "succeeded", requested=1, collected=1,
                lease_owner="worker-a", lease_token=token,
            )
        self.assertIsNone(self.store.get("video-stale"))


    def test_collection_state_reports_batch_health_and_video_coverage(self):
        from youtube_publishing import YouTubeUploadStore
        uploads = YouTubeUploadStore(self.db)
        with uploads.db() as connection:
            for job_id, video_id in (
                ("job-a", "video-a"), ("job-b", "video-b"), ("job-c", "video-c")
            ):
                connection.execute(
                    "INSERT INTO youtube_uploads(job_id,video_id,status,title,description,updated_at) "
                    "VALUES(?,?,'uploaded','title','','2026-11-14')",
                    (job_id, video_id),
                )
        self.store.save("video-a", "2026-11-01", "2026-11-14", {
            "views": 100, "averageViewDuration": 12.5,
        }, [])
        self.store.save("video-b", "2026-11-01", "2026-11-14", {
            "views": 200, "averageViewPercentage": 60,
        }, [])
        self.store.record_collection(
            "partial", requested=3, collected=2, failed=1,
            error="1 video collection(s) failed",
        )

        status = self.store.status(freshness_seconds=86400)
        self.assertEqual(status["platform"], "youtube")
        self.assertEqual(status["status"], "partial")
        self.assertEqual(status["last_batch"], {
            "requested": 3, "collected": 2, "failed": 1,
        })
        self.assertEqual(status["coverage"], {
            "published_videos": 3,
            "with_snapshot": 2,
            "without_snapshot": 1,
            "stale_or_missing": 1,
        })
        self.assertIsNotNone(status["last_attempt_at"])
        self.assertIsNotNone(status["last_success_at"])
        self.assertIsNotNone(status["latest_snapshot_at"])
        self.assertEqual(status["last_error"], "1 video collection(s) failed")

        self.store.record_collection("running")
        running = self.store.status()
        self.assertEqual(running["status"], "running")
        self.assertEqual(running["last_batch"], {
            "requested": 3, "collected": 2, "failed": 1,
        })
        self.assertEqual(running["last_error"], "1 video collection(s) failed")

        self.store.record_collection("succeeded", requested=0, collected=0)
        recovered = self.store.status()
        self.assertEqual(recovered["status"], "succeeded")
        self.assertIsNone(recovered["last_error"])

    def test_collection_state_rejects_unknown_status(self):
        with self.assertRaises(ValueError):
            self.store.record_collection("unknown")

    def test_collector_rechecks_lease_after_oauth_initialization_before_provider_call(self):
        token = self.store.acquire_lease("worker-old", 300)
        reports = FakeReports()

        class LeaseReplacingCollector(YouTubeAnalyticsCollector):
            def _service(inner_self):
                with inner_self.store.db() as connection:
                    connection.execute(
                        "UPDATE youtube_analytics_collector_lease SET token='replacement' WHERE id=1"
                    )
                return FakeService(reports)

        collector = LeaseReplacingCollector(self.store, today=lambda: date(2026, 11, 17))
        with self.assertRaisesRegex(RuntimeError, "lease lost; stale write rejected"):
            collector.collect_video(
                "video-stale", start_date="2026-11-01", end_date="2026-11-14",
                lease_owner="worker-old", lease_token=token,
            )
        self.assertEqual(reports.calls, [])

    def test_collector_stops_batch_after_lease_loss_instead_of_continuing(self):
        token = self.store.acquire_lease("worker-old", 300)
        reports = FakeReports()

        class LeaseReplacingCollector(YouTubeAnalyticsCollector):
            def _service(inner_self):
                with inner_self.store.db() as connection:
                    connection.execute(
                        "UPDATE youtube_analytics_collector_lease SET token='replacement' WHERE id=1"
                    )
                return FakeService(reports)

        self.store.due_video_ids = lambda limit, min_age_seconds: ["video-one", "video-two"]
        collector = LeaseReplacingCollector(self.store)
        with self.assertRaisesRegex(RuntimeError, "lease lost; stale write rejected"):
            collector.refresh_due_metrics(
                lease_owner="worker-old", lease_token=token,
            )
        self.assertEqual(reports.calls, [])

    def test_collector_rechecks_lease_before_retention_request(self):
        token = self.store.acquire_lease("worker-old", 300)
        reports = FakeReports()

        class ReplacingReports(FakeReports):
            def query(inner_self, **kwargs):
                result = super().query(**kwargs)
                if "dimensions" not in kwargs:
                    with self.store.db() as connection:
                        connection.execute(
                            "UPDATE youtube_analytics_collector_lease SET token='replacement' WHERE id=1"
                        )
                return result

        replacing_reports = ReplacingReports()
        collector = YouTubeAnalyticsCollector(
            self.store, service=FakeService(replacing_reports),
            today=lambda: date(2026, 11, 17),
        )
        with self.assertRaisesRegex(RuntimeError, "lease lost; stale write rejected"):
            collector.collect_video(
                "video-stale", start_date="2026-11-01", end_date="2026-11-14",
                lease_owner="worker-old", lease_token=token,
            )
        self.assertEqual(len(replacing_reports.calls), 1)

    def test_lease_prevents_overlapping_collectors(self):
        token = self.store.acquire_lease("worker-a", 300)
        self.assertTrue(token)
        self.assertIsNone(self.store.acquire_lease("worker-b", 300))
        self.store.release_lease("worker-a", token)
        self.assertTrue(self.store.acquire_lease("worker-b", 300))


    def test_save_rejects_boolean_metrics_and_out_of_range_retention_ratios(self):
        self.store.save(
            "numeric-boundary-video", "2026-11-01", "2026-11-14",
            {
                "views": True,
                "engagedViews": False,
                "estimatedMinutesWatched": True,
                "averageViewDuration": 12.5,
                "averageViewPercentage": 125.0,
            },
            [
                {"elapsedVideoTimeRatio": True, "audienceWatchRatio": 0.5},
                {"elapsedVideoTimeRatio": 0.5, "audienceWatchRatio": False},
                {"elapsedVideoTimeRatio": 1.01, "audienceWatchRatio": 0.5},
                {"elapsedVideoTimeRatio": 0.5, "audienceWatchRatio": 1.01},
                {"elapsedVideoTimeRatio": -0.01, "audienceWatchRatio": 0.5},
                {"elapsedVideoTimeRatio": 0.5, "audienceWatchRatio": -0.01},
                {"elapsedVideoTimeRatio": 0.0, "audienceWatchRatio": 1.0,
                 "relativeRetentionPerformance": True},
                {"elapsedVideoTimeRatio": 1.0, "audienceWatchRatio": 0.0,
                 "relativeRetentionPerformance": -0.25},
            ],
        )
        saved = self.store.get("numeric-boundary-video")
        self.assertIsNone(saved["views"])
        self.assertIsNone(saved["engaged_views"])
        self.assertIsNone(saved["engaged_view_share"])
        self.assertIsNone(saved["estimated_minutes_watched"])
        self.assertEqual(saved["average_view_duration"], 12.5)
        self.assertEqual(saved["average_view_percentage"], 125.0)
        self.assertEqual(len(saved["retention_curve"]), 2)
        self.assertEqual(
            saved["retention_curve"][0],
            {
                "elapsed_video_time_ratio": 0.0,
                "audience_watch_ratio": 1.0,
                "relative_retention_performance": None,
            },
        )
        self.assertEqual(
            saved["retention_curve"][1],
            {
                "elapsed_video_time_ratio": 1.0,
                "audience_watch_ratio": 0.0,
                "relative_retention_performance": -0.25,
            },
        )


if __name__ == "__main__":
    unittest.main()
