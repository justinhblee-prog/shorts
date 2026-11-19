import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from tiktok_publishing import TikTokPublishStore
from tiktok_metrics import TikTokMetricsStore, TikTokMetricsCollector, TikTokMetricsError
from metrics_collector import run_tiktok_once, CollectorLeaseLost


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

    def test_history_can_find_a_published_video_outside_the_recent_500(self):
        self.store.save_snapshot("job-1", {
            "id": "video-1", "view_count": 123, "like_count": 4,
            "comment_count": 2, "share_count": 1,
        })
        for index in range(2, 207):
            self._publish("job-" + str(index), "video-" + str(index))
        with self.publications.db() as connection:
            connection.execute(
                "UPDATE tiktok_publications SET updated_at=? WHERE video_id=?",
                ("2000-01-01T00:00:00+00:00", "video-1"),
            )
        history = self.store.history(
            self.publications, video_id="video-1", limit=500
        )
        self.assertEqual([item["video_id"] for item in history], ["video-1"])
        self.assertEqual(history[0]["view_count"], 123)

    def test_metrics_history_has_global_time_index(self):
        with self.store.db() as connection:
            indexes={
                row["name"] for row in connection.execute(
                    "PRAGMA index_list(tiktok_video_metric_snapshots)"
                ).fetchall()
            }
        self.assertIn("idx_tiktok_metric_time",indexes)
        self.assertIn("idx_tiktok_metric_video_time",indexes)

    def test_history_since_filters_before_applying_limit(self):
        self.store.save_snapshot("job-1", {
            "id": "video-1", "view_count": 10, "like_count": 1,
            "comment_count": 0, "share_count": 0,
        })
        with self.store.db() as connection:
            connection.execute(
                "UPDATE tiktok_video_metric_snapshots SET collected_at=? WHERE video_id=?",
                ("2026-11-01T00:00:00+00:00", "video-1"),
            )
        self.store.save_snapshot("job-1", {
            "id": "video-1", "view_count": 20, "like_count": 2,
            "comment_count": 0, "share_count": 0,
        })
        with self.store.db() as connection:
            connection.execute(
                "UPDATE tiktok_video_metric_snapshots SET collected_at=? "
                "WHERE video_id=? AND view_count=20",
                ("2026-11-03T00:00:00+00:00", "video-1"),
            )
        self._publish("job-2", "video-2")
        self.store.save_snapshot("job-2", {
            "id": "video-2", "view_count": 30, "like_count": 3,
            "comment_count": 0, "share_count": 0,
        })
        with self.store.db() as connection:
            connection.execute(
                "UPDATE tiktok_video_metric_snapshots SET collected_at=? WHERE video_id=?",
                ("2026-11-02T00:00:00+00:00", "video-2"),
            )
        recent=self.store.history(self.publications,limit=1,since="2026-11-02T00:00:00+00:00")
        self.assertEqual(len(recent),1)
        self.assertGreaterEqual(recent[0]["collected_at"],"2026-11-02T00:00:00+00:00")

    def test_stale_lease_is_rejected_before_oauth_token_provider(self):
        token = self.store.acquire_lease("worker-old", 300)
        with self.store.db() as connection:
            connection.execute(
                "UPDATE tiktok_metrics_collector_lease "
                "SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=1"
            )
        collector = self._collector({
            "data": {"videos": []}, "error": {"code": "ok"},
        })

        with self.assertRaisesRegex(RuntimeError, "lease lost; stale write rejected"):
            collector.refresh_due_metrics(
                min_age_seconds=0, lease_owner="worker-old", lease_token=token,
            )

        self.assertEqual(self.scopes, [])
        self.assertEqual(self.calls, [])

    def test_lease_replaced_during_oauth_refresh_stops_before_tiktok_request(self):
        token = self.store.acquire_lease("worker-old", 300)
        collector = self._collector({
            "data": {"videos": []}, "error": {"code": "ok"},
        })

        def replacing_token_provider(required_scope):
            self.scopes.append(required_scope)
            with self.store.db() as connection:
                connection.execute(
                    "UPDATE tiktok_metrics_collector_lease "
                    "SET lease_token='replacement' WHERE id=1"
                )
            return "metrics-access-token"

        collector.token_provider = replacing_token_provider
        with self.assertRaisesRegex(RuntimeError, "lease lost; stale write rejected"):
            collector.refresh_due_metrics(
                min_age_seconds=0, lease_owner="worker-old", lease_token=token,
            )

        self.assertEqual(self.scopes, ["video.list"])
        self.assertEqual(self.calls, [])

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

    def test_stale_lease_cannot_write_metrics_or_collection_state(self):
        token = self.store.acquire_lease("collector-a", 60)
        with self.store.db() as connection:
            connection.execute(
                "UPDATE tiktok_metrics_collector_lease SET lease_token='replacement' WHERE id=1"
            )
        with self.assertRaisesRegex(RuntimeError, "stale write rejected"):
            self.store.save_snapshots(
                [("job-1", {"id": "video-1", "view_count": 5})],
                lease_owner="collector-a", lease_token=token,
            )
        with self.assertRaisesRegex(RuntimeError, "stale write rejected"):
            self.store.record_collection(
                "succeeded", requested=1, collected=1,
                lease_owner="collector-a", lease_token=token,
            )
        with self.store.db() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM tiktok_video_metric_snapshots"
            ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_metrics_lease_is_exclusive_and_owner_token_fenced(self):
        first = self.store.acquire_lease("collector-a", 60)
        self.assertIsNotNone(first)
        self.assertIsNone(self.store.acquire_lease("collector-b", 60))
        self.assertFalse(self.store.release_lease("collector-a", "wrong-token"))
        self.assertTrue(self.store.renew_lease("collector-a", first, 120))
        self.assertFalse(self.store.renew_lease("collector-b", first, 120))
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

    def test_status_reports_latest_snapshot_and_stale_or_missing_coverage(self):
        self._publish("job-2", "video-2")
        self.store.save_snapshot("job-1", {
            "id": "video-1", "view_count": 10, "like_count": 1,
            "comment_count": 0, "share_count": 0,
        })
        status = self.store.status(self.publications)
        self.assertEqual(status["coverage"]["published_videos"], 2)
        self.assertEqual(status["coverage"]["with_snapshot"], 1)
        self.assertEqual(status["coverage"]["without_snapshot"], 1)
        self.assertEqual(status["coverage"]["stale_or_missing"], 1)
        self.assertIsNotNone(status["latest_snapshot_at"])
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
            def renew_lease(self, owner_id, token, lease_seconds=300):
                return True
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
            def renew_lease(self, owner_id, token, lease_seconds=300):
                return True
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


    def test_periodic_tiktok_runner_discards_results_after_lease_loss(self):
        class FakeStore:
            def __init__(self):
                self.states = []
                self.released = False
                self.renew_results = iter([True, False])
            def acquire_lease(self, owner_id, lease_seconds=300):
                return "lease-token"
            def renew_lease(self, owner_id, token, lease_seconds=300):
                return next(self.renew_results)
            def release_lease(self, owner_id, token):
                self.released = True
            def record_collection(self, status, **kwargs):
                self.states.append((status, kwargs))
        class FakeCollector:
            def refresh_due_metrics(self, **kwargs):
                return {"requested": 1, "collected": 1, "missing": [],
                        "source": "TikTok Display API v2"}

        fake = FakeStore()
        with self.assertRaises(CollectorLeaseLost):
            run_tiktok_once(
                store=fake, collector=FakeCollector(),
                publication_store=self.publications, token_manager=object(),
            )
        self.assertEqual([state for state, _ in fake.states], ["running"])
        self.assertTrue(fake.released)

    def test_periodic_tiktok_runner_does_not_record_failure_after_lease_loss(self):
        class FakeStore:
            def __init__(self):
                self.states = []
                self.released = False
                self.renew_results = iter([True, False])
            def acquire_lease(self, owner_id, lease_seconds=300):
                return "lease-token"
            def renew_lease(self, owner_id, token, lease_seconds=300):
                return next(self.renew_results)
            def release_lease(self, owner_id, token):
                self.released = True
            def record_collection(self, status, **kwargs):
                self.states.append((status, kwargs))
        class FakeCollector:
            def refresh_due_metrics(self, **kwargs):
                raise TikTokMetricsError("provider unavailable")

        fake = FakeStore()
        with self.assertRaises(CollectorLeaseLost):
            run_tiktok_once(
                store=fake, collector=FakeCollector(),
                publication_store=self.publications, token_manager=object(),
            )
        self.assertEqual([state for state, _ in fake.states], ["running"])
        self.assertTrue(fake.released)

    def test_metrics_coverage_and_collection_include_publications_beyond_recent_200(self):
        for index in range(2, 206):
            self._publish("job-" + str(index), "video-" + str(index))
        eligible = self.publications.list_metrics_eligible()
        self.assertEqual(len(eligible), 205)
        status = self.store.status(self.publications)
        self.assertEqual(status["coverage"]["published_videos"], 205)
        self.assertEqual(status["coverage"]["without_snapshot"], 205)

        collector = self._collector({
            "data": {"videos": []}, "error": {"code": "ok", "message": ""},
        })
        result = collector.refresh_due_metrics(limit=20, min_age_seconds=0)
        self.assertEqual(result["requested"], 20)
        self.assertEqual(len(self.calls), 1)
        requested_ids = self.calls[0][2]["filters"]["video_ids"]
        self.assertEqual(len(requested_ids), 20)
        self.assertIn("video-205", requested_ids)


    def test_missing_video_results_back_off_without_starving_older_publications(self):
        for index in range(2, 22):
            self._publish("job-" + str(index), "video-" + str(index))
        empty_payload = {
            "data": {"videos": []}, "error": {"code": "ok", "message": ""},
        }
        first = self._collector(empty_payload)
        first_result = first.refresh_due_metrics(limit=20, min_age_seconds=0)
        self.assertEqual(first_result["requested"], 20)
        self.assertEqual(first_result["collected"], 0)
        self.assertEqual(len(first_result["missing"]), 20)
        deferred = self.store.deferred_video_ids()
        self.assertEqual(deferred, set(first_result["missing"]))

        self.calls.clear()
        second = self._collector(empty_payload)
        second_result = second.refresh_due_metrics(limit=20, min_age_seconds=0)
        self.assertEqual(second_result["requested"], 1)
        self.assertEqual(second_result["missing"], ["video-1"])
        self.assertTrue(set(second_result["missing"]).isdisjoint(deferred))

    def test_successful_snapshot_clears_missing_video_retry_state(self):
        self.store.record_missing_video_ids(["video-1"])
        self.assertIn("video-1", self.store.deferred_video_ids())
        self.store.save_snapshot("job-1", {
            "id": "video-1", "view_count": 8, "like_count": 1,
            "comment_count": 0, "share_count": 0,
        })
        self.assertNotIn("video-1", self.store.deferred_video_ids())


    def test_snapshot_and_missing_retry_state_commit_atomically(self):
        with self.store.db() as connection:
            connection.execute("""
                CREATE TRIGGER reject_missing_retry
                BEFORE INSERT ON tiktok_metrics_missing_retry
                BEGIN SELECT RAISE(ABORT,'simulated retry persistence failure'); END
            """)
        with self.assertRaisesRegex(Exception, "simulated retry persistence failure"):
            self.store.save_snapshots(
                [("job-1", {"id": "video-1", "view_count": 10})],
                missing_video_ids=["video-2"],
            )
        with self.store.db() as connection:
            snapshots = connection.execute(
                "SELECT COUNT(*) FROM tiktok_video_metric_snapshots"
            ).fetchone()[0]
            retries = connection.execute(
                "SELECT COUNT(*) FROM tiktok_metrics_missing_retry"
            ).fetchone()[0]
        self.assertEqual(snapshots, 0)
        self.assertEqual(retries, 0)

    def test_collector_persists_collected_and_missing_ids_in_one_batch(self):
        self._publish("job-2", "video-2")
        collector = self._collector({
            "data": {"videos": [{"id": "video-1", "view_count": 10}]},
            "error": {"code": "ok"},
        })
        result = collector.refresh_due_metrics(limit=2, min_age_seconds=0)
        self.assertEqual(result["collected"], 1)
        self.assertEqual(result["missing"], ["video-2"])
        self.assertIn("video-2", self.store.deferred_video_ids())
        with self.store.db() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM tiktok_video_metric_snapshots"
            ).fetchone()[0]
        self.assertEqual(count, 1)


    def test_metrics_lease_duration_rejects_ambiguous_or_unbounded_values(self):
        for invalid in (True, False, 1.5, "60", 0, -1, 3601, 10**9):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "lease duration"):
                    self.store.acquire_lease("collector-invalid", invalid)
        token = self.store.acquire_lease("collector-minimum", 1)
        self.assertIsNotNone(token)
        with self.store.db() as connection:
            row = connection.execute(
                "SELECT expires_at FROM tiktok_metrics_collector_lease WHERE id=1"
            ).fetchone()
        expires = datetime.fromisoformat(row["expires_at"])
        self.assertGreaterEqual((expires - datetime.now(timezone.utc)).total_seconds(), 29)
        self.assertTrue(self.store.renew_lease("collector-minimum", token, 3600))
        with self.assertRaisesRegex(ValueError, "lease duration"):
            self.store.renew_lease("collector-minimum", token, True)

if __name__ == "__main__":
    unittest.main()
