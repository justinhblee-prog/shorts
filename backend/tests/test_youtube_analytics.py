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
    def list_uploaded_video_ids(self, limit=10000):
        return [x for x in self.records if x.get("status") == "uploaded"][:limit]


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

    def test_parser_rejects_unhashable_or_invalid_header_names(self):
        for headers in ([{"name": []}], [{"name": None}], [{"name": "video"}, {"name": []}]):
            with self.subTest(headers=headers):
                with self.assertRaises(YouTubeAnalyticsError):
                    YouTubeAnalyticsCollector._parse_response(
                        {"columnHeaders": headers, "rows": []}, {"video-1"}
                    )

    def test_parser_rejects_unhashable_or_invalid_video_ids(self):
        for video_id in ([], {}, True, "", "x" * 257):
            with self.subTest(video_id_type=type(video_id).__name__):
                with self.assertRaises(YouTubeAnalyticsError):
                    YouTubeAnalyticsCollector._parse_response(
                        self.response([video_id]), {"video-1"}
                    )

    def test_parser_rejects_invalid_metric_types_before_any_snapshot_is_saved(self):
        headers = self.response([])["columnHeaders"]
        rows = self.response(["video-1", "video-2"])["rows"]
        rows[1][1] = True
        uploads = FakeUploads([
            {"job_id": "job-1", "video_id": "video-1", "status": "uploaded"},
            {"job_id": "job-2", "video_id": "video-2", "status": "uploaded"},
        ])
        service = FakeAnalyticsService({"columnHeaders": headers, "rows": rows})
        collector = YouTubeAnalyticsCollector(self.store, uploads, service_factory=lambda: service)
        with self.assertRaisesRegex(YouTubeAnalyticsError, "not numeric"):
            collector.refresh()
        with self.store.db() as connection:
            count = connection.execute("SELECT COUNT(*) FROM youtube_analytics_snapshots").fetchone()[0]
        self.assertEqual(count, 0)

    def test_parser_caps_response_rows(self):
        with self.assertRaisesRegex(YouTubeAnalyticsError, "200-row limit"):
            YouTubeAnalyticsCollector._parse_response(
                self.response(["video-1"] * 201), {"video-1"}
            )

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
        self.assertIsNone(self.store.acquire_lease("worker-a", lease_seconds=300, now=1100))
        replacement = self.store.acquire_lease("worker-a", lease_seconds=300, now=1400)
        self.assertTrue(replacement)
        self.store.release_lease("worker-a", first)
        self.assertIsNone(self.store.acquire_lease("worker-b", lease_seconds=300, now=1450))
        self.store.release_lease("worker-a", replacement)
        self.assertTrue(self.store.acquire_lease("worker-b", lease_seconds=300, now=1450))

    def test_analytics_lease_renews_only_for_current_unexpired_token(self):
        first = self.store.acquire_lease("worker-a", lease_seconds=300, now=1000)
        self.assertTrue(self.store.renew_lease("worker-a", first, 300, now=1200))
        self.assertIsNone(self.store.acquire_lease("worker-b", lease_seconds=300, now=1400))
        self.assertFalse(self.store.renew_lease("worker-a", "stale-token", 300, now=1401))
        self.assertFalse(self.store.renew_lease("worker-a", first, 300, now=1501))
        replacement = self.store.acquire_lease("worker-b", lease_seconds=300, now=1501)
        self.assertIsNotNone(replacement)
        self.assertFalse(self.store.renew_lease("worker-a", first, 300, now=1502))

    def test_collection_state_write_rejects_a_replaced_lease_token(self):
        token = self.store.acquire_lease("worker-a", lease_seconds=300)
        with self.store.db() as connection:
            connection.execute(
                "UPDATE youtube_analytics_lease SET token=?,lease_until=? WHERE id=1",
                ("replacement-token", 4102444800),
            )
        with self.assertRaisesRegex(RuntimeError, "lease lost"):
            self.store.record_collection(
                "succeeded", requested=1, collected=1,
                lease_owner="worker-a", lease_token=token,
            )
        self.assertEqual(self.store.status()["status"], "not_started")

    def test_collection_status_is_read_only_and_discloses_required_scope(self):
        status = self.store.status()
        self.assertEqual(status["platform"], "youtube_analytics")
        self.assertEqual(status["scope_required"],
                         "https://www.googleapis.com/auth/yt-analytics.readonly")
        self.assertTrue(status["read_only"])
        self.assertIn("averageViewPercentage", status["available_metrics"])
        self.assertFalse(status["fresh"])



    def test_periodic_runner_records_success_and_releases_lease(self):
        from metrics_collector import run_youtube_analytics_once
        class FakeStore:
            def __init__(self):
                self.states = []
                self.released = False
            def acquire_lease(self, owner_id, lease_seconds=300):
                return "analytics-lease"
            def renew_lease(self, owner_id, token, lease_seconds=300):
                return True
            def release_lease(self, owner_id, token):
                self.released = token == "analytics-lease"
            def record_collection(self, status, **kwargs):
                self.states.append((status, kwargs))
        class FakeCollector:
            def refresh(self, **kwargs):
                return {"requested": 2, "collected": 1, "missing": ["video-2"],
                        "source": "YouTube Analytics API v2"}
        fake = FakeStore()
        result = run_youtube_analytics_once(
            store=fake, collector=FakeCollector(), upload_store=self.uploads
        )
        self.assertEqual(result["collected"], 1)
        self.assertEqual([state for state, _ in fake.states], ["running", "succeeded"])
        self.assertTrue(fake.released)

    def test_periodic_runner_marks_permission_denied_as_scope_missing(self):
        from metrics_collector import run_youtube_analytics_once
        from types import SimpleNamespace
        class FakeStore:
            def __init__(self):
                self.states = []
                self.released = False
            def acquire_lease(self, owner_id, lease_seconds=300):
                return "analytics-lease"
            def renew_lease(self, owner_id, token, lease_seconds=300):
                return True
            def release_lease(self, owner_id, token):
                self.released = True
            def record_collection(self, status, **kwargs):
                self.states.append((status, kwargs))
        class FakeCollector:
            def refresh(self, **kwargs):
                error = RuntimeError("forbidden")
                error.resp = SimpleNamespace(status=403)
                error.error_details = [{"reason": "insufficientPermissions"}]
                raise error
        fake = FakeStore()
        with self.assertRaisesRegex(RuntimeError, "forbidden"):
            run_youtube_analytics_once(
                store=fake, collector=FakeCollector(), upload_store=self.uploads
            )
        self.assertEqual(fake.states[-1][0], "scope_missing")
        self.assertEqual(fake.states[-1][1]["error"], "permission_denied")
        self.assertTrue(fake.released)



    def test_due_selection_does_not_starve_videos_after_first_batch(self):
        records = [
            {"job_id": f"job-{index:03}", "video_id": f"video-{index:03}",
             "status": "uploaded", "uploaded_at": f"2026-10-{(index % 28) + 1:02}T00:00:00+00:00"}
            for index in range(1, 56)
        ]
        uploads = FakeUploads(records)
        first = self.store.due_video_ids(uploads, limit=50, min_age_seconds=21600)
        self.assertEqual(len(first), 50)
        values = {key: 1 for key in NUMERIC_FIELDS}
        for video_id in first:
            self.store.save_snapshot(video_id, "2026-10-01", "2026-10-28", values)
        second = self.store.due_video_ids(uploads, limit=50, min_age_seconds=21600)
        self.assertEqual(len(second), 5)
        self.assertTrue(set(second).isdisjoint(first))


    def test_no_uploaded_videos_waits_without_creating_a_false_scope_success(self):
        collector = YouTubeAnalyticsCollector(
            self.store, FakeUploads([]),
            service_factory=lambda: (_ for _ in ()).throw(AssertionError("must not call API")),
        )
        result = collector.refresh()
        self.assertEqual(result["requested"], 0)
        self.assertEqual(result["collected"], 0)
        self.assertEqual(result["missing"], [])

    def test_periodic_runner_marks_invalid_credentials_separately(self):
        from metrics_collector import run_youtube_analytics_once
        from types import SimpleNamespace
        class FakeStore:
            def __init__(self):
                self.states = []
                self.released = False
            def acquire_lease(self, owner_id, lease_seconds=300):
                return "analytics-lease"
            def renew_lease(self, owner_id, token, lease_seconds=300):
                return True
            def release_lease(self, owner_id, token):
                self.released = True
            def record_collection(self, status, **kwargs):
                self.states.append((status, kwargs))
        class FakeCollector:
            def refresh(self, **kwargs):
                error = RuntimeError("unauthorized")
                error.resp = SimpleNamespace(status=401)
                raise error
        fake = FakeStore()
        with self.assertRaisesRegex(RuntimeError, "unauthorized"):
            run_youtube_analytics_once(
                store=fake, collector=FakeCollector(), upload_store=self.uploads
            )
        self.assertEqual(fake.states[-1][0], "authorization_failed")
        self.assertEqual(fake.states[-1][1]["error"], "invalid_credentials")
        self.assertTrue(fake.released)

if __name__ == "__main__":
    unittest.main()
