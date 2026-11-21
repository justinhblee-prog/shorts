import hashlib
import io
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
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
            max_asset_bytes=32, max_workspace_bytes=40, max_total_media_bytes=50,
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


    def test_upload_preserves_configured_physical_media_free_space(self):
        from unittest.mock import patch
        usage = type("Usage", (), {"free": 50})()
        with patch.dict(os.environ, {"NEXUS_MEDIA_MIN_FREE_BYTES": "100"}):
            with patch("workspace_asset_store.shutil.disk_usage", return_value=usage):
                with self.assertRaisesRegex(AssetError, "insufficient media storage free space"):
                    self.store.register_stream(
                        "ws_studio", "alice", io.BytesIO(b"four"), "low-space.mp4"
                    )
        with self.store.db() as db:
            active = db.execute("SELECT COUNT(*) AS count FROM workspace_media_assets").fetchone()["count"]
            pending = db.execute("SELECT COUNT(*) AS count FROM workspace_asset_upload_reservations").fetchone()["count"]
        self.assertEqual(active, 0)
        self.assertEqual(pending, 0)

    def test_installation_wide_capacity_counts_assets_across_workspaces(self):
        self.workspaces.create("Other", "bob", "ws_other")
        first = self.store.register_stream(
            "ws_studio", "alice", io.BytesIO(b"a" * 30), "studio.mp4"
        )
        self.assertEqual(first["size_bytes"], 30)
        with self.assertRaisesRegex(AssetError, "global media storage capacity"):
            self.store.register_stream(
                "ws_other", "bob", io.BytesIO(b"b" * 21), "other.mp4"
            )
        with self.store.db() as db:
            active = db.execute("""
                SELECT COALESCE(SUM(byte_size),0) AS total
                FROM workspace_media_assets WHERE status='active'
            """).fetchone()["total"]
            pending = db.execute("""
                SELECT COALESCE(SUM(byte_size),0) AS total
                FROM workspace_asset_upload_reservations
            """).fetchone()["total"]
        self.assertEqual(active, 30)
        self.assertEqual(pending, 0)

    def test_global_capacity_must_cover_workspace_capacity(self):
        with self.assertRaisesRegex(ValueError, "max_total_media_bytes"):
            WorkspaceAssetStore(
                self.db_path, str(self.root / "other-private"), self.workspaces,
                max_asset_bytes=16, max_workspace_bytes=40, max_total_media_bytes=39,
            )
        with self.assertRaises(ValueError):
            WorkspaceAssetStore(
                self.db_path, str(self.root / "invalid-private"), self.workspaces,
                max_asset_bytes=16, max_workspace_bytes=40, max_total_media_bytes=True,
            )

    def test_workspace_quota_counts_existing_assets(self):
        self.store.register_stream(
            "ws_studio", "alice", io.BytesIO(b"a" * 25), "first.mp4"
        )
        with self.assertRaisesRegex(AssetError, "workspace storage quota"):
            self.store.register_stream(
                "ws_studio", "alice", io.BytesIO(b"b" * 16), "second.mp4"
            )
        with self.store.db() as db:
            total = db.execute("""
                SELECT COALESCE(SUM(byte_size),0) AS total
                FROM workspace_media_assets
                WHERE workspace_id='ws_studio' AND status='active'
            """).fetchone()["total"]
        self.assertEqual(total, 25)

    def test_streaming_upload_reserves_quota_before_staging_bytes(self):
        from threading import Event

        first_chunk_written = Event()
        continue_upload = Event()

        class PausedStream:
            def __init__(self):
                self.calls = 0
            def read(self, size=-1):
                self.calls += 1
                if self.calls == 1:
                    return b"a" * 12
                if self.calls == 2:
                    first_chunk_written.set()
                    if not continue_upload.wait(timeout=5):
                        raise RuntimeError("test upload release timed out")
                    return b"b" * 10
                return b""

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                self.store.register_stream,
                "ws_studio", "alice", PausedStream(), "paused.mp4"
            )
            self.assertTrue(first_chunk_written.wait(timeout=5))
            with self.store.db() as db:
                reservation = db.execute("""
                    SELECT byte_size FROM workspace_asset_upload_reservations
                    WHERE workspace_id='ws_studio'
                """).fetchone()
            self.assertIsNotNone(reservation)
            self.assertEqual(reservation["byte_size"], 12)
            staged = list((self.root / "private-media" / "ws_studio").glob(".upload-*"))
            self.assertEqual(len(staged), 1)
            # Python may still hold a small write in its file buffer; disk bytes
            # must never exceed the quota already reserved in SQLite.
            self.assertLessEqual(staged[0].stat().st_size, reservation["byte_size"])

            with self.assertRaisesRegex(AssetError, "workspace storage quota"):
                self.store.register_stream(
                    "ws_studio", "alice", io.BytesIO(b"x" * 32), "over-quota.mp4"
                )
            continue_upload.set()
            result = future.result(timeout=10)

        self.assertEqual(result["size_bytes"], 22)
        with self.store.db() as db:
            reservations = db.execute("""
                SELECT COUNT(*) AS total FROM workspace_asset_upload_reservations
                WHERE workspace_id='ws_studio'
            """).fetchone()["total"]
        self.assertEqual(reservations, 0)
        blobs = list((self.root / "private-media" / "ws_studio").glob("*.blob"))
        self.assertEqual(len(blobs), 1)

    def test_concurrent_uploads_cannot_overcommit_workspace_quota(self):
        barrier = Barrier(2)
        class SynchronizedStream(io.BytesIO):
            def __init__(self, payload):
                super().__init__(payload)
                self.first_read = True
            def read(self, size=-1):
                if self.first_read:
                    self.first_read = False
                    barrier.wait(timeout=5)
                return super().read(size)

        def upload(name):
            return self.store.register_stream(
                "ws_studio", "alice",
                SynchronizedStream(b"x" * 24), name
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(upload, "parallel-a.mp4"),
                       pool.submit(upload, "parallel-b.mp4")]
            outcomes = []
            for future in futures:
                try:
                    outcomes.append(future.result(timeout=10))
                except AssetError as exc:
                    outcomes.append(exc)
        self.assertEqual(sum(isinstance(item, dict) for item in outcomes), 1)
        self.assertEqual(sum(isinstance(item, AssetError) for item in outcomes), 1)
        with self.store.db() as db:
            total = db.execute("""
                SELECT COALESCE(SUM(byte_size),0) AS total
                FROM workspace_media_assets
                WHERE workspace_id='ws_studio' AND status='active'
            """).fetchone()["total"]
            reservations = db.execute("""
                SELECT COUNT(*) AS total FROM workspace_asset_upload_reservations
                WHERE workspace_id='ws_studio'
            """).fetchone()["total"]
        self.assertEqual(total, 24)
        self.assertEqual(reservations, 0)
        blobs = list((self.root / "private-media" / "ws_studio").glob("*.blob"))
        self.assertEqual(len(blobs), 1)

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

    def test_resolves_verified_clean_asset_path_for_authorized_render_worker(self):
        payload = b"render-source"
        result = self.store.register_stream(
            "ws_studio", "alice", io.BytesIO(payload), "source.mp4"
        )
        self.store.mark_scan_result("ws_studio", "alice", result["asset_id"], True)
        path = self.store.resolve_clean_asset_path("ws_studio", "alice", result["asset_id"])
        self.assertTrue(path.is_absolute())
        self.assertEqual(path.read_bytes(), payload)
        with self.assertRaises(WorkspaceDenied):
            self.store.resolve_clean_asset_path("ws_studio", "mallory", result["asset_id"])

    def test_trusted_scanner_attestation_promotes_pending_asset_and_audits(self):
        result = self.store.register_stream(
            "ws_studio", "alice", io.BytesIO(b"scan-this"), "scan.mp4"
        )
        class CleanScanner:
            def scan(self, path):
                self.assertion = path.read_bytes()
                return {"status": "clean", "engine": "clamav"}
        scanner = CleanScanner()
        metadata = self.store.scan_pending_asset(
            "ws_studio", result["asset_id"], scanner
        )
        self.assertEqual(scanner.assertion, b"scan-this")
        self.assertEqual(metadata["scan_status"], "clean")
        events = self.workspaces.list_audit_events(
            "ws_studio", "alice", limit=10
        )
        self.assertTrue(any(event["event_type"] == "asset.scan_clean"
                            for event in events))

    def test_scanner_failure_keeps_asset_quarantined(self):
        result = self.store.register_stream(
            "ws_studio", "alice", io.BytesIO(b"scan-failure"), "pending.mp4"
        )
        class FailedScanner:
            def scan(self, path):
                raise RuntimeError("scanner unavailable")
        with self.assertRaisesRegex(RuntimeError, "scanner unavailable"):
            self.store.scan_pending_asset(
                "ws_studio", result["asset_id"], FailedScanner()
            )
        metadata = self.store.get_asset(
            "ws_studio", "alice", result["asset_id"]
        )
        self.assertEqual(metadata["scan_status"], "pending")

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
