import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from artifact_retention_inventory import RetentionInventory


class _SQLiteStore:
    def __init__(self, path):
        self.path = str(path)

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()


class _WorkspaceStore:
    def require_membership(self, workspace_id, principal_id):
        if (workspace_id, principal_id) != ("ws-a", "owner-a"):
            raise PermissionError("workspace membership denied")


class _ArtifactStore:
    def __init__(self, path):
        self.queue = _SQLiteStore(path)


class RetentionInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "inventory.sqlite3"
        with sqlite3.connect(self.db_path) as db:
            db.executescript("""
                CREATE TABLE workspace_media_assets(
                    id TEXT, workspace_id TEXT, status TEXT, scan_status TEXT,
                    created_at TEXT, retention_until TEXT, byte_size INTEGER
                );
                CREATE TABLE pipeline_jobs(
                    id TEXT, workspace_id TEXT, status TEXT
                );
                CREATE TABLE timeline_edl_snapshots(
                    id TEXT, workspace_id TEXT, render_job_id TEXT,
                    payload_json TEXT, created_at TEXT
                );
                CREATE TABLE timeline_render_reviews(
                    snapshot_id TEXT, workspace_id TEXT, decision TEXT
                );
                CREATE TABLE render_artifacts(
                    artifact_id TEXT, job_id TEXT, workspace_id TEXT,
                    snapshot_id TEXT, created_at TEXT, byte_size INTEGER
                );
            """)
            db.execute(
                "INSERT INTO workspace_media_assets VALUES(?,?,?,?,?,?,?)",
                ("asset-a", "ws-a", "active", "clean", "2026-01-01T00:00:00+00:00",
                 "2026-01-31T00:00:00+00:00", 100),
            )
            db.execute(
                "INSERT INTO workspace_media_assets VALUES(?,?,?,?,?,?,?)",
                ("asset-c", "ws-a", "active", "clean", "2026-01-02T00:00:00+00:00",
                 "2026-02-01T00:00:00+00:00", 200),
            )
            db.execute(
                "INSERT INTO workspace_media_assets VALUES(?,?,?,?,?,?,?)",
                ("asset-b", "ws-b", "active", "clean", "2026-01-01T00:00:00+00:00",
                 "2026-01-31T00:00:00+00:00", 300),
            )
            db.execute("INSERT INTO pipeline_jobs VALUES(?,?,?)", ("job-a", "ws-a", "queued"))
            db.execute("INSERT INTO pipeline_jobs VALUES(?,?,?)", ("job-b", "ws-b", "completed"))
            payload = {"clips": [{"id": "clip", "type": "video", "asset_id": "asset-a"}],
                       "audio_tracks": []}
            db.execute(
                "INSERT INTO timeline_edl_snapshots VALUES(?,?,?,?,?)",
                ("snapshot-a", "ws-a", "job-a", json.dumps(payload), "2026-01-01T00:00:00+00:00"),
            )
            db.execute(
                "INSERT INTO timeline_edl_snapshots VALUES(?,?,?,?,?)",
                ("snapshot-b", "ws-b", "job-b",
                 json.dumps({"clips": [{"type": "video", "asset_id": "asset-b"}],
                             "audio_tracks": []}),
                 "2026-01-01T00:00:00+00:00"),
            )
            db.execute(
                "INSERT INTO render_artifacts VALUES(?,?,?,?,?,?)",
                ("rart-a", "job-a", "ws-a", "snapshot-a", "2026-01-01T00:00:00+00:00", 400),
            )
            db.commit()
        self.assets = _SQLiteStore(self.db_path)
        self.artifacts = _ArtifactStore(self.db_path)
        self.snapshots = _SQLiteStore(self.db_path)
        self.workspaces = _WorkspaceStore()
        self.inventory = RetentionInventory(
            self.assets, self.artifacts, self.snapshots, self.workspaces
        )
        self.policy = {
            "policy_version": "approved-test-policy",
            "retention_days": {"workspace_asset": 30, "render_artifact": 90},
            "grace_days": 7,
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_workspace_inventory_is_scoped_and_fail_closed(self):
        with sqlite3.connect(self.db_path) as db:
            before = {
                table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "workspace_media_assets", "pipeline_jobs",
                    "timeline_edl_snapshots", "render_artifacts",
                )
            }
        result = self.inventory.list_workspace(
            "ws-a", "owner-a", self.policy,
            now="2026-11-21T12:00:00+00:00", limit=10,
        )
        self.assertEqual(result["candidate_count"], 3)
        self.assertEqual(result["eligible_for_review_count"], 0)
        self.assertEqual(result["blocked_count"], 3)
        self.assertTrue(result["read_only"])
        self.assertFalse(result["destructive_action_performed"])
        self.assertEqual(
            {item["candidate"]["id"] for item in result["candidates"]},
            {"asset-a", "asset-c", "rart-a"},
        )
        asset = next(x for x in result["candidates"] if x["candidate"]["id"] == "asset-a")
        self.assertEqual(asset["candidate"]["active_reference_count"], 1)
        self.assertEqual(asset["candidate"]["snapshot_reference_count"], 1)
        self.assertIn("legal_hold_state_unknown", asset["evaluation"]["reason_codes"])
        self.assertIn("backup_implications_unknown", asset["evaluation"]["reason_codes"])
        artifact = next(x for x in result["candidates"] if x["candidate"]["id"] == "rart-a")
        self.assertEqual(artifact["candidate"]["active_reference_count"], 1)
        self.assertEqual(artifact["candidate"]["snapshot_reference_count"], 1)
        with sqlite3.connect(self.db_path) as db:
            after = {
                table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in before
            }
        self.assertEqual(before, after)

    def test_workspace_membership_is_required_before_inventory(self):
        with self.assertRaises(PermissionError):
            self.inventory.list_workspace(
                "ws-b", "not-a-member", self.policy,
                now="2026-11-21T12:00:00+00:00",
            )

    def test_malformed_snapshot_payload_makes_asset_references_unknown(self):
        with sqlite3.connect(self.db_path) as db:
            db.execute(
                "INSERT INTO timeline_edl_snapshots VALUES(?,?,?,?,?)",
                ("snapshot-bad", "ws-a", "job-a", "{not-json", "2026-01-03T00:00:00+00:00"),
            )
            db.commit()
        result = self.inventory.list_workspace(
            "ws-a", "owner-a", self.policy,
            now="2026-11-21T12:00:00+00:00", limit=10,
        )
        self.assertFalse(result["snapshot_reference_inventory_complete"])
        asset = next(x for x in result["candidates"] if x["candidate"]["id"] == "asset-a")
        self.assertFalse(asset["candidate"]["reference_check_complete"])
        self.assertIsNone(asset["candidate"]["active_reference_count"])
        self.assertIn("reference_check_incomplete", asset["evaluation"]["reason_codes"])

    def test_limit_is_bounded_and_reports_truncation(self):
        result = self.inventory.list_workspace(
            "ws-a", "owner-a", self.policy,
            now="2026-11-21T12:00:00+00:00", limit=1,
        )
        self.assertTrue(result["truncated"])
        self.assertLessEqual(result["candidate_count"], 2)

    def test_read_only_connections_reject_writes(self):
        original = self.assets.db

        @contextmanager
        def attempt_write():
            with original() as db:
                db.execute("PRAGMA query_only=ON")
                yield db

        self.assets.db = attempt_write
        with self.assertRaises(RetentionInventoryError):
            # The inventory itself remains SELECT-only; the failure below is
            # injected by replacing its read connection with a write-only guard.
            self.inventory.assets.db = lambda: None
            self.inventory.list_workspace(
                "ws-a", "owner-a", self.policy,
                now="2026-11-21T12:00:00+00:00",
            )


if __name__ == "__main__":
    unittest.main()
