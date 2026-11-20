import tempfile
import unittest
from pathlib import Path

from timeline_edl import SCHEMA
from timeline_render_plan import RenderPlanError, build_ffmpeg_argv


class TimelineRenderPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.assets = self.root / "assets"
        self.output = self.root / "jobs"
        self.assets.mkdir()
        self.output.mkdir()
        self.source = self.assets / "source.mp4"
        self.source.write_bytes(b"test fixture; argv planning does not inspect media bytes")
        self.edl = {
            "schema": SCHEMA, "version": 1, "timebase": "milliseconds",
            "clips": [
                {"id": "clip-1", "type": "video", "start_ms": 0, "end_ms": 2000,
                 "asset_id": "asset-1", "source_in_ms": 1000, "source_out_ms": 3000},
                {"id": "clip-2", "type": "video", "start_ms": 2000, "end_ms": 4000,
                 "asset_id": "asset-1", "source_in_ms": 4000, "source_out_ms": 6000},
            ],
        }

    def tearDown(self):
        self.temp.cleanup()

    def plan(self, edl=None, assets=None, output=None, root=None):
        return build_ffmpeg_argv(
            self.edl if edl is None else edl,
            {"asset-1": self.source} if assets is None else assets,
            self.output / "render.mp4" if output is None else output,
            self.output if root is None else root,
        )

    def test_builds_argument_array_with_trim_concat_and_no_audio(self):
        argv = self.plan()
        self.assertEqual(argv[0], "ffmpeg")
        self.assertIn("-nostdin", argv)
        self.assertIn("-protocol_whitelist", argv)
        self.assertIn("trim=start=1.000:end=3.000", argv[argv.index("-filter_complex") + 1])
        self.assertIn("concat=n=2:v=1:a=0[outv]", argv[argv.index("-filter_complex") + 1])
        self.assertIn("-an", argv)
        self.assertEqual(argv[-1], str(self.output / "render.mp4"))

    def test_rejects_title_clips_until_safe_text_renderer_exists(self):
        payload = {**self.edl, "clips": [dict(self.edl["clips"][0]), {
            "id": "title-1", "type": "title", "start_ms": 0, "end_ms": 1000, "text": "hello"
        }]}
        with self.assertRaisesRegex(RenderPlanError, "title clips"):
            self.plan(edl=payload)

    def test_rejects_missing_or_unrelated_asset_mapping(self):
        with self.assertRaisesRegex(RenderPlanError, "incomplete"):
            self.plan(assets={})
        with self.assertRaisesRegex(RenderPlanError, "unrelated"):
            self.plan(assets={"asset-1": self.source, "other": self.source})

    def test_rejects_relative_and_symlink_source_paths(self):
        with self.assertRaisesRegex(RenderPlanError, "absolute"):
            self.plan(assets={"asset-1": "assets/source.mp4"})
        link = self.assets / "linked.mp4"
        try:
            link.symlink_to(self.source)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are unavailable on this platform")
        with self.assertRaisesRegex(RenderPlanError, "symlink"):
            self.plan(assets={"asset-1": link})

    def test_rejects_output_path_escape_and_existing_output(self):
        with self.assertRaisesRegex(RenderPlanError, "inside"):
            self.plan(output=self.root / "outside.mp4")
        existing = self.output / "exists.mp4"
        existing.write_bytes(b"")
        with self.assertRaisesRegex(RenderPlanError, "new"):
            self.plan(output=existing)

    def test_rejects_non_mp4_and_unsafe_output_filename(self):
        with self.assertRaises(RenderPlanError):
            self.plan(output=self.output / "render.mov")
        with self.assertRaises(RenderPlanError):
            self.plan(output=self.output / "bad name.mp4")


if __name__ == "__main__":
    unittest.main()
