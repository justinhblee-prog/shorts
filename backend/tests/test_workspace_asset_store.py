import hashlib
import io
import os
import tempfile
import unittest
from pathlib import Path

from workspace_store import WorkspaceStore, WorkspaceDenied
from media_scanner import MediaInfectedError, MediaScanError
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


    def _scan_probe(self, *, has_video=True, has_audio=False):
        class Scanner:
            def scan(inner, path):
                return {"status": "clean", "engine": "test"}
        def probe(path):
            return {
                "duration_ms": 12000, "byte_size": Path(path).stat().st_size,
                "has_video": has_video, "has_audio": has_audio,
                "video_streams": [{"codec": "h264", "width": 640, "height": 360}] if has_video else [],
                "audio_streams": [{"codec": "aac", "sample_rate": 48000, "channels": 2}] if has_audio else [],
            }
        return Scanner(), probe

    def test_scan_requires_clamav_and_ffprobe_success_before_clean(self):
        result = self.store.register_stream(
            "ws_studio", "alice", io.BytesIO(b"scan-fixture"), "scan.mp4"
        )
        scanner, probe = self._scan_probe()
        metadata = self.store.scan_pending_asset(
            "ws_studio", "alice", result["asset_id"], scanner, probe
        )
        self.assertEqual(metadata["scan_status"], "clean")
        self.assertEqual(metadata["duration_ms"], 12000)
        self.assertTrue(metadata["media_metadata"]["has_video"])

    def test_infected_assets_are_rejected_and_scanner_outage_stays_pending(self):
        infected = self.store.register_stream(
            "ws_studio", "alice", io.BytesIO(b"infected"), "infected.mp4"
        )
        class InfectedScanner:
            def scan(self, path):
                raise MediaInfectedError("infected")
        with self.assertRaisesRegex(AssetError, "rejected"):
            self.store.scan_pending_asset(
                "ws_studio", "alice", infected["asset_id"], InfectedScanner(),
                lambda path: {},
            )
        self.assertEqual(
            self.store.get_asset("ws_studio", "alice", infected["asset_id"])["scan_status"],
            "rejected",
        )

        pending = self.store.register_stream(
            "ws_studio", "alice", io.BytesIO(b"scanner-down"), "pending.mp4"
        )
        class UnavailableScanner:
            def scan(self, path):
                raise MediaScanError("database unavailable")
        with self.assertRaisesRegex(AssetError, "remains quarantined"):
            self.store.scan_pending_asset(
                "ws_studio", "alice", pending["asset_id"], UnavailableScanner(),
                lambda path: {},
            )
        self.assertEqual(
            self.store.get_asset("ws_studio", "alice", pending["asset_id"])["scan_status"],
            "pending",
        )

    def test_source_probe_failure_or_tampering_never_marks_asset_clean(self):
        result = self.store.register_stream(
            "ws_studio", "alice", io.BytesIO(b"source"), "source.mp4"
        )
        scanner, _ = self._scan_probe()
        with self.assertRaisesRegex(AssetError, "source media probe"):
            self.store.scan_pending_asset(
                "ws_studio", "alice", result["asset_id"], scanner,
                lambda path: (_ for _ in ()).throw(ValueError("invalid media")),
            )
        self.assertEqual(
            self.store.get_asset("ws_studio", "alice", result["asset_id"])["scan_status"],
            "pending",
        )


if __name__ == "__main__":
    unittest.main()
