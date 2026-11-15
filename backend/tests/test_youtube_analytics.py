import tempfile
import unittest
from datetime import date
from pathlib import Path

from youtube_analytics import (
    YouTubeAnalyticsStore, YouTubeAnalyticsCollector, YouTubeAnalyticsError,
    METRICS, NUMERIC_FIELDS,
)


class FakeRequest:
    def __init__(self, response):
        self.response = response
    def execute(self):
        return self.response


class FakeReports:
    def __init__(self, response):
        self.response = response
        self.calls = []
    def query(self, **kwargs):
        self.calls.append(kwargs)
        return FakeRequest(self.response)


class FakeAnalyticsService:
    def __init__(self, response):
        self._reports = FakeReports(response)
    def reports(self):
        return self._reports


class FakeUploads:
    def __init__(self, records=None):
        self.records = records or []
    def list_recent(self, limit=100):
        return self.records[:limit]


class YouTubeAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "analytics.sqlite3")
        self.store = YouTubeAnalyticsStore(self.db)
        self.uploads = FakeUploads([
            {"job_id": "job-1", "video_id": "video-1", "status": "uploaded"},
            {"job_id": "job-2", "video_id": "video-2", "status": "uploaded"},
            {"job_id": "job-3", "video_id": "not-uploaded", "status": "uploading"},
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def response(self, video_ids):
        headers = [{"name": "video"}] + [{"name": key} for key in NUMERIC_FIELDS]
        rows = []
        for index, video_id in enumerate(video_ids):
            rows.append([video_id] + [index + 1 for _ in NUMERIC_FIELDS])
        return {"columnHeaders": headers, "rows": rows}

    def test_collector_queries_only_confirmed_uploaded_video_ids(self):
        service = FakeAnalyticsService(self.response(["video-1", "video-2"]))
        collector = YouTubeAnalyticsCollector(
            self.store, self.uploads, service_factory=lambda: service
        )
        result = collector.refresh(limit=50, days=28)
        self.assertEqual(result["requested"], 2)
        self.assertEqual(result["collected"], 2)
        self.assertEqual(result["missing"], [])
        self.assertEqual(service.reports().calls[0]["ids"], "channel==MINE")
        self.assertEqual(service.reports().calls[0]["metrics"], METRICS)
        self.assertEqual(service.reports().calls[0]["dimensions"], "video")
        self.assertEqual(service.reports().calls[0]["filters"], "video==video-1,video-2")
        self.assertEqual(result["end_date"], (date.today() - __import__("datetime").timedelta(days=2)).isoformat())

    def test_collector_records_missing_rows_without_fabricating_values(self):
        service = FakeAnalyticsService(self.response(["video-1"]))
        collector = YouTubeAnalyticsCollector(
            self.store, self.uploads, service_factory=lambda: service
        )
        result = collector.refresh()
        self.assertEqual(result["collected"], 1)
        self.assertEqual(result["missing"], ["video-2"])

    def test_collector_rejects_unrequested_or_duplicate_video_rows(self):
        service = FakeAnalyticsService(self.response(["foreign-video"]))
        collector = YouTubeAnalyticsCollector(
            self.store, self.uploads, service_factory=lambda: service
        )
        with self.assertRaisesRegex(YouTubeAnalyticsError, "unrequested video ID"):
            collector.refresh()
        duplicate = self.response(["video-1", "video-1"])
        with self.assertRaisesRegex(YouTubeAnalyticsError, "duplicate video rows"):
            YouTubeAnalyticsCollector._parse_response(duplicate, {"video-1"})

    def test_collector_rejects_malformed_response_and_non_numeric_metrics(self):
        with self.assertRaisesRegex(YouTubeAnalyticsError, "columns are invalid"):
            YouTubeAnalyticsCollector._parse_response(
                {"columnHeaders": [{"name": "video"}, {"name": "video"}], "rows": []},
                {"video-1"},
            )
        values = {key: 1 for key in NUMERIC_FIELDS}
        values["views"] = float("nan")
        with self.assertRaisesRegex(YouTubeAnalyticsError, "valid range"):
            self.store.save_snapshot("video-1", "2026-10-01", "2026-10-28", values)

    def test_recent_metrics_returns_latest_owned_uploaded_snapshot(self):
        values = {key: 1 for key in NUMERIC_FIELDS}
        self.store.save_snapshot("video-1", "2026-10-01", "2026-10-28", values)
        values["views"] = 22
        self.store.save_snapshot("video-1", "2026-10-02", "2026-10-29", values)
        values["views"] = 9
        self.store.save_snapshot("not-uploaded", "2026-10-01", "2026-10-28", values)
        rows = self.store.recent_metrics(self.uploads, limit=10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["video_id"], "video-1")
        self.assertEqual(rows[0]["views"], 22)

    def test_analytics_lease_is_exclusive_and_token_fenced(self):
        first = self.store.acquire_lease("worker-a", lease_seconds=300, now=1000)
        self.assertTrue(first)
        self.assertIsNone(self.store.acquire_lease("worker-b", lease_seconds=300, now=1100))
        replacement = self.store.acquire_lease("worker-a", lease_seconds=300, now=1400)
        self.assertTrue(replacement)
        self.store.release_lease("worker-a", first)
        self.assertIsNone(self.store.acquire_lease("worker-b", lease_seconds=300, now=1450))
        self.store.release_lease("worker-a", replacement)
        self.assertTrue(self.store.acquire_lease("worker-b", lease_seconds=300, now=1450))

    def test_collection_status_is_read_only_and_discloses_required_scope(self):
        status = self.store.status()
        self.assertEqual(status["platform"], "youtube_analytics")
        self.assertEqual(status["scope_required"],
                         "https://www.googleapis.com/auth/yt-analytics.readonly")
        self.assertTrue(status["read_only"])
        self.assertIn("averageViewPercentage", status["available_metrics"])
        self.assertFalse(status["fresh"])


if __name__ == "__main__":
    unittest.main()
