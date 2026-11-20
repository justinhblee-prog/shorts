import sys
from pathlib import Path
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ffmpeg_render_execution import RenderExecutionError, execute_ffmpeg_render


class FFmpegRenderExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.ffmpeg = self.root / "fake_ffmpeg.py"
        self.ffprobe = self.root / "fake_ffprobe.py"
        self.ffmpeg.write_text(
            "import pathlib, sys\npathlib.Path(sys.argv[-1]).write_bytes(b'fake mp4 fixture')\n",
            encoding="utf-8")
        self.ffprobe.write_text(
            "import json\nprint(json.dumps({'streams':[{'codec_type':'video','codec_name':'h264','width':1080,'height':1920}],"
            "'format':{'duration':'2.0','format_name':'mov,mp4'}}))\n",
            encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def command(self):
        return [sys.executable, str(self.ffmpeg), "{output}"]

    def test_adopts_verified_artifact_with_hash_and_review_state(self):
        result = execute_ffmpeg_render(self.command(), self.root, "accepted.mp4",
                                       ffprobe_path=[sys.executable, str(self.ffprobe)])
        self.assertEqual(result["status"], "review_pending")
        self.assertEqual(result["size_bytes"], len(b"fake mp4 fixture"))
        self.assertTrue((self.root / "accepted.mp4").is_file())
        self.assertEqual(len(result["sha256"]), 64)

    def test_rejects_existing_destination(self):
        (self.root / "exists.mp4").write_bytes(b"x")
        with self.assertRaisesRegex(RenderExecutionError, "already exists"):
            execute_ffmpeg_render(self.command(), self.root, "exists.mp4",
                                  ffprobe_path=sys.executable)

    def test_rejects_invalid_output_name(self):
        with self.assertRaisesRegex(RenderExecutionError, "invalid"):
            execute_ffmpeg_render(self.command(), self.root, "../escape.mp4",
                                  ffprobe_path=sys.executable)


if __name__ == "__main__":
    unittest.main()
