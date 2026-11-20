import asyncio
import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from media_scanner import MediaScanError
from render_asset_store import (
    RenderAssetError,
    RenderAssetNotFound,
    RenderAssetStore,
)


PAYLOAD = b"0000ftypisom" + b"trusted-media-fixture"


class CleanScanner:
    def scan(self, path):
        return {"status": "clean", "engine": "test"}


class FailedScanner:
    def scan(self, path):
        raise MediaScanError("scanner unavailable")


async def stream_of(*chunks):
    for chunk in chunks:
        yield chunk


class RenderAssetStoreTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.store = RenderAssetStore(
            db_path=self.root / "nexus.sqlite3",
            media_dir=self.root / "media",
            scanner=CleanScanner(),
            scan_enabled=True,
            max_video_bytes=1024,
            max_audio_bytes=512,
        )

    def tearDown(self):
        self.tmp.cleanup()

    async def register(self, workspace="workspace-a", name="phone.mp4", chunks=None, **kwargs):
        return await self.store.register_stream(
            workspace, "operator-a", "video/mp4", name,
            stream_of(*(chunks or [PAYLOAD])), **kwargs,
        )

    async def test_registers_workspace_asset_and_resolves_hash_verified_path(self):
        result = await self.register(chunks=[PAYLOAD[:7], PAYLOAD[7:]])
        self.assertEqual(result["asset_type"], "video")
        self.assertEqual(result["scan_status"], "clean")
        self.assertTrue(result["render_ready"])
        self.assertEqual(result["sha256"], hashlib.sha256(PAYLOAD).hexdigest())
        paths = self.store.resolve_asset_paths("workspace-a", [result["asset_id"]])
        self.assertEqual(paths[result["asset_id"]].read_bytes(), PAYLOAD)
        self.assertEqual(self.store.list_assets("workspace-a")[0]["asset_id"], result["asset_id"])

    async def test_asset_is_not_visible_or_resolvable_from_another_workspace(self):
        result = await self.register()
        self.assertEqual(self.store.list_assets("workspace-b"), [])
        with self.assertRaises(RenderAssetNotFound):
            self.store.resolve_asset_paths("workspace-b", [result["asset_id"]])

    async def test_rejects_tampered_asset_bytes_on_resolution(self):
        result = await self.register()
        path = self.store.resolve_asset_paths("workspace-a", [result["asset_id"]])[result["asset_id"]]
        path.write_bytes(b"tampered")
        with self.assertRaisesRegex(RenderAssetError, "checksum"):
            self.store.resolve_asset_paths("workspace-a", [result["asset_id"]])

    async def test_unscanned_asset_is_not_render_resolvable(self):
        store = RenderAssetStore(
            db_path=self.root / "unscanned.sqlite3",
            media_dir=self.root / "unscanned-media",
            scan_enabled=False,
            max_video_bytes=1024,
        )
        result = await store.register_stream(
            "workspace-a", "operator-a", "video/mp4", "clip.mp4", stream_of(PAYLOAD)
        )
        self.assertFalse(result["render_ready"])
        with self.assertRaisesRegex(RenderAssetError, "malware scan"):
            store.resolve_asset_paths("workspace-a", [result["asset_id"]])

    async def test_rejects_scanner_failure_and_leaves_no_registered_asset(self):
        store = RenderAssetStore(
            db_path=self.root / "failed.sqlite3",
            media_dir=self.root / "failed-media",
            scanner=FailedScanner(),
            scan_enabled=True,
            max_video_bytes=1024,
        )
        with self.assertRaisesRegex(RenderAssetError, "malware scanning"):
            await store.register_stream(
                "workspace-a", "operator-a", "video/mp4", "clip.mp4", stream_of(PAYLOAD)
            )
        self.assertEqual(store.list_assets("workspace-a"), [])
        self.assertEqual(list((self.root / "failed-media").rglob("*.part")), [])

    async def test_rejects_invalid_type_signature_and_workspace(self):
        with self.assertRaisesRegex(RenderAssetError, "Only MP4"):
            await self.store.register_stream(
                "workspace-a", "operator-a", "video/quicktime", "clip.mov", stream_of(PAYLOAD)
            )
        with self.assertRaisesRegex(RenderAssetError, "signature"):
            await self.store.register_stream(
                "workspace-a", "operator-a", "video/mp4", "bad.mp4", stream_of(b"not an mp4 file")
            )
        with self.assertRaisesRegex(RenderAssetError, "workspace"):
            await self.store.register_stream(
                "../outside", "operator-a", "video/mp4", "clip.mp4", stream_of(PAYLOAD)
            )

    async def test_rejects_declared_and_streamed_size_overflow(self):
        with self.assertRaisesRegex(RenderAssetError, "Content-Length"):
            await self.register(declared_length=len(PAYLOAD) + 1)
        with self.assertRaisesRegex(RenderAssetError, "size limit"):
            await self.register(chunks=[PAYLOAD, b"x" * 2048])
        self.assertEqual(self.store.list_assets("workspace-a"), [])

    async def test_rejects_declared_length_mismatch(self):
        with self.assertRaisesRegex(RenderAssetError, "does not match"):
            await self.register(declared_length=len(PAYLOAD) + 1)
        self.assertEqual(self.store.list_assets("workspace-a"), [])

    async def test_sanitizes_display_name_without_using_it_as_a_path(self):
        result = await self.register(name="../../private\\clip?.mp4")
        self.assertEqual(result["original_name"], "clip_.mp4")
        paths = self.store.resolve_asset_paths("workspace-a", [result["asset_id"]])
        self.assertTrue(paths[result["asset_id"]].is_relative_to(self.root / "media"))

    async def test_rejects_symlinked_workspace_namespace(self):
        namespace = hashlib.sha256(b"workspace-a").hexdigest()
        external = self.root / "outside"
        external.mkdir()
        (self.root / "media").mkdir()
        (self.root / "media" / namespace).symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(RenderAssetError, "symlink"):
            await self.register()
        self.assertEqual(list(external.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
