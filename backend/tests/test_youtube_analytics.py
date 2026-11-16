import os
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
                    {"name": "video"}, {"name": "views"},
                    {"name": "estimatedMinutesWatched"},
                    {"name": "averageViewDuration"}, {"name": "averageViewPercentage"},
                ],
                "rows": [["video-1", 1000, 250.5, 15.03, 72.4]],
            },
            retention={
                "columnHeaders": [
                    {"name": "elapsedVideoTimeRatio"},
                    {"name": "audienceWatchRatio"},
                    {"name": "relativeRetentionPerformance"},
                ],
                "rows": [[0.01, 1.0, 0.8], [0.5, 0.42, 1.1], [1.0, 0.1, 0.7]],
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
        self.assertEqual(saved["retention_curve"][1]["audience_watch_ratio"], 0.42)
        self.assertEqual(reports.calls[0]["ids"], "channel==MINE")
        self.assertEqual(reports.calls[0]["filters"], "video==video-1")
        self.assertNotIn("dimensions", reports.calls[0])
        self.assertEqual(reports.calls[0]["metrics"],
                         "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage")

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

    def test_lease_prevents_overlapping_collectors(self):
        self.assertEqual(self.store.acquire_lease("worker-a", 300), "worker-a")
        self.assertIsNone(self.store.acquire_lease("worker-b", 300))
        self.store.release_lease("worker-a")
        self.assertEqual(self.store.acquire_lease("worker-b", 300), "worker-b")


if __name__ == "__main__":
    unittest.main()
