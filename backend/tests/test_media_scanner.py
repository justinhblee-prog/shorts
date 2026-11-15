import os
import tempfile
import unittest
from media_scanner import ClamAVScanner, MediaScanError


class ClamAVScannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "artifact.mp4")
        with open(self.path, "wb") as handle:
            handle.write(b"test")

    def tearDown(self):
        self.tmp.cleanup()

    def test_clean_exit_is_reported(self):
        calls = []
        def runner(args, **kwargs):
            calls.append((args, kwargs))
            return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        result = ClamAVScanner(executable="/usr/bin/clamscan", runner=runner).scan(self.path)
        self.assertEqual(result, {"status": "clean", "engine": "clamav"})
        self.assertEqual(calls[0][0][0:3], ["/usr/bin/clamscan", "--no-summary", "--infected"])
        self.assertNotIn("shell", calls[0][1])

    def test_infected_exit_is_rejected(self):
        scanner = ClamAVScanner(runner=lambda *args, **kwargs:
            type("Result", (), {"returncode": 1, "stdout": "Eicar", "stderr": ""})())
        with self.assertRaisesRegex(MediaScanError, "infected"):
            scanner.scan(self.path)

    def test_scanner_error_is_fail_closed(self):
        scanner = ClamAVScanner(runner=lambda *args, **kwargs:
            type("Result", (), {"returncode": 2, "stdout": "", "stderr": "database unavailable"})())
        with self.assertRaisesRegex(MediaScanError, "failed"):
            scanner.scan(self.path)

    def test_timeout_and_missing_executable_are_fail_closed(self):
        import subprocess
        def timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])
        with self.assertRaisesRegex(MediaScanError, "timed out"):
            ClamAVScanner(runner=timeout).scan(self.path)
        def missing(*args, **kwargs):
            raise FileNotFoundError("clamscan")
        with self.assertRaisesRegex(MediaScanError, "could not be started"):
            ClamAVScanner(runner=missing).scan(self.path)

    def test_symlink_and_missing_targets_are_rejected(self):
        link = os.path.join(self.tmp.name, "link.mp4")
        os.symlink(self.path, link)
        scanner = ClamAVScanner(runner=lambda *args, **kwargs: None)
        with self.assertRaises(MediaScanError):
            scanner.scan(link)
        with self.assertRaises(MediaScanError):
            scanner.scan(os.path.join(self.tmp.name, "missing.mp4"))


if __name__ == "__main__":
    unittest.main()
