import unittest

import metrics_collector
from metrics_collector import CollectorLeaseLost, LeaseHeartbeat


class MetricsCollectorLeaseTests(unittest.TestCase):
    class FakeStore:
        def __init__(self, renew_ok=True):
            self.renew_ok = renew_ok
            self.renew_calls = 0
            self.states = []
            self.released = None

        def acquire_metrics_collector_lease(self, owner_id, lease_seconds=300):
            return "lease-token"

        def renew_metrics_collector_lease(self, owner_id, token, lease_seconds=300):
            self.renew_calls += 1
            return self.renew_ok

        def release_metrics_collector_lease(self, owner_id, token):
            self.released = (owner_id, token)
            return True

        def record_metrics_collection(self, status, **kwargs):
            self.states.append((status, kwargs))

    class FakePublisher:
        def __init__(self, failure=None):
            self.failure = failure
            self.kwargs = None

        def refresh_due_metrics(self, **kwargs):
            self.kwargs = kwargs
            if self.failure:
                raise self.failure
            return {
                "requested": 2, "collected": 2, "missing": [],
                "source": "YouTube Data API v3",
            }

    def test_heartbeat_renews_and_stops_cleanly(self):
        calls = []
        heartbeat = LeaseHeartbeat(lambda: calls.append(True) or True, lease_seconds=30)
        heartbeat.start()
        heartbeat.assert_owned()
        heartbeat.close()
        self.assertGreaterEqual(len(calls), 1)
        self.assertFalse(heartbeat.thread.is_alive())

    def test_lost_heartbeat_fails_closed(self):
        heartbeat = LeaseHeartbeat(lambda: False, lease_seconds=30)
        with self.assertRaises(CollectorLeaseLost):
            heartbeat.assert_owned()
        heartbeat.close()

    def test_youtube_data_collector_fences_batch_and_records_success(self):
        store = self.FakeStore()
        publisher = self.FakePublisher()
        result = metrics_collector.run_once(store=store, publisher=publisher)
        self.assertEqual(result["collected"], 2)
        self.assertEqual([state for state, _ in store.states], ["running", "succeeded"])
        self.assertGreaterEqual(store.renew_calls, 2)
        self.assertEqual(
            store.released, (metrics_collector.OWNER_ID, "lease-token")
        )
        self.assertEqual(publisher.kwargs["lease_owner"], metrics_collector.OWNER_ID)
        self.assertEqual(publisher.kwargs["lease_token"], "lease-token")

    def test_youtube_data_collector_records_failure_only_while_lease_is_owned(self):
        store = self.FakeStore()
        publisher = self.FakePublisher(RuntimeError("provider unavailable"))
        with self.assertRaisesRegex(RuntimeError, "provider unavailable"):
            metrics_collector.run_once(store=store, publisher=publisher)
        self.assertEqual([state for state, _ in store.states], ["running", "failed"])
        self.assertEqual(
            store.released, (metrics_collector.OWNER_ID, "lease-token")
        )

    def test_youtube_data_collector_discards_results_after_lease_loss(self):
        store = self.FakeStore(renew_ok=False)
        publisher = self.FakePublisher()
        with self.assertRaises(CollectorLeaseLost):
            metrics_collector.run_once(store=store, publisher=publisher)
        self.assertEqual(store.states, [])
        self.assertIsNone(publisher.kwargs)
        self.assertEqual(
            store.released, (metrics_collector.OWNER_ID, "lease-token")
        )


if __name__ == "__main__":
    unittest.main()
