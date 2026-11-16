import unittest

from scheduler_runtime_config import load_scheduler_config


class SchedulerRuntimeConfigTests(unittest.TestCase):
    def test_defaults_are_valid(self):
        self.assertEqual(load_scheduler_config({}), (30, 90))

    def test_valid_boundary_values(self):
        self.assertEqual(load_scheduler_config({
            "NEXUS_SCHEDULER_POLL_SECONDS": "5",
            "NEXUS_SCHEDULER_LEASE_SECONDS": "15",
        }), (5, 15))
        self.assertEqual(load_scheduler_config({
            "NEXUS_SCHEDULER_POLL_SECONDS": "300",
            "NEXUS_SCHEDULER_LEASE_SECONDS": "900",
        }), (300, 900))

    def test_rejects_non_decimal_integer_settings(self):
        invalid_values = ("", "  ", "1.5", "-5", "+5", "5s", "1e2")
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "decimal integer"):
                    load_scheduler_config({"NEXUS_SCHEDULER_POLL_SECONDS": value})

    def test_rejects_values_outside_bounds(self):
        for name, value in (
            ("NEXUS_SCHEDULER_POLL_SECONDS", "4"),
            ("NEXUS_SCHEDULER_POLL_SECONDS", "301"),
            ("NEXUS_SCHEDULER_LEASE_SECONDS", "14"),
            ("NEXUS_SCHEDULER_LEASE_SECONDS", "3601"),
        ):
            with self.subTest(name=name, value=value):
                with self.assertRaisesRegex(ValueError, "between"):
                    load_scheduler_config({name: value})

    def test_poll_interval_must_leave_lease_renewal_margin(self):
        with self.assertRaisesRegex(ValueError, "one-third"):
            load_scheduler_config({
                "NEXUS_SCHEDULER_POLL_SECONDS": "31",
                "NEXUS_SCHEDULER_LEASE_SECONDS": "90",
            })
        self.assertEqual(load_scheduler_config({
            "NEXUS_SCHEDULER_POLL_SECONDS": "30",
            "NEXUS_SCHEDULER_LEASE_SECONDS": "90",
        }), (30, 90))


if __name__ == "__main__":
    unittest.main()
