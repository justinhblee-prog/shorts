import hashlib
import io
import os
import tempfile
import unittest
from pathlib import Path

from workspace_store import WorkspaceStore, WorkspaceDenied
from workspace_asset_store import (
    AssetError, AssetNotFound, WorkspaceAssetStore,
)


class WorkspaceAssetStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db_path = str(self.root / "nexus.sqlite3")
        self.workspaces = WorkspaceStore(self.db_path)
        self.workspaces.create("Studio", "alice", "ws_studio")
        self.store = WorkspaceAssetStore(
            self.db_path, str(self.root / "private-media"), self.workspaces,
            max_asset_bytes=32,
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_registers_private_asset_with_server_hash_and_quarantine(self):
        payload = b"private-media-fixture"
        result = self.store.register_stream(
            "ws_studio", "alice", io.BytesIO(payload), "clip.mp4"
        )
        self.assertEqual(result["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(result["size_bytes"], len(payload))
        self.assertEqual(result["scan_status"], "pending")
        with self.assertRaisesRegex(AssetError, "quarantined"):
            self.store.open_clean_asset("ws_studio", "alice", result["asset_id"])

    def test_clean_asset_is_available_only_after_admin_scan_transition(self):
        payload = b"safe-media"
        result = self.store.register_stream(
            "ws_studio", "alice", io.BytesIO(payload), "safe.mp4"
        )
        metadata = self.store.mark_scan_result(
            "ws_studio", "alice", result["asset_id"], True
        )
        self.assertEqual(metadata["scan_status"], "clean")
        with self.store.open_clean_asset(
            "ws_studio", "alice", result["asset_id"]
        ) as handle:
            self.assertEqual(handle.read(), payload)

    def test_rejects_cross_workspace_and_non_member_access(self):
        result = self.store.register_stream(
            "ws_studio", "alice", io.BytesIO(b"payload"), "clip.mp4"
        )
        with self.assertRaises(WorkspaceDenied):
            self.store.get_asset("ws_studio", "mallory", result["asset_id"])
        self.workspaces.create("Other", "bob", "ws_other")
        with self.assertRaises(AssetNotFound):
            self.store.get_asset("ws_other", "bob", result["asset_id"])

    def test_rejects_oversized_empty_and_invalid_name(self):
        with self.assertRaisesRegex(AssetError, "byte limit"):
            self.store.register_stream(
                "ws_studio", "alice", io.BytesIO(b"x" * 33), "large.mp4"
            )
        with self.assertRaisesRegex(AssetError, "empty"):
            self.store.register_stream(
                "ws_studio", "alice", io.BytesIO(b""), "empty.mp4"
            )
        with self.assertRaises(ValueError):
            self.store.register_stream(
                "ws_studio", "alice", io.BytesIO(b"x"), "../escape.mp4"
            )

    def test_rejects_duplicate_workspace_content_and_cleans_staging(self):
        self.store.register_stream(
            "ws_studio", "alice", io.BytesIO(b"duplicate"), "one.mp4"
        )
        with self.assertRaisesRegex(Exception, "already registered"):
            self.store.register_stream(
                "ws_studio", "alice", io.BytesIO(b"duplicate"), "two.mp4"
            )
        files = list((self.root / "private-media" / "ws_studio").iterdir())
        self.assertEqual(len(files), 1)
        self.assertFalse(any(path.name.startswith(".upload-") for path in files))

    def test_detects_modified_binary_before_open(self):
        result = self.store.register_stream(
            "ws_studio", "alice", io.BytesIO(b"original"), "clip.mp4"
        )
        self.store.mark_scan_result("ws_studio", "alice", result["asset_id"], True)
        binary = self.root / "private-media" / "ws_studio" / (result["asset_id"] + ".blob")
        binary.write_bytes(b"tampered")
        with self.assertRaisesRegex(AssetError, "integrity"):
            self.store.open_clean_asset("ws_studio", "alice", result["asset_id"])

    def test_viewer_cannot_register_or_mark_scan_result(self):
        self.workspaces.add_member("ws_studio", "alice", "viewer", "viewer")
        with self.assertRaises(WorkspaceDenied):
            self.store.register_stream(
                "ws_studio", "viewer", io.BytesIO(b"payload"), "clip.mp4"
            )


    def test_scan_path_verifies_pending_asset_and_persists_probe_metadata(self):
        result = self.store.register_stream(
            "ws_studio", "alice", io.BytesIO(b"probe-media"), "clip.mp4"
        )
        path = self.store.path_for_scan("ws_studio", "alice", result["asset_id"])
        self.assertTrue(path.is_file())
        metadata = {
            "duration_ms": 2500, "byte_size": len(b"probe-media"),
            "has_video": True, "has_audio": False,
            "video_streams": [{"codec": "h264", "width": 640, "height": 360}],
            "audio_streams": [],
        }
        verified = self.store.mark_scan_result(
            "ws_studio", "alice", result["asset_id"], True,
            media_metadata=metadata, scanner_verified=True,
        )
        self.assertEqual(verified["duration_ms"], 2500)
        self.assertEqual(verified["media_metadata"]["has_video"], True)
        with self.assertRaisesRegex(AssetError, "only pending"):
            self.store.path_for_scan("ws_studio", "alice", result["asset_id"])

    def test_editor_cannot_self_certify_asset_without_scanner_verification(self):
        self.workspaces.add_member("ws_studio", "alice", "editor", "editor")
        result = self.store.register_stream(
            "ws_studio", "editor", io.BytesIO(b"editor-media"), "clip.mp4"
        )
        with self.assertRaises(WorkspaceDenied):
            self.store.mark_scan_result(
                "ws_studio", "editor", result["asset_id"], True
            )
        verified = self.store.mark_scan_result(
            "ws_studio", "editor", result["asset_id"], True,
            media_metadata={
                "duration_ms": 1000, "byte_size": len(b"editor-media"),
                "has_video": True, "has_audio": False,
                "video_streams": [{"codec": "h264", "width": 640, "height": 360}],
                "audio_streams": [],
            },
            scanner_verified=True,
        )
        self.assertEqual(verified["scan_status"], "clean")


if __name__ == "__main__":
    unittest.main()
