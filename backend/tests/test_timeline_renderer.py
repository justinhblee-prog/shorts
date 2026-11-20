import hashlib
import os
import signal
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from timeline_edl import SCHEMA
from timeline_renderer import TimelineRenderer, TimelineRenderError, TimelineRenderCancelled


class FakeInspector:
    def __init__(self, report=None, error=None):
        self.report = report or {
            "status": "inspected",
            "width": 1080,
            "height": 1920,
            "duration_seconds": 5.0,
            "audio_track_present": False,
        }
        self.error = error

    def inspect(self, path):
        if self.error:
            raise self.error
        return dict(self.report)


class TimelineRendererTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.asset = self.root / "source.mp4"
        self.asset.write_bytes(b"trusted source bytes")
        self.edl = {
            "schema": SCHEMA,
            "version": 1,
            "timebase": "milliseconds",
            "clips": [{
                "id": "clip-1",
                "type": "video",
                "start_ms": 0,
                "end_ms": 5000,
                "asset_id": "asset_1",
                "source_in_ms": 1000,
                "source_out_ms": 6000,
            }],
        }
        self.font = self.root / "NotoSansCJK-Regular.ttc"
        self.font.write_bytes(b"font fixture")
        self.calls = []

        def runner(args, **kwargs):
            self.calls.append((args, kwargs))
            Path(args[-1]).write_bytes(b"rendered mp4 fixture")
            return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

        self.runner = runner
        self.renderer = TimelineRenderer(
            media_root=self.root,
            timeout_seconds=30,
            max_asset_bytes=1024,
            max_output_bytes=1024 * 1024,
            runner=runner,
            inspector=FakeInspector(),
            font_path=self.font,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_renders_to_atomic_workspace_local_output_and_hashes_bytes(self):
        result = self.renderer.render(
            self.edl, {"asset_1": self.asset}, output_dir=self.root / "renders"
        )
        output = self.root / result["media_path"]
        self.assertTrue(output.is_file())
        self.assertEqual(result["sha256"], hashlib.sha256(output.read_bytes()).hexdigest())
        self.assertEqual(result["status"], "rendered_unreviewed")
        self.assertEqual(result["width"], 1080)
        self.assertEqual(result["height"], 1920)
        args, kwargs = self.calls[0]
        self.assertFalse(kwargs["shell"])
        self.assertEqual(kwargs["timeout"], 30)
        self.assertIs(kwargs["stdout"], __import__("subprocess").DEVNULL)
        self.assertIs(kwargs["stderr"], __import__("subprocess").DEVNULL)
        self.assertIn("-nostdin", args)
        self.assertIn("-filter_complex", args)
        self.assertIn("-fs", args)
        self.assertIn("libx264", args)
        self.assertNotIn("shell", args)
        if os.name == "posix":
            self.assertEqual(args[0], "prlimit")
            self.assertIn("--", args)
            self.assertTrue(any(item.startswith("--as=") for item in args))
            self.assertTrue(any(item.startswith("--cpu=") for item in args))

    def test_fails_closed_when_posix_resource_limiter_is_missing(self):
        if os.name != "posix":
            self.skipTest("POSIX resource limits are not available")
        with patch("timeline_renderer.shutil.which", return_value=None):
            with self.assertRaisesRegex(TimelineRenderError, "prlimit is required"):
                self.renderer.render(self.edl, {"asset_1": self.asset})
        self.assertEqual(self.calls, [])

    def test_rejects_asset_path_outside_media_root_before_process_start(self):
        outside = self.root.parent / "outside.mp4"
        outside.write_bytes(b"outside")
        try:
            with self.assertRaisesRegex(TimelineRenderError, "escaped"):
                self.renderer.render(self.edl, {"asset_1": outside})
            self.assertEqual(self.calls, [])
        finally:
            outside.unlink(missing_ok=True)

    def test_rejects_symlink_asset(self):
        link = self.root / "linked.mp4"
        try:
            link.symlink_to(self.asset)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are unavailable")
        with self.assertRaisesRegex(TimelineRenderError, "symlink"):
            self.renderer.render(self.edl, {"asset_1": link})
        self.assertEqual(self.calls, [])

    def test_rejects_unknown_asset_and_oversized_asset(self):
        with self.assertRaisesRegex(TimelineRenderError, "not registered"):
            self.renderer.render(self.edl, {})
        self.asset.write_bytes(b"x" * 2048)
        with self.assertRaisesRegex(TimelineRenderError, "size limit"):
            self.renderer.render(self.edl, {"asset_1": self.asset})
        self.assertEqual(self.calls, [])

    def test_rejects_output_directory_escape_before_creating_it(self):
        outside = self.root.parent / ("outside-render-" + self.root.name)
        try:
            with self.assertRaisesRegex(TimelineRenderError, "escaped"):
                self.renderer.render(self.edl, {"asset_1": self.asset}, output_dir=outside)
            self.assertFalse(outside.exists())
            self.assertEqual(self.calls, [])
        finally:
            if outside.exists():
                import shutil
                shutil.rmtree(outside)

    def test_renders_title_overlay_from_private_text_file_without_filter_interpolation(self):
        payload = {
            **self.edl,
            "clips": [
                self.edl["clips"][0],
                {"id": "title-1", "type": "title", "start_ms": 1000, "end_ms": 3000,
                 "text": "Hello %{metadata}, [drawtext]"},
            ],
        }
        result = self.renderer.render(payload, {"asset_1": self.asset})
        args, kwargs = self.calls[0]
        graph = args[args.index("-filter_complex") + 1]
        self.assertIn("drawtext=fontfile=", graph)
        self.assertIn("expansion=none", graph)
        self.assertIn("textfile=", graph)
        self.assertIn("enable='between(t\\\\,1.000\\\\,3.000)'", graph)
        self.assertNotIn("Hello", graph)
        self.assertTrue((self.root / result["media_path"]).is_file())
        self.assertEqual(list(self.root.glob(".*.title-*.txt")), [])
        self.assertEqual(kwargs["cwd"], str(self.root / "renders"))

    def test_rejects_invalid_edl_and_arbitrary_paths(self):
        payload = {**self.edl, "remote_url": "https://example.invalid/video.mp4"}
        with self.assertRaises(TimelineRenderError):
            self.renderer.render(payload, {"asset_1": self.asset})
        self.assertEqual(self.calls, [])

    def test_audio_is_mapped_only_from_registered_asset_id(self):
        audio = self.root / "voice.m4a"
        audio.write_bytes(b"trusted audio")
        self.renderer.inspector = FakeInspector({
            "status": "inspected", "width": 1080, "height": 1920,
            "duration_seconds": 5.0, "audio_track_present": True,
        })
        result = self.renderer.render(
            self.edl, {"asset_1": self.asset, "voice_1": audio},
            audio_asset_id="voice_1",
        )
        args, _ = self.calls[0]
        self.assertIn("-stream_loop", args)
        self.assertIn("aac", args)
        graph = args[args.index("-filter_complex") + 1]
        self.assertIn("[0:a:0]", graph)
        self.assertIn("[1:a:0]", graph)
        self.assertIn("amix=inputs=2", graph)
        self.assertIn("[mixed]", args)
        self.assertTrue((self.root / result["media_path"]).is_file())

    def test_preserves_source_clip_audio_without_background_asset(self):
        self.renderer.inspector = FakeInspector({
            "status": "inspected", "width": 1080, "height": 1920,
            "duration_seconds": 5.0, "audio_track_present": True,
        })
        self.renderer.render(self.edl, {"asset_1": self.asset})
        args, _ = self.calls[0]
        graph = args[args.index("-filter_complex") + 1]
        self.assertIn("[0:a:0]", graph)
        self.assertIn("concat=n=1:v=0:a=1[outa]", graph)
        self.assertIn("[outa]", args)
        self.assertNotIn("-an", args)

    def test_rejects_title_overlay_outside_video_timeline(self):
        payload = {
            **self.edl,
            "clips": [
                self.edl["clips"][0],
                {"id": "title-1", "type": "title", "start_ms": 4000, "end_ms": 6000,
                 "text": "Out of bounds"},
            ],
        }
        with self.assertRaisesRegex(TimelineRenderError, "inside the rendered video timeline"):
            self.renderer.render(payload, {"asset_1": self.asset})
        self.assertEqual(self.calls, [])

    def test_rejects_gaps_or_overlaps_in_timeline_order(self):
        payload = {
            "schema": SCHEMA, "version": 1, "timebase": "milliseconds",
            "clips": [
                {"id": "clip-1", "type": "video", "start_ms": 0, "end_ms": 5000,
                 "asset_id": "asset_1", "source_in_ms": 0, "source_out_ms": 5000},
                {"id": "clip-2", "type": "video", "start_ms": 6000, "end_ms": 7000,
                 "asset_id": "asset_1", "source_in_ms": 0, "source_out_ms": 1000},
            ],
        }
        with self.assertRaisesRegex(TimelineRenderError, "ordered and contiguous"):
            self.renderer.render(payload, {"asset_1": self.asset})
        self.assertEqual(self.calls, [])

    def test_rejects_combined_assets_over_total_limit(self):
        audio = self.root / "voice.m4a"
        audio.write_bytes(b"trusted audio")
        self.renderer.max_total_asset_bytes = 25
        with self.assertRaisesRegex(TimelineRenderError, "total size limit"):
            self.renderer.render(
                self.edl, {"asset_1": self.asset, "voice_1": audio},
                audio_asset_id="voice_1",
            )
        self.assertEqual(self.calls, [])

    def test_rejects_output_duration_mismatch(self):
        self.renderer.inspector = FakeInspector({
            "status": "inspected", "width": 1080, "height": 1920,
            "duration_seconds": 9.0, "audio_track_present": False,
        })
        with self.assertRaisesRegex(TimelineRenderError, "duration"):
            self.renderer.render(self.edl, {"asset_1": self.asset})
        self.assertEqual(list(self.root.glob(".*.part.mp4")), [])

    def test_rejects_audio_asset_outside_registry(self):
        with self.assertRaisesRegex(TimelineRenderError, "not registered"):
            self.renderer.render(self.edl, {"asset_1": self.asset}, audio_asset_id="remote")
        self.assertEqual(self.calls, [])

    def test_lease_cancellation_terminates_ffmpeg_process_group(self):
        if os.name != "posix":
            self.skipTest("FFmpeg process-group limits require POSIX")
        class FakeProcess:
            pid = 4242
            returncode = None

            def poll(self):
                return self.returncode

            def wait(self, timeout=None):
                self.returncode = -signal.SIGTERM
                return self.returncode

        process = FakeProcess()
        stop_event = threading.Event()
        self.renderer.runner = None
        with (
            patch("timeline_renderer.subprocess.Popen", return_value=process) as popen,
            patch("timeline_renderer.time.sleep", side_effect=lambda delay: stop_event.set()),
            patch("timeline_renderer.os.killpg") as kill_group,
        ):
            with self.assertRaises(TimelineRenderCancelled):
                self.renderer._execute(["prlimit", "--", "ffmpeg"], self.root, stop_event)
        popen.assert_called_once()
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        kill_group.assert_called_once_with(4242, signal.SIGTERM)

    def test_stop_event_cancels_before_ffmpeg_start(self):
        stop_event = __import__("threading").Event()
        stop_event.set()
        with self.assertRaises(TimelineRenderCancelled):
            self.renderer.render(self.edl, {"asset_1": self.asset}, stop_event=stop_event)
        self.assertEqual(self.calls, [])
        self.assertEqual(list(self.root.glob(".*.part.mp4")), [])

    def test_timeout_cleans_partial_output(self):
        def timeout_runner(args, **kwargs):
            Path(args[-1]).write_bytes(b"partial")
            raise __import__("subprocess").TimeoutExpired(args, kwargs["timeout"])
        self.renderer.runner = timeout_runner
        with self.assertRaisesRegex(TimelineRenderError, "time limit"):
            self.renderer.render(self.edl, {"asset_1": self.asset})
        self.assertEqual(list(self.root.glob(".*.part.mp4")), [])

    def test_nonzero_ffmpeg_exit_does_not_adopt_output(self):
        def failed_runner(args, **kwargs):
            Path(args[-1]).write_bytes(b"partial")
            return SimpleNamespace(returncode=1, stdout=b"", stderr=b"secret path")
        self.renderer.runner = failed_runner
        with self.assertRaisesRegex(TimelineRenderError, "status 1"):
            self.renderer.render(self.edl, {"asset_1": self.asset})
        self.assertEqual(list(self.root.glob(".*.part.mp4")), [])

    def test_inspection_failure_removes_partial_artifact(self):
        self.renderer.inspector = FakeInspector(error=RuntimeError("probe failure"))
        with self.assertRaisesRegex(TimelineRenderError, "Source video failed media inspection"):
            self.renderer.render(self.edl, {"asset_1": self.asset})
        self.assertEqual(list(self.root.glob(".*.part.mp4")), [])

    def test_rejects_output_with_wrong_dimensions(self):
        self.renderer.inspector = FakeInspector({
            "status": "inspected", "width": 1920, "height": 1080,
            "duration_seconds": 5, "audio_track_present": False,
        })
        with self.assertRaisesRegex(TimelineRenderError, "dimensions"):
            self.renderer.render(self.edl, {"asset_1": self.asset})
        self.assertEqual(list(self.root.glob(".*.part.mp4")), [])


if __name__ == "__main__":
    unittest.main()
