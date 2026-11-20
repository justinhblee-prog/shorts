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
        audio = self.assets.register_stream(
            "ws_studio", "alice", io.BytesIO(b"audio-fixture"), "music.wav"
        )
        self.assets.mark_scan_result("ws_studio", "alice", audio["asset_id"], True)
        self.audio_asset_id = audio["asset_id"]
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
        self.assertEqual(snapshot["payload"]["clips"], self.edl["clips"])
        self.assertEqual(snapshot["payload"]["audio_tracks"], [])
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


    def test_submit_persists_and_authorizes_audio_track_assets(self):
        edl = {
            **self.edl,
            "audio_tracks": [{
                "id": "music1", "asset_id": self.audio_asset_id,
                "start_ms": 0, "source_in_ms": 250,
                "source_out_ms": 4250, "gain": 0.4,
                "fade_in_ms": 100, "fade_out_ms": 200,
            }],
        }
        result = self.store.submit("ws_studio", "alice", edl, "render-audio-0001")
        job = self.queue.get(result["render_job_id"], workspace_id="ws_studio")
        self.assertEqual(job["payload"]["creator_principal_id"], "alice")
        self.assertEqual(job["payload"]["edl"]["audio_tracks"][0]["asset_id"], self.audio_asset_id)

        pending = self.assets.register_stream(
            "ws_studio", "alice", io.BytesIO(b"pending-audio"), "pending.wav"
        )
        blocked = {
            **self.edl,
            "audio_tracks": [{
                "id": "music2", "asset_id": pending["asset_id"],
                "start_ms": 0, "source_in_ms": 0, "source_out_ms": 1000,
            }],
        }
        with self.assertRaisesRegex(SnapshotError, "audio assets"):
            self.store.submit("ws_studio", "alice", blocked, "render-audio-0002")

    def test_queue_job_and_snapshot_are_atomic_on_snapshot_insert_failure(self):
        with self.store._db() as db:
            db.execute("""
                CREATE TRIGGER reject_snapshot_for_test
                BEFORE INSERT ON timeline_edl_snapshots
                BEGIN SELECT RAISE(ABORT, 'snapshot write failure'); END
            """)
        with self.assertRaises(SnapshotConflict):
            self.store.submit("ws_studio", "alice", self.edl, "render-atomic-0001")
        self.assertEqual(self.queue.stats(workspace_id="ws_studio").get("total", 0), 0)


    def test_submit_requires_probed_stream_type_and_source_duration(self):
        audio_only = self.assets.register_stream(
            "ws_studio", "alice", io.BytesIO(b"audio-only"), "music.wav"
        )
        self.assets.mark_scan_result(
            "ws_studio", "alice", audio_only["asset_id"], True,
            media_metadata={
                "duration_ms": 6000, "byte_size": len(b"audio-only"),
                "has_video": False, "has_audio": True,
                "video_streams": [], "audio_streams": [{"codec": "aac"}],
            },
        )
        invalid_video = {
            **self.edl,
            "clips": [{
                **self.edl["clips"][0], "asset_id": audio_only["asset_id"],
            }],
        }
        with self.assertRaisesRegex(SnapshotError, "probed video asset"):
            self.store.submit("ws_studio", "alice", invalid_video, "render-type-0001")

        video = self.assets.register_stream(
            "ws_studio", "alice", io.BytesIO(b"short-video"), "short.mp4"
        )
        self.assets.mark_scan_result(
            "ws_studio", "alice", video["asset_id"], True,
            media_metadata={
                "duration_ms": 2000, "byte_size": len(b"short-video"),
                "has_video": True, "has_audio": False,
                "video_streams": [{"codec": "h264", "width": 640, "height": 360}],
                "audio_streams": [],
            },
        )
        too_long = {
            **self.edl,
            "clips": [{
                **self.edl["clips"][0], "asset_id": video["asset_id"],
                "source_out_ms": 5000,
            }],
        }
        with self.assertRaisesRegex(EDLValidationError, "source trim exceeds"):
            self.store.submit("ws_studio", "alice", too_long, "render-duration-0001")


if __name__ == "__main__":
    unittest.main()
