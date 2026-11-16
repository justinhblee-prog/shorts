import os
import tempfile
import unittest
from media_scanner import ClamAVScanner, MediaScanError
from media_staging import MediaStager, MediaStagingError


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
        self.assertEqual(calls[0][0][0], "/usr/bin/clamscan")
        self.assertIn("--database=/var/lib/clamav", calls[0][0])
        self.assertIn("--no-summary", calls[0][0])
        self.assertIn("--infected", calls[0][0])
        self.assertIn("--alert-exceeds-max=yes", calls[0][0])
        self.assertIn("--max-filesize=12345", calls[0][0])
        self.assertIn("--max-scansize=12345", calls[0][0])
        self.assertIn("--max-scantime=7000", calls[0][0])
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

    def test_scanner_limits_exceeded_is_not_treated_as_clean(self):
        def runner(*args, **kwargs):
            return SimpleNamespace(
                returncode=1, stdout="Heuristics.Limits.Exceeded FOUND", stderr=""
            )
        scanner = ClamAVScanner(runner=runner)
        with tempfile.NamedTemporaryFile() as handle:
            with self.assertRaisesRegex(MediaScanError, "incomplete"):
                scanner.scan(handle.name)

    def test_media_limit_above_clamav_supported_max_is_rejected(self):
        with self.assertRaises(ValueError):
            ClamAVScanner(max_bytes=2 * 1024 * 1024 * 1024 + 1)

    def test_invalid_timeout_is_rejected(self):
        with self.assertRaises(ValueError):
            ClamAVScanner(timeout=0)
        with self.assertRaises(ValueError):
            ClamAVScanner(timeout="invalid")

    def test_symlink_and_missing_targets_are_rejected(self):
        link = os.path.join(self.tmp.name, "link.mp4")
        os.symlink(self.path, link)
        scanner = ClamAVScanner(runner=lambda *args, **kwargs: None)
        with self.assertRaises(MediaScanError):
            scanner.scan(link)
        with self.assertRaises(MediaScanError):
            scanner.scan(os.path.join(self.tmp.name, "missing.mp4"))


class MediaStagingScanIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.payload = b"0000ftypisom" + b"x" * 64
        self.scanned = []
        def fetcher(host, ip, path, timeout):
            return 200, {"content-type": "video/mp4", "content-length": str(len(self.payload))}, [self.payload]
        class Scanner:
            def __init__(inner, error=None):
                inner.error = error
            def scan(inner, path):
                self.scanned.append(path)
                if inner.error:
                    raise inner.error
                return {"status": "clean", "engine": "test"}
        self.Scanner = Scanner
        self.fetcher = fetcher

    def tearDown(self):
        self.tmp.cleanup()

    def _stager(self, scanner):
        return MediaStager(self.tmp.name, "cdn.example.test", 1024,
            resolver=lambda host: ["8.8.8.8"], fetcher=self.fetcher,
            scanner=scanner, scan_enabled=True)

    def test_invalid_scanner_configuration_fails_closed_without_blocking_stager_creation(self):
        from unittest.mock import patch
        with patch.dict(os.environ, {"NEXUS_MEDIA_SCAN_TIMEOUT_SECONDS": "invalid"}):
            stager = MediaStager(
                self.tmp.name, "cdn.example.test", 1024,
                resolver=lambda host: ["8.8.8.8"], fetcher=self.fetcher,
                scan_enabled=True,
            )
            with self.assertRaisesRegex(MediaStagingError, "configuration is invalid"):
                stager.stage("invalid-scan-config", "https://cdn.example.test/video.mp4")
        self.assertFalse(os.path.exists(stager.staged_path("invalid-scan-config")))
        self.assertFalse(any(name.endswith(".part") for name in os.listdir(self.tmp.name)))

    def test_invalid_scan_toggle_is_treated_as_enabled(self):
        from unittest.mock import patch
        scanner = self.Scanner()
        with patch.dict(os.environ, {"NEXUS_MEDIA_SCAN_ENABLED": "treu"}):
            stager = MediaStager(
                self.tmp.name, "cdn.example.test", 1024,
                resolver=lambda host: ["8.8.8.8"], fetcher=self.fetcher,
                scanner=scanner,
            )
        result = stager.stage("invalid-toggle", "https://cdn.example.test/video.mp4")
        self.assertEqual(result["malware_scan"], "clean")
        self.assertEqual(len(self.scanned), 1)

    def test_disabled_scan_does_not_construct_optional_scanner(self):
        from unittest.mock import patch
        with patch.dict(os.environ, {"NEXUS_MEDIA_SCAN_TIMEOUT_SECONDS": "invalid"}):
            stager = MediaStager(
                self.tmp.name, "cdn.example.test", 1024,
                resolver=lambda host: ["8.8.8.8"], fetcher=self.fetcher,
                scan_enabled=False,
            )
        self.assertIsNone(stager.scanner)
        result = stager.stage("disabled-job", "https://cdn.example.test/video.mp4")
        self.assertEqual(result["malware_scan"], "disabled")

    def test_scanner_must_explicitly_return_clean_before_publish(self):
        stager = MediaStager(
            self.tmp.name, "cdn.example.test", 1024,
            resolver=lambda host: ["8.8.8.8"], fetcher=self.fetcher,
            scanner=self.Scanner(), scan_enabled=True,
        )
        stager.scanner.scan = lambda path: None
        with self.assertRaisesRegex(MediaStagingError, "explicitly confirm"):
            stager.stage("unknown-scan-job", "https://cdn.example.test/video.mp4")
        self.assertFalse(os.path.exists(stager.staged_path("unknown-scan-job")))
        self.assertFalse(any(name.endswith(".part") for name in os.listdir(self.tmp.name)))

    def test_clean_scan_is_required_before_staged_file_is_published(self):
        scanner = self.Scanner()
        result = self._stager(scanner).stage("clean-job", "https://cdn.example.test/video.mp4")
        self.assertEqual(result["malware_scan"], "clean")
        self.assertEqual(len(self.scanned), 1)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp.name, result["media_path"])))

    def test_infected_or_unavailable_scanner_blocks_and_cleans_temporary_file(self):
        for error in (MediaScanError("infected"), MediaScanError("scanner unavailable")):
            with self.subTest(error=str(error)):
                stager = self._stager(self.Scanner(error))
                with self.assertRaises(MediaStagingError):
                    stager.stage("blocked-job", "https://cdn.example.test/video.mp4")
                self.assertFalse(os.path.exists(stager.staged_path("blocked-job")))
                self.assertFalse(any(name.endswith(".part") for name in os.listdir(self.tmp.name)))


if __name__ == "__main__":
    unittest.main()
