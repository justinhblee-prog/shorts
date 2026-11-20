import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from ffmpeg_edl_renderer import EDLFFmpegRenderer, EDLRenderError, build_video_argv


class FakeProcess:
    def __init__(self, argv, **kwargs):
        Path(argv[-1]).write_bytes(b"fixture-output")
        self.returncode = 0
    def poll(self):
        return self.returncode
    def wait(self, timeout=None):
        return self.returncode
    def terminate(self):
        self.returncode = -15
    def kill(self):
        self.returncode = -9


class EDLFFmpegRendererTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.binary = self.root / "ffmpeg"
        self.binary.write_bytes(b"fixture executable")
        self.video = self.root / "source.mp4"
        self.video.write_bytes(b"fixture source")
        self.audio = self.root / "music.wav"
        self.audio.write_bytes(b"fixture audio")
        self.edl = {
            "schema": "nexus-edit-decision-list",
            "version": 1,
            "timebase": "milliseconds",
            "clips": [
                {"id": "clip1", "type": "video", "asset_id": "asset1",
                 "start_ms": 0, "end_ms": 2000,
                 "source_in_ms": 100, "source_out_ms": 2100},
                {"id": "clip2", "type": "video", "asset_id": "asset2",
                 "start_ms": 2000, "end_ms": 4000,
                 "source_in_ms": 0, "source_out_ms": 2000},
            ],
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_builds_normalized_multi_clip_video_graph(self):
        output = self.root / "out.mp4"
        argv, duration = build_video_argv(
            self.edl, {"asset1": self.video, "asset2": self.video},
            output, ffmpeg_path=str(self.binary),
        )
        self.assertEqual(duration, 4000)
        self.assertEqual(argv.count("-i"), 2)
        graph = argv[argv.index("-filter_complex") + 1]
        self.assertIn("concat=n=2:v=1:a=0", graph)
        self.assertIn("trim=start=0.100:duration=2.000", graph)
        self.assertIn("-an", argv)

    def test_renders_black_gaps_and_rejects_titles_overlaps_and_unresolved_assets(self):
        title = dict(self.edl)
        title["clips"] = [
            self.edl["clips"][0],
            {"id": "title1", "type": "title", "start_ms": 2000,
             "end_ms": 2500, "text": "hello: world, [safe]"},
            dict(self.edl["clips"][1], start_ms=2500, end_ms=4500),
        ]
        with self.assertRaisesRegex(EDLRenderError, "configured trusted font"):
            build_video_argv(title, {"asset1": self.video, "asset2": self.video},
                             self.root / "out.mp4", ffmpeg_path=str(self.binary))
        font = self.root / "font.ttf"
        font.write_bytes(b"fixture font")
        title_argv, title_duration = build_video_argv(
            title, {"asset1": self.video, "asset2": self.video},
            self.root / "title.mp4", ffmpeg_path=str(self.binary),
            title_font_path=str(font),
        )
        self.assertEqual(title_duration, 4500)
        title_graph = title_argv[title_argv.index("-filter_complex") + 1]
        self.assertIn("drawtext=fontfile=", title_graph)
        self.assertIn("expansion=none", title_graph)
        self.assertIn(r"hello\: world\, \[safe\]", title_graph)
        gap = dict(self.edl)
        gap["clips"] = [self.edl["clips"][0], dict(self.edl["clips"][1], start_ms=3000, end_ms=5000)]
        gap_argv, gap_duration = build_video_argv(
            gap, {"asset1": self.video, "asset2": self.video},
            self.root / "gap.mp4", ffmpeg_path=str(self.binary),
        )
        self.assertEqual(gap_duration, 5000)
        self.assertIn("color=c=black:s=1080x1920:r=30", gap_argv)
        self.assertIn("concat=n=3:v=1:a=0", gap_argv[gap_argv.index("-filter_complex") + 1])
        overlap = dict(self.edl)
        overlap["clips"] = [self.edl["clips"][0],
            dict(self.edl["clips"][1], start_ms=1000, end_ms=3000)]
        with self.assertRaises(EDLRenderError):
            build_video_argv(overlap, {"asset1": self.video, "asset2": self.video},
                             self.root / "out.mp4", ffmpeg_path=str(self.binary))
        with self.assertRaises(EDLRenderError):
            build_video_argv(self.edl, {"asset1": self.video}, self.root / "out.mp4",
                             ffmpeg_path=str(self.binary))

    def test_renderer_runs_video_and_audio_mix_then_returns_staged_mp4(self):
        renderer = EDLFFmpegRenderer(
            self.root / "staging", str(self.binary),
            lambda workspace, principal, asset: self.video,
            audio_tracks_resolver=lambda payload: [
                {"path": str(self.audio), "duration_ms": 4000, "gain": 0.5}
            ],
        )
        with patch("ffmpeg_edl_renderer.subprocess.Popen", side_effect=FakeProcess) as popen:
            result = renderer(
                {"workspace_id": "ws1", "creator_principal_id": "principal1", "edl": self.edl}, threading.Event()
            )
        self.assertTrue(Path(result["staged_path"]).is_file())
        self.assertEqual(result["duration_ms"], 4000)
        self.assertEqual(popen.call_count, 3)
        self.assertTrue(all(call.kwargs["shell"] is False for call in popen.call_args_list))
        self.assertTrue(Path(result["staged_path"]).is_relative_to(self.root / "staging"))


    def test_mixes_source_clip_audio_using_source_trim_and_timeline_offsets(self):
        ffprobe = self.root / "ffprobe"
        ffprobe.write_bytes(b"fixture ffprobe")
        renderer = EDLFFmpegRenderer(
            self.root / "staging", str(self.binary),
            lambda workspace, principal, asset: self.video,
            ffprobe_path=str(ffprobe),
        )
        with patch("ffmpeg_edl_renderer.has_audio_stream", return_value=True), \
             patch("ffmpeg_edl_renderer.subprocess.Popen", side_effect=FakeProcess) as popen:
            result = renderer(
                {"workspace_id": "ws1", "creator_principal_id": "principal1",
                 "edl": self.edl}, threading.Event()
            )
        self.assertTrue(Path(result["staged_path"]).is_file())
        self.assertEqual(popen.call_count, 3)
        mix_argv = popen.call_args_list[1].args[0]
        graph = mix_argv[mix_argv.index("-filter_complex") + 1]
        self.assertIn("atrim=start=0.100:duration=2.000", graph)
        self.assertIn("adelay=0|0", graph)
        self.assertIn("adelay=2000|2000", graph)

    def test_renderer_cancels_before_start_when_lease_is_lost(self):
        renderer = EDLFFmpegRenderer(
            self.root / "staging", str(self.binary),
            lambda workspace, asset: self.video,
        )
        stopped = threading.Event()
        stopped.set()
        with patch("ffmpeg_edl_renderer.subprocess.Popen") as popen:
            with self.assertRaisesRegex(EDLRenderError, "lease was lost"):
                renderer({"workspace_id": "ws1", "edl": self.edl}, stopped)
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
