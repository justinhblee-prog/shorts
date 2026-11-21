import os
import unittest
from unittest.mock import patch

from timeline_render_worker_service import _integer_env, reconcile_artifacts


class TimelineRenderWorkerServiceConfigTests(unittest.TestCase):
    def test_periodic_artifact_reconciliation_reports_removed_file_counts(self):
        class FakeArtifactStore:
            def reconcile_orphaned_staging(self, grace_seconds):
                self.staging_grace = grace_seconds
                return {
                    "removed_files": 2,
                    "removed_directories": 1,
                    "removed_bytes": 4096,
                }

            def reconcile_orphaned_files(self, grace_seconds):
                self.indexed_grace = grace_seconds
                return {"removed": 3, "removed_bytes": 8192}

        store = FakeArtifactStore()
        with patch("builtins.print") as output:
            result = reconcile_artifacts(store)
        self.assertEqual(store.staging_grace, 7200)
        self.assertEqual(store.indexed_grace, 7200)
        self.assertEqual(result["staging"]["removed_files"], 2)
        self.assertEqual(result["unindexed"]["removed"], 3)
        message = output.call_args.args[0]
        self.assertIn("staging_files_removed=2", message)
        self.assertIn("staging_directories_removed=1", message)
        self.assertIn("unindexed_files_removed=3", message)

    def test_integer_environment_values_are_bounded_decimal_values(self):
        with patch.dict(os.environ, {"NEXUS_RENDER_WIDTH": "720"}):
            self.assertEqual(_integer_env("NEXUS_RENDER_WIDTH", 1080, 16, 8192), 720)
        for value in ("", "-1", "1.5", "8193", "NaN"):
            with patch.dict(os.environ, {"NEXUS_RENDER_WIDTH": value}):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    _integer_env("NEXUS_RENDER_WIDTH", 1080, 16, 8192)


if __name__ == "__main__":
    unittest.main()
