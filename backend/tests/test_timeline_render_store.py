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
from render_artifact_store import RenderArtifactStore


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
        self.artifacts = RenderArtifactStore(
            self.queue, root / "render-staging", root / "render-artifacts"
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


    def _complete_render_and_adopt_fixture(self, idempotency_key):
        result = self.store.submit(
            "ws_studio", "alice", self.edl, idempotency_key
        )
        generation = self.queue.register_worker("timeline-review-fixture")["generation_token"]
        job = self.queue.claim(
            "timeline-review-fixture", job_type="timeline_render",
            generation_token=generation,
        )
        self.queue.finish(
            job["id"], "timeline-review-fixture", job["lease_token"],
            {"snapshot_id": result["snapshot_id"], "review_required": True},
            generation_token=generation, workspace_id="ws_studio",
        )
        with self.queue.db() as db:
            db.execute("""
                INSERT INTO render_artifacts
                (artifact_id,job_id,workspace_id,snapshot_id,snapshot_sha256,
                 artifact_sha256,byte_size,media_suffix,storage_key,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)
            """, (
                "rart_" + "f" * 32, job["id"], "ws_studio",
                result["snapshot_id"], result["payload_sha256"], "e" * 64,
                128, ".mp4", "rart_" + "f" * 32 + ".mp4", "2026-11-20T00:00:00+00:00",
            ))
        return result

    def test_review_queue_exposes_only_adopted_unreviewed_timeline_outputs(self):
        result = self._complete_render_and_adopt_fixture("render-review-0001")
        pending = self.store.list_pending_reviews("ws_studio", "alice")
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["snapshot_id"], result["snapshot_id"])
        self.assertIn("/preview", pending[0]["preview_url"])
        decision = self.store.review_decide(
            "ws_studio", "alice", result["snapshot_id"], "approved", "Looks good"
        )
        self.assertEqual(decision["decision"], "approved")
        self.assertEqual(decision["artifact_sha256"], "e" * 64)
        self.assertEqual(
            self.store.review_status("ws_studio", "alice", result["snapshot_id"])["status"],
            "approved",
        )
        self.assertEqual(self.store.list_pending_reviews("ws_studio", "alice"), [])

    def test_review_decision_is_single_immutable_record_bound_to_artifact(self):
        result = self._complete_render_and_adopt_fixture("render-review-0002")
        self.store.review_decide(
            "ws_studio", "alice", result["snapshot_id"], "revision_requested", "Fix timing"
        )
        with self.assertRaisesRegex(SnapshotConflict, "already has a review decision"):
            self.store.review_decide(
                "ws_studio", "alice", result["snapshot_id"], "approved", "Second decision"
            )
        with self.store._db() as db:
            row = db.execute(
                "SELECT decision,artifact_sha256 FROM timeline_render_reviews WHERE snapshot_id=?",
                (result["snapshot_id"],),
            ).fetchone()
            self.assertEqual(row["decision"], "revision_requested")
            self.assertEqual(row["artifact_sha256"], "e" * 64)

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


    def test_queue_and_snapshot_roll_back_together_when_snapshot_insert_fails(self):
        with self.store._db() as db:
            db.execute("""
                CREATE TRIGGER reject_test_snapshot
                BEFORE INSERT ON timeline_edl_snapshots
                BEGIN SELECT RAISE(ABORT, 'injected snapshot failure'); END
            """)
        with self.assertRaisesRegex(SnapshotConflict, "already exists"):
            self.store.submit("ws_studio", "alice", self.edl, "render-atomic-0001")
        self.assertEqual(self.queue.stats(workspace_id="ws_studio").get("total", 0), 0)
        with self.store._db() as db:
            count = db.execute(
                "SELECT COUNT(*) FROM timeline_edl_snapshots"
            ).fetchone()[0]
            db.execute("DROP TRIGGER reject_test_snapshot")
        self.assertEqual(count, 0)

    def test_concurrent_style_replay_returns_same_snapshot_and_job(self):
        first = self.store.submit(
            "ws_studio", "alice", self.edl, "render-atomic-0002"
        )
        replay = self.store.submit(
            "ws_studio", "alice", self.edl, "render-atomic-0002"
        )
        self.assertEqual(replay["snapshot_id"], first["snapshot_id"])
        self.assertEqual(replay["render_job_id"], first["render_job_id"])
        self.assertTrue(replay["replayed"])
        self.assertEqual(self.queue.stats(workspace_id="ws_studio")["total"], 1)


if __name__ == "__main__":
    unittest.main()
