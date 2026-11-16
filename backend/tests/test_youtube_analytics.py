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
        self.metrics = metrics or {}
        self.retention = retention or {}
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
                "columnHeaders": [{"name": "views"}, {"name": "averageViewDuration"}],
                "rows": [[25, 9.5]],
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


    def test_lease_renewal_extends_only_the_live_owner_lease(self):
        self.assertEqual(self.store.acquire_lease("worker-a", 300), "worker-a")
        self.assertTrue(self.store.renew_lease("worker-a", 600))
        self.assertIsNone(self.store.acquire_lease("worker-b", 300))
        self.store.release_lease("worker-a")
        self.assertEqual(self.store.acquire_lease("worker-b", 300), "worker-b")
        self.assertFalse(self.store.renew_lease("worker-a", 600))

    def test_expired_lease_cannot_be_resurrected_by_old_owner(self):
        self.assertEqual(self.store.acquire_lease("worker-a", 300), "worker-a")
        with self.store.db() as connection:
            connection.execute(
                "UPDATE youtube_analytics_collector_lease SET lease_until=0 WHERE id=1"
            )
        self.assertFalse(self.store.renew_lease("worker-a", 300))
        self.assertEqual(self.store.acquire_lease("worker-b", 300), "worker-b")


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

    def test_lease_prevents_overlapping_collectors(self):
        self.assertEqual(self.store.acquire_lease("worker-a", 300), "worker-a")
        self.assertIsNone(self.store.acquire_lease("worker-b", 300))
        self.store.release_lease("worker-a")
        self.assertEqual(self.store.acquire_lease("worker-b", 300), "worker-b")


if __name__ == "__main__":
    unittest.main()
