import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ffprobe_validate import FFprobeValidationError, probe_media, has_audio_stream


class FFprobeValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.media = root / "render.mp4"
        self.binary = root / "ffprobe"
        self.media.write_bytes(b"fixture-media")
        self.binary.write_bytes(b"fixture-executable")
        self.valid = {
            "format": {"duration": "12.5", "size": str(self.media.stat().st_size)},
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080},
                {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000", "channels": 2},
            ],
        }

    def tearDown(self):
        self.temp.cleanup()

    def run_probe(self, payload=None, **kwargs):
        result = SimpleNamespace(
            returncode=0,
            stdout=json.dumps(self.valid if payload is None else payload),
            stderr="",
        )
        with patch("ffprobe_validate.subprocess.run", return_value=result) as run:
            metadata = probe_media(self.media, self.binary, **kwargs)
        return metadata, run

    def test_builds_shell_free_bounded_probe_and_returns_metadata(self):
        metadata, run = self.run_probe(require_audio=True, timeout_seconds=12)
        self.assertEqual(metadata["duration_ms"], 12500)
        self.assertEqual(metadata["byte_size"], self.media.stat().st_size)
        self.assertEqual(metadata["video_streams"][0]["width"], 1920)
        self.assertEqual(metadata["audio_streams"], 1)
        args, kwargs = run.call_args
        self.assertEqual(args[0][0], str(self.binary))
        self.assertIn(str(self.media), args[0])
        self.assertIs(kwargs["shell"], False)
        self.assertEqual(kwargs["timeout"], 12.0)

    def test_rejects_missing_video_audio_and_oversized_duration(self):
        with self.assertRaisesRegex(FFprobeValidationError, "video stream"):
            self.run_probe({"format": {"duration": "2"}, "streams": []})
        no_audio = {
            "format": {"duration": "2", "size": str(self.media.stat().st_size)},
            "streams": [{"codec_type": "video", "width": 640, "height": 480}],
        }
        with self.assertRaisesRegex(FFprobeValidationError, "audio stream"):
            self.run_probe(no_audio, require_audio=True)
        with self.assertRaisesRegex(FFprobeValidationError, "duration"):
            self.run_probe(max_duration_ms=1000)

    def test_rejects_invalid_metadata_and_size_mismatch(self):
        with self.assertRaisesRegex(FFprobeValidationError, "invalid JSON"):
            result = SimpleNamespace(returncode=0, stdout="{", stderr="")
            with patch("ffprobe_validate.subprocess.run", return_value=result):
                probe_media(self.media, self.binary)
        bad = dict(self.valid)
        bad["format"] = {"duration": "NaN", "size": str(self.media.stat().st_size)}
        with self.assertRaisesRegex(FFprobeValidationError, "duration"):
            self.run_probe(bad)
        bad = dict(self.valid)
        bad["format"] = {"duration": "2", "size": "1"}
        with self.assertRaisesRegex(FFprobeValidationError, "size"):
            self.run_probe(bad)

    def test_rejects_timeout_and_nonzero_exit(self):
        from subprocess import TimeoutExpired
        with patch("ffprobe_validate.subprocess.run", side_effect=TimeoutExpired("ffprobe", 1)):
            with self.assertRaisesRegex(FFprobeValidationError, "timeout"):
                probe_media(self.media, self.binary)
        result = SimpleNamespace(returncode=1, stdout="", stderr="invalid media")
        with patch("ffprobe_validate.subprocess.run", return_value=result):
            with self.assertRaisesRegex(FFprobeValidationError, "invalid media"):
                probe_media(self.media, self.binary)


    def test_detects_optional_source_audio_stream_without_shell(self):
        result = SimpleNamespace(
            returncode=0, stdout=json.dumps({"streams": [{"codec_type": "audio"}]}),
            stderr="",
        )
        with patch("ffprobe_validate.subprocess.run", return_value=result) as run:
            self.assertTrue(has_audio_stream(self.media, self.binary))
        args, kwargs = run.call_args
        self.assertIn("-select_streams", args[0])
        self.assertIn("a:0", args[0])
        self.assertIs(kwargs["shell"], False)
        silent = SimpleNamespace(returncode=0, stdout='{"streams":[]}', stderr="")
        with patch("ffprobe_validate.subprocess.run", return_value=silent):
            self.assertFalse(has_audio_stream(self.media, self.binary))

    def test_rejects_relative_paths_symlinks_and_invalid_limits(self):
        with self.assertRaises(FFprobeValidationError):
            probe_media("relative.mp4", self.binary)
        link = Path(self.temp.name) / "link.mp4"
        link.symlink_to(self.media)
        with self.assertRaises(FFprobeValidationError):
            probe_media(link, self.binary)
        with self.assertRaises(FFprobeValidationError):
            probe_media(self.media, self.binary, timeout_seconds=0)
        with self.assertRaises(FFprobeValidationError):
            probe_media(self.media, self.binary, max_bytes=0)


    def test_source_probe_accepts_audio_only_and_video_audio_inputs(self):
        result = SimpleNamespace(
            returncode=0, stdout=json.dumps(self.valid), stderr=""
        )
        with patch("ffprobe_validate.subprocess.run", return_value=result) as run:
            metadata = probe_source_media(self.media, self.binary)
        self.assertTrue(metadata["has_video"])
        self.assertTrue(metadata["has_audio"])
        self.assertEqual(metadata["duration_ms"], 12500)
        self.assertIn("-protocol_whitelist", run.call_args.args[0])

        audio_only = {
            "format": {"duration": "3.5", "size": str(self.media.stat().st_size)},
            "streams": [{
                "codec_type": "audio", "codec_name": "aac",
                "sample_rate": "48000", "channels": 2,
            }],
        }
        result = SimpleNamespace(returncode=0, stdout=json.dumps(audio_only), stderr="")
        with patch("ffprobe_validate.subprocess.run", return_value=result):
            metadata = probe_source_media(self.media, self.binary)
        self.assertFalse(metadata["has_video"])
        self.assertTrue(metadata["has_audio"])

    def test_source_probe_rejects_no_media_stream_invalid_audio_and_duration(self):
        empty = {"format": {"duration": "2", "size": str(self.media.stat().st_size)}, "streams": []}
        result = SimpleNamespace(returncode=0, stdout=json.dumps(empty), stderr="")
        with patch("ffprobe_validate.subprocess.run", return_value=result):
            with self.assertRaisesRegex(FFprobeValidationError, "audio or video"):
                probe_source_media(self.media, self.binary)
        invalid_audio = {
            "format": {"duration": "2", "size": str(self.media.stat().st_size)},
            "streams": [{"codec_type": "audio", "sample_rate": "bad", "channels": 2}],
        }
        result = SimpleNamespace(returncode=0, stdout=json.dumps(invalid_audio), stderr="")
        with patch("ffprobe_validate.subprocess.run", return_value=result):
            with self.assertRaisesRegex(FFprobeValidationError, "audio stream metadata"):
                probe_source_media(self.media, self.binary)
        with patch("ffprobe_validate.subprocess.run", return_value=SimpleNamespace(
            returncode=0, stdout=json.dumps(self.valid), stderr=""
        )):
            with self.assertRaisesRegex(FFprobeValidationError, "duration"):
                probe_source_media(self.media, self.binary, max_duration_ms=1000)

if __name__ == "__main__":
    unittest.main()
