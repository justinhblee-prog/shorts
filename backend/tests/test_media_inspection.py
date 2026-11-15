import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from media_inspection import MediaInspectionError, inspect_media_file


class MediaInspectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "sample.mp4"
        self.path.write_bytes(b"not-empty")
        self.payload = {
            "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "28.5"},
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920},
                {"codec_type": "audio", "codec_name": "aac"},
                {"codec_type": "subtitle", "codec_name": "mov_text"},
            ],
        }

    def tearDown(self):
        self.tmp.cleanup()

    def runner(self, payload=None, returncode=0):
        raw = json.dumps(self.payload if payload is None else payload)
        return lambda *args, **kwargs: SimpleNamespace(returncode=returncode, stdout=raw, stderr="")

    def test_inspects_real_media_metadata_and_reports_byte_level_basis(self):
        report = inspect_media_file(self.path, ffprobe_path="ffprobe", runner=self.runner())
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["verification"], "ffprobe_media_bytes")
        self.assertEqual(report["duration_seconds"], 28.5)
        self.assertTrue(report["audio_track_present"])
        self.assertTrue(report["subtitle_stream_present"])

    def test_fails_closed_when_ffprobe_is_unavailable(self):
        with self.assertRaisesRegex(MediaInspectionError, "ffprobe is unavailable"):
            inspect_media_file(self.path, ffprobe_path="/definitely/missing/ffprobe")

    def test_rejects_unreadable_or_truncated_media(self):
        with self.assertRaisesRegex(MediaInspectionError, "unreadable"):
            inspect_media_file(self.path, ffprobe_path="ffprobe",
                               runner=self.runner(returncode=1))

    def test_rejects_wrong_aspect_ratio(self):
        payload = dict(self.payload)
        payload["streams"] = [dict(s) for s in self.payload["streams"]]
        payload["streams"][0]["width"] = 1920
        payload["streams"][0]["height"] = 1080
        with self.assertRaisesRegex(MediaInspectionError, "9:16"):
            inspect_media_file(self.path, ffprobe_path="ffprobe", runner=self.runner(payload))

    def test_rejects_missing_audio(self):
        payload = dict(self.payload)
        payload["streams"] = [dict(s) for s in self.payload["streams"] if s["codec_type"] != "audio"]
        with self.assertRaisesRegex(MediaInspectionError, "no audio"):
            inspect_media_file(self.path, ffprobe_path="ffprobe", runner=self.runner(payload))

    def test_rejects_overlong_and_invalid_duration(self):
        for duration in ("181", "nan", "0"):
            payload = dict(self.payload)
            payload["streams"] = [dict(s) for s in self.payload["streams"]]
            payload["format"] = {"duration": duration}
            with self.assertRaises(MediaInspectionError):
                inspect_media_file(self.path, ffprobe_path="ffprobe", runner=self.runner(payload))

    def test_rejects_empty_or_missing_file(self):
        self.path.write_bytes(b"")
        with self.assertRaisesRegex(MediaInspectionError, "empty"):
            inspect_media_file(self.path, ffprobe_path="ffprobe", runner=self.runner())
        self.path.unlink()
        with self.assertRaisesRegex(MediaInspectionError, "missing"):
            inspect_media_file(self.path, ffprobe_path="ffprobe", runner=self.runner())


if __name__ == "__main__":
    unittest.main()
