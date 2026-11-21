import os
import unittest
from unittest.mock import patch

from media_binary_pin import MediaBinaryPinError
import timeline_render_worker_service as service


class TimelineRenderWorkerServiceConfigTests(unittest.TestCase):
    def test_integer_environment_values_are_bounded_decimal_values(self):
        with patch.dict(os.environ, {"NEXUS_RENDER_WIDTH": "720"}):
            self.assertEqual(service._integer_env("NEXUS_RENDER_WIDTH", 1080, 16, 8192), 720)
        for value in ("", "-1", "1.5", "8193", "NaN"):
            with patch.dict(os.environ, {"NEXUS_RENDER_WIDTH": value}):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    service._integer_env("NEXUS_RENDER_WIDTH", 1080, 16, 8192)

    def test_media_binary_verification_uses_exact_configured_paths_and_manifest(self):
        with (
            patch.dict(os.environ, {"NEXUS_MEDIA_BINARY_MANIFEST": "/tmp/reviewed.sha256"}),
            patch.object(service, "verify_binary_manifest", return_value={
                service.FFMPEG_PATH: "a" * 64,
                service.FFPROBE_PATH: "b" * 64,
            }) as verify,
        ):
            result = service.verify_media_binaries()
        verify.assert_called_once_with(
            (service.FFMPEG_PATH, service.FFPROBE_PATH), "/tmp/reviewed.sha256"
        )
        self.assertEqual(result[service.FFMPEG_PATH], "a" * 64)

    def test_invalid_binary_manifest_blocks_worker_construction_before_queue_access(self):
        with (
            patch.object(service, "verify_media_binaries",
                         side_effect=MediaBinaryPinError("checksum mismatch")),
            patch.object(service, "JobQueue") as queue,
        ):
            with self.assertRaisesRegex(MediaBinaryPinError, "checksum mismatch"):
                service.build_worker()
        queue.assert_not_called()


if __name__ == "__main__":
    unittest.main()
