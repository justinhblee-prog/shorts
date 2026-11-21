import os
import unittest
from unittest.mock import patch

from timeline_render_worker_service import (
    RECONCILE_INTERVAL_SECONDS, _integer_env, reconcile_artifacts,
)


class TimelineRenderWorkerServiceConfigTests(unittest.TestCase):
    def test_artifact_reconciliation_interval_has_safe_default_and_bounds(self):
        self.assertEqual(RECONCILE_INTERVAL_SECONDS, 300)
        for value in ("", "59", "86401", "-1", "1.5"):
            with patch.dict(os.environ, {"NEXUS_RENDER_RECONCILE_INTERVAL_SECONDS": value}):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    _integer_env(
                        "NEXUS_RENDER_RECONCILE_INTERVAL_SECONDS", 300, 60, 86_400
                    )

    def test_reconciliation_runs_both_sweeps_and_logs_removal_counts(self):
        class Store:
            def __init__(self):
                self.calls = []

            def reconcile_orphaned_staging(self, *, grace_seconds):
                self.calls.append(("staging", grace_seconds))
                return {"removed_files": 2, "removed_directories": 1, "removed_bytes": 30}

            def reconcile_orphaned_files(self, *, grace_seconds):
                self.calls.append(("artifacts", grace_seconds))
                return {"removed": 3, "removed_bytes": 40}

        store = Store()
        with self.assertLogs("nexus.timeline_render_worker", level="INFO") as captured:
            result = reconcile_artifacts(store)
        self.assertEqual(store.calls, [("staging", 7200), ("artifacts", 7200)])
        self.assertEqual(result["removed"], 6)
        self.assertEqual(result["staging"]["removed_bytes"] + result["artifacts"]["removed_bytes"], 70)
        self.assertIn("removed_staging_files=2", captured.output[0])
        self.assertIn("removed_artifacts=3", captured.output[0])

    def test_integer_environment_values_are_bounded_decimal_values(self):
        with patch.dict(os.environ, {"NEXUS_RENDER_WIDTH": "720"}):
            self.assertEqual(_integer_env("NEXUS_RENDER_WIDTH", 1080, 16, 8192), 720)
        for value in ("", "-1", "1.5", "8193", "NaN"):
            with patch.dict(os.environ, {"NEXUS_RENDER_WIDTH": value}):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    _integer_env("NEXUS_RENDER_WIDTH", 1080, 16, 8192)


if __name__ == "__main__":
    unittest.main()
