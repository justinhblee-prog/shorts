import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from tiktok_publishing import TikTokPublishStore
from tiktok_metrics import TikTokMetricsStore, TikTokMetricsCollector, TikTokMetricsError
from metrics_collector import run_tiktok_once


class TikTokMetricsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.temp.name) / "metrics.sqlite3")
        self.publications = TikTokPublishStore(self.db)
        self.store = TikTokMetricsStore(self.db)
        self._publish("job-1", "video-1")
        self.calls = []
        self.scopes = []

    def tearDown(self):
        self.temp.cleanup()

    def _publish(self, job_id, video_id):
        self.publications.begin(
            job_id, "Approved test", True, "operator-1",
            "attempt-" + job_id, False, False,
        )
        self.publications.mark_status(
            job_id, "attempt-" + job_id, "PUBLISH_COMPLETE", [video_id], None,
        )

    def _transport(self, payload, status=200):
        def call(url, headers, body, timeout):
            self.calls.append((url, headers, json.loads(body.decode("utf-8")), timeout))
            return status, json.dumps(payload).encode("utf-8")
        return call

    def _collector(self, payload, status=200):
        def token_provider(required_scope):
            self.scopes.append(required_scope)
            return "metrics-access-token"
        return TikTokMetricsCollector(
            self.store, self.publications, token_provider,
            self._transport(payload, status),
        )

    def test_queries_only_owned_published_ids_and_saves_four_supported_counters(self):
        collector = self._collector({
            "data": {"videos": [{
                "id": "video-1", "view_count": 1200, "like_count": 80,
                "comment_count": 12, "share_count": 5,
            }]},
            "error": {"code": "ok", "message": ""},
        })
        result = collector.refresh_due_metrics(limit=20, min_age_seconds=0)
        self.assertEqual(result["requested"], 1)
        self.assertEqual(result["collected"], 1)
        self.assertEqual(result["missing"], [])
        self.assertEqual(self.scopes, ["video.list"])
        url, headers, body, timeout = self.calls[0]
        self.assertEqual(urlparse(url).path, "/v2/video/query/")
        self.assertEqual(parse_qs(urlparse(url).query)["fields"],
                         ["id,view_count,like_count,comment_count,share_count"])
        self.assertEqual(body, {"filters": {"video_ids": ["video-1"]}})
        self.assertEqual(headers["Authorization"], "Bearer metrics-access-token")
        self.assertEqual(timeout, 30)
        with self.store.db() as connection:
            row = connection.execute(
                "SELECT * FROM tiktok_video_metric_snapshots WHERE video_id='video-1'"
            ).fetchone()
        self.assertEqual(
            [row["view_count"], row["like_count"], row["comment_count"], row["share_count"]],
            [1200, 80, 12, 5],
        )

    def test_no_due_videos_does_not_request_token_or_contact_tiktok(self):
        self.store.save_snapshot("job-1", {
            "id": "video-1", "view_count": 1, "like_count": 0,
            "comment_count": 0, "share_count": 0,
        })
        collector = self._collector({"data": {"videos": []}, "error": {"code": "ok"}})
        result = collector.refresh_due_metrics(min_age_seconds=999999)
        self.assertEqual(result["requested"], 0)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.scopes, [])

    def test_response_cannot_inject_unrequested_video_ids(self):
        collector = self._collector({
            "data": {"videos": [{"id": "not-owned", "view_count": 1}]},
            "error": {"code": "ok"},
        })
        with self.assertRaisesRegex(TikTokMetricsError, "unrequested video"):
            collector.refresh_due_metrics(min_age_seconds=0)
        with self.store.db() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM tiktok_video_metric_snapshots"
            ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_negative_or_boolean_counter_is_rejected(self):
        for invalid in (-1, True):
            with self.subTest(value=invalid):
                with self.assertRaisesRegex(TikTokMetricsError, "invalid view_count"):
                    self.store.save_snapshot("job-1", {
                        "id": "video-1", "view_count": invalid,
                    })


    def test_response_batch_is_validated_before_any_snapshot_is_committed(self):
        self._publish("job-2", "video-2")
        collector = self._collector({
            "data": {"videos": [
                {"id": "video-1", "view_count": 10, "like_count": 1,
                 "comment_count": 0, "share_count": 0},
                {"id": "video-2", "view_count": True, "like_count": 1,
                 "comment_count": 0, "share_count": 0},
            ]},
            "error": {"code": "ok"},
        })
        with self.assertRaisesRegex(TikTokMetricsError, "invalid view_count"):
            collector.refresh_due_metrics(min_age_seconds=0)
        with self.store.db() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM tiktok_video_metric_snapshots"
            ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_response_batch_rejects_duplicate_ids_before_persisting(self):
        collector = self._collector({
            "data": {"videos": [
                {"id": "video-1", "view_count": 10},
                {"id": "video-1", "view_count": 11},
            ]},
            "error": {"code": "ok"},
        })
        with self.assertRaisesRegex(TikTokMetricsError, "duplicate video IDs"):
            collector.refresh_due_metrics(min_age_seconds=0)
        with self.store.db() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM tiktok_video_metric_snapshots"
            ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_batch_store_rejects_sqlite_integer_overflow_without_partial_writes(self):
        self._publish("job-2", "video-2")
        with self.assertRaisesRegex(TikTokMetricsError, "invalid view_count"):
            self.store.save_snapshots([
                ("job-1", {"id": "video-1", "view_count": 1}),
                ("job-2", {"id": "video-2", "view_count": 2**80}),
            ])
        with self.store.db() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM tiktok_video_metric_snapshots"
            ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_api_error_and_malformed_response_fail_closed(self):
        collector = self._collector({
            "data": {"videos": []},
            "error": {"code": "scope_not_authorized"},
        }, status=200)
        with self.assertRaisesRegex(TikTokMetricsError, "scope_not_authorized"):
            collector.refresh_due_metrics(min_age_seconds=0)
        malformed = self._collector(["not", "an", "object"])
        with self.assertRaisesRegex(TikTokMetricsError, "unexpected response shape"):
            malformed.refresh_due_metrics(min_age_seconds=0)
        malformed_data = self._collector({"data": [], "error": {"code": "ok"}})
        with self.assertRaisesRegex(TikTokMetricsError, "omitted its data object"):
            malformed_data.refresh_due_metrics(min_age_seconds=0)

    def test_metrics_lease_is_exclusive_and_owner_token_fenced(self):
        first = self.store.acquire_lease("collector-a", 60)
        self.assertIsNotNone(first)
        self.assertIsNone(self.store.acquire_lease("collector-b", 60))
        self.assertFalse(self.store.release_lease("collector-a", "wrong-token"))
        self.assertTrue(self.store.release_lease("collector-a", first))
        self.assertIsNotNone(self.store.acquire_lease("collector-b", 60))

    def test_recent_metrics_returns_latest_snapshot_only_for_completed_owned_publications(self):
        self.store.save_snapshot("job-1", {
            "id": "video-1", "view_count": 10, "like_count": 1,
            "comment_count": 0, "share_count": 0,
        })
        self.store.save_snapshot("job-1", {
            "id": "video-1", "view_count": 20, "like_count": 2,
            "comment_count": 1, "share_count": 1,
        })
        self._publish("job-2", "video-2")
        self.store.save_snapshot("job-2", {
            "id": "video-2", "view_count": 5, "like_count": 0,
            "comment_count": 0, "share_count": 0,
        })
        items = self.store.recent_metrics(self.publications, limit=10)
        by_id = {x["video_id"]: x for x in items}
        self.assertEqual(by_id["video-1"]["view_count"], 20)
        self.assertEqual(by_id["video-1"]["privacy_level"], "SELF_ONLY")
        self.assertEqual(by_id["video-2"]["view_count"], 5)

    def test_status_reports_coverage_and_never_claims_unavailable_metrics(self):
        self.store.save_snapshot("job-1", {
            "id": "video-1", "view_count": 10, "like_count": 1,
            "comment_count": 0, "share_count": 0,
        })
        status = self.store.status(self.publications)
        self.assertEqual(status["coverage"]["published_videos"], 1)
        self.assertEqual(status["coverage"]["with_snapshot"], 1)
        self.assertIn("share_count", status["available_metrics"])
        self.assertIn("audience_retention", status["unavailable_metrics"])
        self.assertTrue(status["read_only"])



    def test_periodic_runner_persists_success_and_releases_lease(self):
        class FakeStore:
            def __init__(self):
                self.states = []
                self.released = False
            def acquire_lease(self, owner_id, lease_seconds=300):
                return "lease-token"
            def release_lease(self, owner_id, token):
                self.released = True
            def record_collection(self, status, **kwargs):
                self.states.append((status, kwargs))
        class FakeCollector:
            def refresh_due_metrics(self, **kwargs):
                return {"requested": 1, "collected": 1, "missing": [],
                        "source": "TikTok Display API v2"}
        fake = FakeStore()
        result = run_tiktok_once(
            store=fake, collector=FakeCollector(),
            publication_store=self.publications, token_manager=object(),
        )
        self.assertEqual(result["collected"], 1)
        self.assertEqual([x[0] for x in fake.states], ["running", "succeeded"])
        self.assertTrue(fake.released)

    def test_periodic_runner_records_failure_and_releases_lease(self):
        class FakeStore:
            def __init__(self):
                self.states = []
                self.released = False
            def acquire_lease(self, owner_id, lease_seconds=300):
                return "lease-token"
            def release_lease(self, owner_id, token):
                self.released = True
            def record_collection(self, status, **kwargs):
                self.states.append((status, kwargs))
        class FakeCollector:
            def refresh_due_metrics(self, **kwargs):
                raise TikTokMetricsError("scope unavailable")
        fake = FakeStore()
        with self.assertRaisesRegex(TikTokMetricsError, "scope unavailable"):
            run_tiktok_once(
                store=fake, collector=FakeCollector(),
                publication_store=self.publications, token_manager=object(),
            )
        self.assertEqual([x[0] for x in fake.states], ["running", "failed"])
        self.assertEqual(fake.states[-1][1]["error"], "TikTokMetricsError")
        self.assertTrue(fake.released)

if __name__ == "__main__":
    unittest.main()
