import unittest
from unittest.mock import Mock, patch

import metrics_collector


class ScheduledYouTubeAnalyticsOAuthTests(unittest.TestCase):
    def test_default_collector_uses_encrypted_youtube_oauth_token_provider(self):
        store = Mock()
        store.acquire_lease.return_value = "lease-token"
        collector = Mock()
        collector.refresh_due_metrics.return_value = {
            "requested": 1, "collected": 1, "failed": [], "results": []
        }
        token_manager = Mock()
        store.renew_lease.return_value = True

        with patch("metrics_collector.YouTubeAnalyticsStore", return_value=store), \
             patch("metrics_collector.YouTubeOAuthStore") as oauth_store_class, \
             patch("metrics_collector.YouTubeOAuthManager", return_value=token_manager), \
             patch("metrics_collector.YouTubeAnalyticsCollector", return_value=collector) as collector_class:
            result = metrics_collector.run_youtube_analytics_once()

        oauth_store_class.assert_called_once_with(metrics_collector.DB)
        collector_class.assert_called_once_with(
            store, token_provider=token_manager.get_refresh_token
        )
        collector.refresh_due_metrics.assert_called_once()
        self.assertEqual(
            [call.args[0] for call in store.record_collection.call_args_list],
            ["running", "succeeded"],
        )
        store.release_lease.assert_called_once_with(metrics_collector.OWNER_ID, "lease-token")
        self.assertEqual(result["collected"], 1)

    def test_injected_collector_does_not_construct_oauth_manager(self):
        store = Mock()
        store.acquire_lease.return_value = "lease-token"
        collector = Mock()
        collector.refresh_due_metrics.return_value = {
            "requested": 0, "collected": 0, "failed": [], "results": []
        }

        store.renew_lease.return_value = True
        with patch("metrics_collector.YouTubeAnalyticsStore", return_value=store), \
             patch("metrics_collector.YouTubeOAuthManager") as manager_class:
            result = metrics_collector.run_youtube_analytics_once(
                collector=collector
            )

        manager_class.assert_not_called()
        self.assertEqual(result["requested"], 0)
        store.release_lease.assert_called_once_with(metrics_collector.OWNER_ID, "lease-token")

    def test_collector_failure_still_releases_lease(self):
        store = Mock()
        store.acquire_lease.return_value = "lease-token"
        collector = Mock()
        collector.refresh_due_metrics.side_effect = RuntimeError("provider unavailable")

        store.renew_lease.return_value = True
        with self.assertRaises(RuntimeError):
            metrics_collector.run_youtube_analytics_once(
                store=store, collector=collector
            )

        self.assertEqual(
            [call.args[0] for call in store.record_collection.call_args_list],
            ["running", "failed"],
        )
        store.release_lease.assert_called_once_with(metrics_collector.OWNER_ID, "lease-token")


if __name__ == "__main__":
    unittest.main()
