import tempfile
import unittest
from pathlib import Path

from ffmpeg_audio_mix import AudioMixError, build_audio_mix_argv


class FFmpegAudioMixTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.one = self.root / "voice.wav"
        self.two = self.root / "music.wav"
        self.one.write_bytes(b"fixture")
        self.two.write_bytes(b"fixture")
        self.output = self.root / "mix.m4a"

    def tearDown(self):
        self.temp.cleanup()

    def test_builds_shell_free_two_track_mix_with_fades_and_gain(self):
        argv = build_audio_mix_argv([
            {"path": str(self.one), "start_ms": 0, "duration_ms": 10000,
             "gain": 1.0, "fade_in_ms": 100, "fade_out_ms": 500},
            {"path": str(self.two), "start_ms": 500, "duration_ms": 12000,
             "gain": 0.25},
        ], str(self.output), output_duration_ms=12000)
        self.assertEqual(argv[0], "ffmpeg")
        self.assertIn("-nostdin", argv)
        self.assertIn("-filter_complex", argv)
        graph = argv[argv.index("-filter_complex") + 1]
        self.assertIn("amix=inputs=2", graph)
        self.assertIn("alimiter=limit=0.95", graph)
        self.assertIn("volume=0.2500", graph)
        self.assertFalse(any(";" in arg and arg != graph for arg in argv))

    def test_rejects_untrusted_filter_fields_invalid_gain_and_unsafe_paths(self):
        cases = [
            ([{"path": str(self.one), "duration_ms": 1000, "filter": "amovie"}], {}),
            ([{"path": str(self.one), "duration_ms": 1000, "gain": 99}], {}),
            ([{"path": str(self.one), "duration_ms": 1000, "fade_in_ms": 1001}], {}),
            ([{"path": str(self.root / "missing.wav"), "duration_ms": 1000}], {}),
        ]
        for tracks, kwargs in cases:
            with self.subTest(tracks=tracks), self.assertRaises((AudioMixError, TypeError)):
                build_audio_mix_argv(tracks, str(self.output), **kwargs)

    def test_rejects_invalid_track_count_and_output_extension(self):
        with self.assertRaises(AudioMixError):
            build_audio_mix_argv([], str(self.output))
        with self.assertRaises(AudioMixError):
            build_audio_mix_argv(
                [{"path": str(self.one), "duration_ms": 1000}],
                str(self.root / "mix.mp3"),
            )


    def test_audio_mix_applies_source_trim_before_timeline_delay(self):
        argv = build_audio_mix_argv([{
            "path": str(self.one), "start_ms": 750,
            "source_in_ms": 1250, "duration_ms": 4000,
            "gain": 0.5, "fade_out_ms": 500,
        }], str(self.output), output_duration_ms=5000)
        graph = argv[argv.index("-filter_complex") + 1]
        self.assertIn("atrim=start=1.250:duration=4.000", graph)
        self.assertIn("adelay=750|750", graph)
        self.assertLess(graph.index("afade=t=out"), graph.index("adelay=750|750"))


if __name__ == "__main__":
    unittest.main()
