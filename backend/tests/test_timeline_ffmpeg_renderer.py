import io
import json
import os
import stat
import tempfile
import threading
import unittest
from pathlib import Path

from timeline_ffmpeg_renderer import (
    TimelineFFmpegError, TimelineFFmpegRenderer, build_timeline_ffmpeg_argv,
)


class FixtureAssets:
    def __init__(self, payloads):
        self.payloads = payloads
        self.opened = []

    def open_clean_asset(self, workspace_id, principal_id, asset_id):
        if workspace_id != "ws_render" or principal_id != "alice":
            raise AssertionError("renderer used an unexpected workspace principal")
        self.opened.append(asset_id)
        return io.BytesIO(self.payloads[asset_id])


class TimelineFFmpegRendererTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.ffmpeg = self.root / "ffmpeg"
        self.ffprobe = self.root / "ffprobe"
        self.font = self.root / "font.ttf"
        self.font.write_bytes(b"font-fixture")
        self.ffmpeg.write_text(
            "#!/usr/bin/env python3\n"
            "import pathlib, sys\n"
            "pathlib.Path(sys.argv[-1]).write_bytes(b'encoded-mp4-fixture')\n",
            encoding="utf-8",
        )
        self.ffprobe.write_text(
            "#!/usr/bin/env python3\n"
            "import json, pathlib, sys\n"
            "p=pathlib.Path(sys.argv[-1])\n"
            "if p.suffix == '.mp4':\n"
            " s=[{'codec_type':'video','codec_name':'h264','width':1080,'height':1920},"
            "{'codec_type':'audio','codec_name':'aac','sample_rate':'48000','channels':2}]\n"
            "elif 'audio' in p.name: s=[{'codec_type':'audio','codec_name':'aac'}]\n"
            "else: s=[{'codec_type':'video','codec_name':'h264','width':1920,'height':1080}]\n"
            "d={'format':{'duration':'5.0','size':str(p.stat().st_size)},'streams':s}\n"
            "print(json.dumps(d))\n",
            encoding="utf-8",
        )
        self.ffmpeg.chmod(self.ffmpeg.stat().st_mode | stat.S_IXUSR)
        self.ffprobe.chmod(self.ffprobe.stat().st_mode | stat.S_IXUSR)
        self.staging = self.root / "staging"
        self.staging.mkdir()
        self.assets = FixtureAssets({
            "asset_video": b"video-source-fixture",
            "asset_audio": b"audio-source-fixture",
        })
        self.renderer = TimelineFFmpegRenderer(
            self.assets, self.staging, self.ffmpeg, self.ffprobe,
            font_path=self.font, timeout_seconds=20,
        )
        self.edl = {
            "schema": "nexus-edit-decision-list", "version": 1,
            "timebase": "milliseconds",
            "clips": [
                {"id": "v1", "type": "video", "start_ms": 0, "end_ms": 5000,
                 "asset_id": "asset_video", "source_in_ms": 0, "source_out_ms": 5000},
                {"id": "a1", "type": "audio", "start_ms": 0, "end_ms": 5000,
                 "asset_id": "asset_audio", "source_in_ms": 0, "source_out_ms": 5000,
                 "gain": 0.5, "fade_in_ms": 250, "fade_out_ms": 500},
                {"id": "t1", "type": "title", "start_ms": 1000, "end_ms": 3000,
                 "text": "Launch 100%"},
            ],
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_builds_video_title_and_audio_mapping_without_shell(self):
        title_file = self.root / "title.txt"
        title_file.write_text("safe title", encoding="utf-8")
        audio_file = self.root / "mix.m4a"
        audio_file.write_bytes(b"audio")
        argv = build_timeline_ffmpeg_argv(
            self.edl, {"asset_video": self.root / "video.media"},
            self.root / "out.mp4", ffmpeg_path=str(self.ffmpeg),
            font_path=self.font, audio_mix_path=audio_file,
            title_files={"t1": title_file},
        )
        graph = argv[argv.index("-filter_complex") + 1]
        self.assertIn("overlay=", graph)
        self.assertIn("drawtext=", graph)
        self.assertIn("expansion=none", graph)
        self.assertIn("between(t,1.000,3.000)", graph)
        self.assertIn("-map", argv)
        self.assertIn("1:a:0", argv)
        self.assertEqual(argv[0], str(self.ffmpeg))

    def test_renders_edl_to_staging_and_mixes_audio(self):
        result = self.renderer({
            "workspace_id": "ws_render", "principal_id": "alice", "edl": self.edl,
        }, stop_event=threading.Event())
        path = Path(result["staged_path"])
        self.assertTrue(path.is_file())
        self.assertEqual(path.parent, self.staging)
        self.assertRegex(path.name, r"^rart_[a-f0-9]{32}\.mp4$")
        self.assertEqual(result["probe"]["width"], 1080)
        self.assertEqual(result["probe"]["height"], 1920)
        self.assertEqual(result["probe"]["audio_streams"], 1)
        self.assertCountEqual(self.assets.opened, ["asset_video", "asset_audio"])
        self.assertEqual(len(list(self.staging.glob(".timeline-work-*"))), 0)

    def test_rejects_source_trim_past_real_probed_duration(self):
        edl = json.loads(json.dumps(self.edl))
        edl["clips"][0]["source_out_ms"] = 6000
        edl["clips"][0]["end_ms"] = 6000
        edl["clips"][1]["end_ms"] = 6000
        result = None
        with self.assertRaisesRegex(TimelineFFmpegError, "source trim"):
            self.renderer({
                "workspace_id": "ws_render", "principal_id": "alice", "edl": edl,
            }, stop_event=threading.Event())
        self.assertEqual(list(self.staging.glob("rart_*.mp4")), [])

    def test_rejects_missing_worker_principal_and_lost_lease(self):
        with self.assertRaisesRegex(TimelineFFmpegError, "workspace owner"):
            self.renderer({"workspace_id": "ws_render", "edl": self.edl},
                          stop_event=threading.Event())
        stopped = threading.Event()
        stopped.set()
        with self.assertRaisesRegex(TimelineFFmpegError, "cancelled"):
            self.renderer({
                "workspace_id": "ws_render", "principal_id": "alice", "edl": self.edl,
            }, stop_event=stopped)
        self.assertEqual(list(self.staging.glob("rart_*.mp4")), [])


if __name__ == "__main__":
    unittest.main()
