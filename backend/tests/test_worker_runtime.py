import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from worker_runtime import heartbeat_interval


class WorkerRuntimeTests(unittest.TestCase):
    def test_default_heartbeat_is_ten_seconds(self):
        self.assertEqual(heartbeat_interval(300), 10)

    def test_heartbeat_is_capped_to_one_third_of_lease(self):
        self.assertEqual(heartbeat_interval(30, 20), 10)
        self.assertEqual(heartbeat_interval(90, 60), 30)

    def test_heartbeat_never_falls_below_five_seconds(self):
        self.assertEqual(heartbeat_interval(30, 1), 5)
        self.assertEqual(heartbeat_interval(10, 2), 5)

    def test_configured_heartbeat_is_respected_below_lease_cap(self):
        self.assertEqual(heartbeat_interval(300, 15), 15)


if __name__ == "__main__":
    unittest.main()
