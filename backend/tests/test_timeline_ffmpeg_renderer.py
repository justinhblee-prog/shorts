import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from timeline_edl import EDLValidationError, validate_edl
from timeline_ffmpeg_renderer import (
    RenderCancelled, TimelineFFmpegRenderer, TimelineRenderError,
    run_bounded_process,
)


class TimelineFFmpegRendererTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.staging = self.root / "staging"
        self.staging.mkdir()
        self.assets = {
            "asset_video": self.root / "video.blob",
            "asset_audio": self.root / "audio.blob",
        }
        for path in self.assets.values():
            path.write_bytes(b"trusted-media-fixture")
        self.ffmpeg = self.root / "ffmpeg"
        self.ffprobe = self.root / "ffprobe"
        self.ffmpeg.write_bytes(b"fixture-binary")
        self.ffprobe.write_bytes(b"fixture-binary")
        self.font = self.root / "font.ttf"
        self.font.write_bytes(b"font-fixture")
        self.commands = []

        def resolver(workspace_id, principal_id, asset_id):
            self.assertEqual(workspace_id, "ws_demo")
            self.assertEqual(principal_id, "alice")
            path = self.assets[asset_id]
            return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

        def runner(argv, *, timeout_seconds, stop_event):
            self.commands.append(argv)
            Path(argv[-1]).write_bytes(b"encoded-media-fixture")
            return {"returncode": 0}

        self.resolver = resolver
        self.runner = runner
        self.source_probe = patch(
            "timeline_ffmpeg_renderer.probe_source_media",
            return_value={"duration_ms": 12000, "has_video": True, "has_audio": True},
        )
        self.source_probe.start()
        self.addCleanup(self.source_probe.stop)
        self.renderer = TimelineFFmpegRenderer(
            self.staging, resolver, self.ffmpeg, self.ffprobe,
            width=720, height=1280, fps=30, process_runner=runner,
        )
        self.payload = {
            "snapshot_id": "edl_" + "a" * 32,
            "snapshot_sha256": "",
            "creator_principal_id": "alice",
            "edl": {
                "schema": "nexus-edit-decision-list", "version": 1,
                "timebase": "milliseconds",
                "clips": [{
                    "id": "clip1", "type": "video", "start_ms": 0,
                    "end_ms": 5000, "asset_id": "asset_video",
                    "source_in_ms": 1000, "source_out_ms": 6000,
                }],
                "audio_tracks": [{
                    "id": "music1", "asset_id": "asset_audio", "start_ms": 0,
                    "source_in_ms": 500, "source_out_ms": 5500,
                    "gain": 0.3, "fade_in_ms": 200, "fade_out_ms": 300,
                }],
            },
        }
        self._rehash(self.payload)

    @staticmethod
    def _rehash(payload):
        normalized = validate_edl(payload["edl"])
        canonical = json.dumps(
            normalized, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        payload["snapshot_sha256"] = hashlib.sha256(canonical).hexdigest()


    @staticmethod
    def _rehash_legacy(payload):
        normalized = validate_edl(payload["edl"])
        normalized.pop("audio_tracks", None)
        canonical = json.dumps(
            normalized, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        payload["snapshot_sha256"] = hashlib.sha256(canonical).hexdigest()

    def tearDown(self):
        self.temp.cleanup()

    def test_renders_video_mixes_audio_muxes_and_probes_final_mp4(self):
        probe = {
            "duration_ms": 5000, "byte_size": 23,
            "video_streams": [{"width": 720, "height": 1280, "codec": "h264"}],
            "audio_streams": 1, "audio_codecs": ["aac"],
        }
        with patch("timeline_ffmpeg_renderer.probe_media", return_value=probe) as mocked:
            result = self.renderer(
                self.payload, stop_event=threading.Event(),
                workspace_id="ws_demo", principal_id="alice",
            )
        self.assertTrue(Path(result["staged_path"]).is_file())
        self.assertEqual(result["duration_ms"], 5000)
        self.assertEqual(len(self.commands), 3)
        video_graph = self.commands[0][self.commands[0].index("-filter_complex") + 1]
        audio_graph = self.commands[1][self.commands[1].index("-filter_complex") + 1]
        self.assertNotIn("xfade=", video_graph)
        self.assertIn("[0:v:0]", video_graph)
        self.assertIn("-filter_threads", self.commands[0])
        self.assertIn("-threads", self.commands[0])
        self.assertEqual(self.commands[0][self.commands[0].index("-fs") + 1], str(self.renderer.max_output_bytes))
        self.assertIn("scale=720:1280", video_graph)
        self.assertIn("atrim=start=0.500:duration=5.000", audio_graph)
        self.assertIn("amix=inputs=1", audio_graph)
        self.assertIn("-c:v", self.commands[2])
        self.assertEqual(self.commands[0].count("-protocol_whitelist"), 1)
        self.assertIn("file,pipe", self.commands[0])
        self.assertEqual(self.commands[2].count("-protocol_whitelist"), 2)
        self.assertEqual(self.commands[2][self.commands[2].index("-fs") + 1], str(self.renderer.max_output_bytes))
        self.assertEqual(self.commands[2][-1], result["staged_path"])
        mocked.assert_called_once()
        self.assertEqual(mocked.call_args.kwargs["require_audio"], True)

    def test_renders_video_only_when_no_audio_tracks(self):
        self.payload["edl"]["audio_tracks"] = []
        self._rehash(self.payload)
        probe = {
            "duration_ms": 5000, "byte_size": 23,
            "video_streams": [{"width": 720, "height": 1280, "codec": "h264"}],
            "audio_streams": 0, "audio_codecs": [],
        }
        with patch("timeline_ffmpeg_renderer.probe_media", return_value=probe):
            result = self.renderer(
                self.payload, stop_event=threading.Event(),
                workspace_id="ws_demo", principal_id="alice",
            )
        self.assertTrue(Path(result["staged_path"]).is_file())
        self.assertEqual(len(self.commands), 1)

    def test_rejects_titles_gaps_untrusted_assets_and_audio_past_end(self):
        title_only = json.loads(json.dumps(self.payload))
        title_only["edl"]["clips"] = [{
            "id": "title1", "type": "title", "start_ms": 0,
            "end_ms": 5000, "text": "Title without video",
        }]
        title_only["edl"]["audio_tracks"] = []
        self._rehash(title_only)
        with self.assertRaisesRegex(TimelineRenderError, "at least one video clip"):
            self.renderer(title_only, stop_event=threading.Event(), workspace_id="ws_demo", principal_id="alice")

        overlap = json.loads(json.dumps(self.payload))
        overlap["edl"]["clips"].append({
            "id": "clip2", "type": "video", "start_ms": 4500,
            "end_ms": 6500, "asset_id": "asset_video",
            "source_in_ms": 0, "source_out_ms": 2000,
        })
        self._rehash(overlap)
        with self.assertRaisesRegex(TimelineRenderError, "overlap"):
            self.renderer(overlap, stop_event=threading.Event(), workspace_id="ws_demo", principal_id="alice")

        escaped = json.loads(json.dumps(self.payload))
        escaped["edl"]["clips"][0]["asset_id"] = "asset_escape"
        self._rehash(escaped)
        with self.assertRaises(KeyError):
            self.renderer(escaped, stop_event=threading.Event(), workspace_id="ws_demo", principal_id="alice")

        past_end = json.loads(json.dumps(self.payload))
        past_end["edl"]["audio_tracks"][0]["source_out_ms"] = 7000
        self._rehash(past_end)
        with self.assertRaisesRegex(TimelineRenderError, "extends beyond"):
            self.renderer(past_end, stop_event=threading.Event(), workspace_id="ws_demo", principal_id="alice")

    def test_renders_internal_and_trailing_black_gaps_to_explicit_project_duration(self):
        extended = json.loads(json.dumps(self.payload))
        extended["edl"]["clips"].append({
            "id": "clip2", "type": "video", "start_ms": 7000,
            "end_ms": 9000, "asset_id": "asset_video",
            "source_in_ms": 6000, "source_out_ms": 8000,
        })
        extended["edl"]["project_duration_ms"] = 11000
        self._rehash(extended)
        probe = {
            "duration_ms": 11000, "byte_size": 23,
            "video_streams": [{"width": 720, "height": 1280, "codec": "h264"}],
            "audio_streams": 1, "audio_codecs": ["aac"],
        }
        with patch("timeline_ffmpeg_renderer.probe_media", return_value=probe):
            result = self.renderer(
                extended, stop_event=threading.Event(),
                workspace_id="ws_demo", principal_id="alice",
            )
        graph = self.commands[0][self.commands[0].index("-filter_complex") + 1]
        self.assertEqual(graph.count("color=c=black"), 2)
        self.assertIn("concat=n=3:v=1:a=0", graph)
        self.assertIn("concat=n=2:v=1:a=0", graph)
        self.assertEqual(result["duration_ms"], 11000)
        self.assertIn("11.000", self.commands[0])

    def test_renders_declared_crossfade_with_absolute_timeline_offset(self):
        transitioned = json.loads(json.dumps(self.payload))
        transitioned["edl"]["clips"].append({
            "id": "clip2", "type": "video", "start_ms": 3000,
            "end_ms": 8000, "asset_id": "asset_video",
            "source_in_ms": 6000, "source_out_ms": 11000,
        })
        transitioned["edl"]["transitions"] = [{
            "id": "xfade1", "type": "crossfade",
            "from_clip_id": "clip1", "to_clip_id": "clip2",
            "duration_ms": 2000,
        }]
        self._rehash(transitioned)
        probe = {
            "duration_ms": 8000, "byte_size": 23,
            "video_streams": [{"width": 720, "height": 1280, "codec": "h264"}],
            "audio_streams": 1, "audio_codecs": ["aac"],
        }
        with patch("timeline_ffmpeg_renderer.probe_media", return_value=probe):
            result = self.renderer(
                transitioned, stop_event=threading.Event(),
                workspace_id="ws_demo", principal_id="alice",
            )
        graph = self.commands[0][self.commands[0].index("-filter_complex") + 1]
        self.assertIn("xfade=transition=fade:duration=2.000:offset=3.000", graph)
        self.assertEqual(result["duration_ms"], 8000)
        self.assertIn("8.000", self.commands[0])
        self.assertEqual(len(self.commands), 3)

    def test_renders_title_overlay_from_bounded_utf8_text_file(self):
        titled = json.loads(json.dumps(self.payload))
        titled["edl"]["clips"].append({
            "id": "title1", "type": "title", "start_ms": 1000,
            "end_ms": 3000, "text": "Safe title 100%",
        })
        self._rehash(titled)
        renderer = TimelineFFmpegRenderer(
            self.staging, self.resolver, self.ffmpeg, self.ffprobe,
            width=720, height=1280, fps=30, process_runner=self.runner,
            font_path=self.font,
        )
        probe = {
            "duration_ms": 5000, "byte_size": 23,
            "video_streams": [{"width": 720, "height": 1280, "codec": "h264"}],
            "audio_streams": 1, "audio_codecs": ["aac"],
        }
        with patch("timeline_ffmpeg_renderer.probe_media", return_value=probe):
            result = renderer(
                titled, stop_event=threading.Event(),
                workspace_id="ws_demo", principal_id="alice",
            )
        self.assertTrue(Path(result["staged_path"]).is_file())
        video_graph = self.commands[0][self.commands[0].index("-filter_complex") + 1]
        self.assertIn("drawtext=", video_graph)
        self.assertIn("expansion=none", video_graph)
        self.assertIn("textfile=", video_graph)
        self.assertIn("between(t,1.000,3.000)", video_graph)


    def test_rejects_asset_checksum_mismatch_and_lease_cancellation(self):
        bad = TimelineFFmpegRenderer(
            self.staging, lambda *_: {"path": str(self.assets["asset_video"]), "sha256": "0" * 64},
            self.ffmpeg, self.ffprobe, process_runner=lambda *a, **k: self.fail("must not run"),
        )
        with self.assertRaisesRegex(TimelineRenderError, "checksum"):
            bad(self.payload, stop_event=threading.Event(), workspace_id="ws_demo", principal_id="alice")

        stopped = threading.Event()
        stopped.set()
        with self.assertRaises(RenderCancelled):
            self.renderer(self.payload, stop_event=stopped, workspace_id="ws_demo", principal_id="alice")
        self.assertEqual(self.commands, [])

    def test_bounded_runner_executes_without_shell(self):
        import sys
        result = run_bounded_process(
            [sys.executable, "-c", "print('ok')"], timeout_seconds=5,
            stop_event=threading.Event(),
        )
        self.assertEqual(result["returncode"], 0)


    def test_rejects_edl_payload_that_does_not_match_snapshot_digest(self):
        invalid = json.loads(json.dumps(self.payload))
        invalid["edl"]["clips"][0]["asset_id"] = "asset_other"
        with self.assertRaisesRegex(TimelineRenderError, "snapshot digest"):
            self.renderer(
                invalid, stop_event=threading.Event(),
                workspace_id="ws_demo", principal_id="alice",
            )


    def test_rejects_aggregate_input_bytes_above_configured_budget(self):
        limited = TimelineFFmpegRenderer(
            self.staging, lambda *args: {
                "path": str(self.assets["asset_video"]),
                "sha256": hashlib.sha256(self.assets["asset_video"].read_bytes()).hexdigest(),
            },
            self.ffmpeg, self.ffprobe, max_input_bytes=10,
            process_runner=lambda *args, **kwargs: self.fail("FFmpeg must not run"),
        )
        with self.assertRaisesRegex(TimelineRenderError, "aggregate source assets"):
            limited(
                self.payload, stop_event=threading.Event(),
                workspace_id="ws_demo", principal_id="alice",
            )


    def test_accepts_legacy_edl_v1_snapshot_without_audio_tracks_field(self):
        legacy = json.loads(json.dumps(self.payload))
        legacy["edl"].pop("audio_tracks")
        self._rehash_legacy(legacy)
        probe = {
            "duration_ms": 5000, "byte_size": 23,
            "video_streams": [{"width": 720, "height": 1280, "codec": "h264"}],
            "audio_streams": 0, "audio_codecs": [],
        }
        with patch("timeline_ffmpeg_renderer.probe_media", return_value=probe):
            result = self.renderer(
                legacy, stop_event=threading.Event(),
                workspace_id="ws_demo", principal_id="alice",
            )
        self.assertTrue(Path(result["staged_path"]).is_file())
        self.assertEqual(len(self.commands), 1)


if __name__ == "__main__":
    unittest.main()
