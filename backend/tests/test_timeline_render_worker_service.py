import os
import unittest
from unittest.mock import patch

from timeline_render_worker_service import _integer_env


class TimelineRenderWorkerServiceConfigTests(unittest.TestCase):
    def test_integer_environment_values_are_bounded_decimal_values(self):
        with patch.dict(os.environ, {"NEXUS_RENDER_WIDTH": "720"}):
            self.assertEqual(_integer_env("NEXUS_RENDER_WIDTH", 1080, 16, 8192), 720)
        for value in ("", "-1", "1.5", "8193", "NaN"):
            with patch.dict(os.environ, {"NEXUS_RENDER_WIDTH": value}):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    _integer_env("NEXUS_RENDER_WIDTH", 1080, 16, 8192)


if __name__ == "__main__":
    unittest.main()
