import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ffmpeg_render_execution import RenderExecutionError, execute_ffmpeg_render


class FFmpegRenderExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.ffmpeg = self.root / ("fake_ffmpeg.py" if os.name == "nt" else "fake_ffmpeg")
        self.ffprobe = self.root / ("fake_ffprobe.py" if os.name == "nt" else "fake_ffprobe")
        self._write_executable(self.ffmpeg, """#!/usr/bin/env python3
import pathlib, sys
pathlib.Path(sys.argv[-1]).write_bytes(b'fake mp4 fixture')
""")
        self._write_executable(self.ffprobe, """#!/usr/bin/env python3
import json
print(json.dumps({'streams':[{'codec_type':'video','codec_name':'h264','width':1080,'height':1920}],
                  'format':{'duration':'2.0','format_name':'mov,mp4'}}))
""")

    def tearDown(self):
        self.temp.cleanup()

    def _write_executable(self, path, content):
        path.write_text(content, encoding="utf-8")
        if os.name != "nt":
            path.chmod(0o755)

    def command(self, output):
        return [str(self.ffmpeg), str(output)]

    def run_render(self, name="render.mp4"):
        # Supply a placeholder; the executor replaces it with its private temp path.
        return execute_ffmpeg_render(self.command_placeholder(), self.root, name,
                                      ffprobe_path=str(self.ffprobe))

    def command_placeholder(self):
        # A valid argv whose final path is replaced below with the executor-owned path.
        # The executable writes to its final argv item.
        fd, path = tempfile.mkstemp(suffix=".mp4", dir=self.root)
        os.close(fd)
        os.unlink(path)
        # execute_ffmpeg_render requires its own generated path, so the fake executable
        # is invoked via a tiny wrapper script that writes to the final argument.
        return [str(self.ffmpeg), str(Path(path).resolve())]

    def test_adopts_verified_artifact_with_hash_and_review_state(self):
        # Patch the temp-path argument after observing that the executor owns it.
        import ffmpeg_render_execution as module
        original = module.tempfile.mkstemp
        def fixed_mkstemp(**kwargs):
            fd, path = original(**kwargs)
            self.generated = Path(path)
            return fd, path
        module.tempfile.mkstemp = fixed_mkstemp
        try:
            result = execute_ffmpeg_render([str(self.ffmpeg), str(self.root / ".placeholder.mp4")],
                self.root, "accepted.mp4", ffprobe_path=str(self.ffprobe))
        finally:
            module.tempfile.mkstemp = original
        self.assertEqual(result["status"], "review_pending")
        self.assertEqual(result["size_bytes"], len(b"fake mp4 fixture"))
        self.assertTrue((self.root / "accepted.mp4").is_file())
        self.assertEqual(len(result["sha256"]), 64)

    def test_rejects_existing_destination(self):
        (self.root / "exists.mp4").write_bytes(b"x")
        with self.assertRaisesRegex(RenderExecutionError, "already exists"):
            execute_ffmpeg_render([str(self.ffmpeg), str(self.root / "x.mp4")],
                self.root, "exists.mp4", ffprobe_path=str(self.ffprobe))

    def test_rejects_invalid_output_name(self):
        with self.assertRaisesRegex(RenderExecutionError, "invalid"):
            execute_ffmpeg_render([str(self.ffmpeg), str(self.root / "x.mp4")],
                self.root, "../escape.mp4", ffprobe_path=str(self.ffprobe))


if __name__ == "__main__":
    unittest.main()
