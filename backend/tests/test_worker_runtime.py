import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from worker_runtime import (heartbeat_interval, parse_worker_runtime_config,
                            request_worker_shutdown)


class WorkerRuntimeTests(unittest.TestCase):

    def test_worker_runtime_config_defaults(self):
        self.assertEqual(parse_worker_runtime_config(), (300, 3, 10))

    def test_worker_runtime_config_bounds_and_heartbeat_cap(self):
        self.assertEqual(parse_worker_runtime_config("30", "1", "3600"), (30, 1, 10))
        self.assertEqual(parse_worker_runtime_config("3600", "300", "15"),
                         (3600, 300, 15))
        self.assertEqual(parse_worker_runtime_config("90", "10", "5"), (90, 10, 5))

    def test_worker_runtime_config_rejects_non_decimal_values(self):
        invalid = ["", " 30", "30 ", "+30", "-30", "3.0", "3e1", "٣٠"]
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_worker_runtime_config(value, "3", "10")
                with self.assertRaises(ValueError):
                    parse_worker_runtime_config("300", value, "10")
                with self.assertRaises(ValueError):
                    parse_worker_runtime_config("300", "3", value)

    def test_worker_runtime_config_rejects_out_of_range_values(self):
        cases = [
            ("29", "3", "10"), ("3601", "3", "10"),
            ("300", "0", "10"), ("300", "301", "10"),
            ("300", "3", "4"), ("300", "3", "3601"),
        ]
        for values in cases:
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    parse_worker_runtime_config(*values)

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

    def test_sigterm_signals_local_stop_and_pauses_active_production(self):
        import threading

        class Queue:
            def __init__(self):
                self.pauses = []
            def pause(self, reason, job_id):
                self.pauses.append((reason, job_id))

        queue = Queue()
        stopping = threading.Event()
        lost_lease = threading.Event()
        request_worker_shutdown(queue, stopping, "job-1", lost_lease, 15)
        self.assertTrue(stopping.is_set())
        self.assertTrue(lost_lease.is_set())
        self.assertEqual(len(queue.pauses), 1)
        self.assertEqual(queue.pauses[0][1], "job-1")
        self.assertIn("signal 15", queue.pauses[0][0])

    def test_sigterm_still_stops_locally_if_pause_persistence_fails(self):
        import threading

        class BrokenQueue:
            def pause(self, reason, job_id):
                raise OSError("database unavailable")

        stopping = threading.Event()
        lost_lease = threading.Event()
        request_worker_shutdown(BrokenQueue(), stopping, "job-2", lost_lease, 15)
        self.assertTrue(stopping.is_set())
        self.assertTrue(lost_lease.is_set())


if __name__ == "__main__":
    unittest.main()
