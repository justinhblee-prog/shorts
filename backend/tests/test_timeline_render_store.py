import io
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from queue_store import JobQueue
from timeline_edl import SCHEMA
from workspace_store import WorkspaceStore
from workspace_asset_store import WorkspaceAssetStore
from timeline_render_store import TimelineRenderStore, SnapshotConflict, SnapshotError


class TimelineRenderStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.db_path = str(root / "nexus.sqlite3")
        self.workspaces = WorkspaceStore(self.db_path)
        self.workspaces.create("Studio", "alice", "ws_studio")
        self.assets = WorkspaceAssetStore(
            self.db_path, str(root / "private"), self.workspaces
        )
        self.queue = JobQueue(self.db_path)
        self.store = TimelineRenderStore(
            self.db_path, self.assets, self.workspaces, self.queue
        )
        asset = self.assets.register_stream(
            "ws_studio", "alice", io.BytesIO(b"video-fixture"), "clip.mp4"
        )
        self.assets.mark_scan_result("ws_studio", "alice", asset["asset_id"], True)
        self.asset_id = asset["asset_id"]
        self.edl = {
            "schema": SCHEMA, "version": 1, "timebase": "milliseconds",
            "clips": [{
                "id": "clip-1", "type": "video", "start_ms": 0, "end_ms": 5000,
                "asset_id": self.asset_id, "source_in_ms": 0, "source_out_ms": 5000,
            }],
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_submit_persists_immutable_snapshot_and_queues_job(self):
        result = self.store.submit("ws_studio", "alice", self.edl, "render-try-0001")
        snapshot = self.store.get("ws_studio", "alice", result["snapshot_id"])
        job = self.queue.get(result["render_job_id"], workspace_id="ws_studio")
        self.assertEqual(snapshot["payload"], self.edl)
        self.assertEqual(snapshot["payload_sha256"], result["payload_sha256"])
        self.assertEqual(job["job_type"], "timeline_render")
        self.assertEqual(job["payload"]["snapshot_id"], result["snapshot_id"])
        self.assertEqual(job["payload"]["snapshot_sha256"], result["payload_sha256"])

    def test_same_idempotency_key_replays_and_different_payload_conflicts(self):
        first = self.store.submit("ws_studio", "alice", self.edl, "render-try-0002")
        replay = self.store.submit("ws_studio", "alice", self.edl, "render-try-0002")
        self.assertEqual(first["snapshot_id"], replay["snapshot_id"])
        self.assertTrue(replay["replayed"])
        changed = {**self.edl, "clips": [dict(self.edl["clips"][0], end_ms=4000,
                                                source_out_ms=4000)]}
        with self.assertRaises(SnapshotConflict):
            self.store.submit("ws_studio", "alice", changed, "render-try-0002")

    def test_snapshot_rows_reject_update_and_delete(self):
        result = self.store.submit("ws_studio", "alice", self.edl, "render-try-0003")
        with self.store._db() as db:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                db.execute("UPDATE timeline_edl_snapshots SET payload_json='{}' WHERE id=?",
                           (result["snapshot_id"],))
            with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                db.execute("DELETE FROM timeline_edl_snapshots WHERE id=?",
                           (result["snapshot_id"],))

    def test_unscanned_asset_and_cross_workspace_submission_are_denied(self):
        pending = self.assets.register_stream(
            "ws_studio", "alice", io.BytesIO(b"pending"), "pending.mp4"
        )
        edl = {**self.edl, "clips": [dict(self.edl["clips"][0], asset_id=pending["asset_id"])]}
        with self.assertRaisesRegex(SnapshotError, "malware"):
            self.store.submit("ws_studio", "alice", edl, "render-try-0004")
        self.workspaces.create("Other", "bob", "ws_other")
        with self.assertRaises(Exception):
            self.store.submit("ws_other", "bob", self.edl, "render-try-0005")


if __name__ == "__main__":
    unittest.main()
