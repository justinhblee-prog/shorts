import hashlib
import tempfile
import unittest
from pathlib import Path

from media_binary_pin import MediaBinaryPinError, verify_binary_manifest


class MediaBinaryPinTests(unittest.TestCase):
    def test_verifies_exact_configured_binary_paths_and_hashes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ffmpeg = root / "ffmpeg"
            ffprobe = root / "ffprobe"
            ffmpeg.write_bytes(b"ffmpeg-binary")
            ffprobe.write_bytes(b"ffprobe-binary")
            manifest = root / "media-binaries.sha256"
            entries = [
                f"{hashlib.sha256(ffmpeg.read_bytes()).hexdigest()} {ffmpeg}",
                f"{hashlib.sha256(ffprobe.read_bytes()).hexdigest()} {ffprobe}",
            ]
            manifest.write_text("\n".join(entries) + "\n", encoding="ascii")
            result = verify_binary_manifest([str(ffmpeg), str(ffprobe)], str(manifest))
            self.assertEqual(result[str(ffmpeg)], hashlib.sha256(b"ffmpeg-binary").hexdigest())
            self.assertEqual(result[str(ffprobe)], hashlib.sha256(b"ffprobe-binary").hexdigest())

    def test_rejects_tampered_binary(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binary = root / "ffmpeg"
            binary.write_bytes(b"original")
            manifest = root / "manifest.sha256"
            manifest.write_text(
                f"{hashlib.sha256(b'original').hexdigest()} {binary}\n",
                encoding="ascii",
            )
            binary.write_bytes(b"tampered")
            with self.assertRaisesRegex(MediaBinaryPinError, "checksum"):
                verify_binary_manifest([str(binary)], str(manifest))

    def test_rejects_unlisted_binary_and_unsafe_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binary = root / "ffmpeg"
            binary.write_bytes(b"ffmpeg")
            manifest = root / "manifest.sha256"
            manifest.write_text("", encoding="ascii")
            with self.assertRaisesRegex(MediaBinaryPinError, "not pinned"):
                verify_binary_manifest([str(binary)], str(manifest))
            link = root / "manifest-link"
            link.symlink_to(manifest)
            with self.assertRaisesRegex(MediaBinaryPinError, "missing or unsafe"):
                verify_binary_manifest([str(binary)], str(link))


if __name__ == "__main__":
    unittest.main()
