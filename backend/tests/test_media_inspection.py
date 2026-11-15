import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from media_inspection import MediaInspector, MediaInspectionError


class MediaInspectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "clip.mp4"
        self.path.write_bytes(b"test fixture bytes")

    def tearDown(self):
        self.tmp.cleanup()

    def runner_for(self, payload, returncode=0, stderr=""):
        def runner(args, **kwargs):
            self.assertIn("-show_entries", args)
            self.assertEqual(kwargs["timeout"], 30)
            return SimpleNamespace(returncode=returncode, stdout=json.dumps(payload),
                                   stderr=stderr)
        return runner

    def test_inspects_actual_dimensions_duration_codecs_and_audio_stream(self):
        inspector = MediaInspector(analyze_signals=False, runner=self.runner_for({
            "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2",
                       "duration": "29.75", "size": "123456"},
            "streams": [
                {"index": 0, "codec_type": "video", "codec_name": "h264",
                 "width": 1080, "height": 1920},
                {"index": 1, "codec_type": "audio", "codec_name": "aac",
                 "sample_rate": "48000", "channels": 2},
            ],
        }))
        report = inspector.inspect(self.path)
        self.assertEqual(report["status"], "inspected")
        self.assertEqual(report["inspection_method"], "ffprobe_file_bytes")
        self.assertEqual(report["width"], 1080)
        self.assertEqual(report["height"], 1920)
        self.assertAlmostEqual(report["duration_seconds"], 29.75)
        self.assertTrue(report["audio_track_present"])
        self.assertEqual(report["video_codec"], "h264")
        self.assertFalse(report["subtitle_stream_present"])

    def test_extracts_text_subtitle_stream_with_bounded_ffmpeg_output(self):
        probe = {
            "format": {"format_name": "mp4", "duration": "30", "size": "123456"},
            "streams": [
                {"index": 0, "codec_type": "video", "codec_name": "h264",
                 "width": 1080, "height": 1920},
                {"index": 1, "codec_type": "audio", "codec_name": "aac"},
                {"index": 2, "codec_type": "subtitle", "codec_name": "mov_text"},
            ],
        }
        calls = []
        def runner(args, **kwargs):
            calls.append((args, kwargs))
            if args[0] == "ffprobe":
                return SimpleNamespace(returncode=0, stdout=json.dumps(probe), stderr="")
            return SimpleNamespace(
                returncode=0,
                stdout=("1\\n00:00:00,000 --> 00:00:02,000\\n"
                        "The human brain predicts what happens next.\\n\\n"
                        "2\\n00:00:02,000 --> 00:00:04,000\\n"
                        "Patterns help the brain learn.\\n"),
                stderr="",
            )
        report = MediaInspector(analyze_signals=False, runner=runner).inspect(self.path)
        self.assertTrue(report["subtitle_stream_present"])
        self.assertEqual(report["subtitle_extraction"]["status"], "extracted")
        self.assertIn("The human brain predicts", report["subtitle_text"])
        self.assertEqual(len(calls), 2)
        args, kwargs = calls[1]
        self.assertIn("0:s:0", args)
        self.assertIn("-fs", args)
        self.assertIn("2097152", args)
        self.assertEqual(kwargs["timeout"], 90)

    def test_subtitle_extraction_failure_is_reported_without_failing_probe(self):
        probe = {
            "format": {"format_name": "mp4", "duration": "30", "size": "123456"},
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920},
                {"codec_type": "subtitle", "codec_name": "mov_text"},
            ],
        }
        def runner(args, **kwargs):
            if args[0] == "ffprobe":
                return SimpleNamespace(returncode=0, stdout=json.dumps(probe), stderr="")
            return SimpleNamespace(returncode=1, stdout="", stderr="decoder unavailable")
        report = MediaInspector(analyze_signals=False, runner=runner).inspect(self.path)
        self.assertEqual(report["status"], "inspected")
        self.assertEqual(report["subtitle_extraction"]["status"], "failed")
        self.assertIsNone(report["subtitle_text"])

    def test_analyzes_black_frames_and_audio_silence_as_review_warnings(self):
        probe = {
            "format": {"format_name": "mp4", "duration": "30", "size": "123456"},
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920},
                {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000", "channels": 2},
            ],
        }
        calls = []
        def runner(args, **kwargs):
            calls.append(args)
            if args[0] == "ffprobe":
                return SimpleNamespace(returncode=0, stdout=json.dumps(probe), stderr="")
            if "-vf" in args:
                return SimpleNamespace(
                    returncode=0, stdout="",
                    stderr="black_start:0 black_end:2.5 black_duration:2.5",
                )
            return SimpleNamespace(
                returncode=0, stdout="",
                stderr=("silence_start: 0\\nsilence_end: 2.1 | silence_duration: 2.1\\n"
                        "silence_start: 28.0"),
            )
        report = MediaInspector(runner=runner).inspect(self.path)
        signals = report["signal_analysis"]
        self.assertEqual(signals["status"], "analyzed")
        self.assertEqual(len(signals["black_segments"]), 1)
        self.assertEqual(len(signals["silence_segments"]), 2)
        self.assertIn("black_frame_segment_at_least_2_seconds_detected",
                      signals["signal_warnings"])
        self.assertIn("audio_starts_with_extended_silence", signals["signal_warnings"])
        self.assertIn("audio_ends_with_extended_silence", signals["signal_warnings"])
        self.assertEqual(len(calls), 3)
        self.assertIn("-vf", calls[1])
        self.assertIn("-af", calls[2])

    def test_rejects_media_without_video_stream(self):
        inspector = MediaInspector(runner=self.runner_for({
            "format": {"format_name": "mp4", "duration": "10", "size": "123"},
            "streams": [{"codec_type": "audio", "codec_name": "aac"}],
        }))
        with self.assertRaisesRegex(MediaInspectionError, "no video stream"):
            inspector.inspect(self.path)

    def test_rejects_non_mp4_container(self):
        inspector = MediaInspector(runner=self.runner_for({
            "format": {"format_name": "matroska,webm", "duration": "10", "size": "123"},
            "streams": [{"codec_type": "video", "codec_name": "vp9",
                         "width": 1080, "height": 1920}],
        }))
        with self.assertRaisesRegex(MediaInspectionError, "MP4-family"):
            inspector.inspect(self.path)

    def test_rejects_invalid_probe_and_missing_file(self):
        inspector = MediaInspector(runner=self.runner_for({}, returncode=1, stderr="invalid data"))
        with self.assertRaisesRegex(MediaInspectionError, "rejected"):
            inspector.inspect(self.path)
        with self.assertRaisesRegex(MediaInspectionError, "missing"):
            inspector.inspect(Path(self.tmp.name) / "missing.mp4")


if __name__ == "__main__":
    unittest.main()
