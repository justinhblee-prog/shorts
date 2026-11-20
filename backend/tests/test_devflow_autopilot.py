import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import devflow_autopilot as autopilot


class DevflowAutopilotTests(unittest.TestCase):
    def test_selects_highest_priority_runnable_task(self):
        data = {"tasks": [
            {"id": "BUILD-2", "priority": 2, "status": "ready", "depends_on": []},
            {"id": "BUILD-1", "priority": 1, "status": "in_progress", "depends_on": []},
            {"id": "BUILD-3", "priority": 0, "status": "blocked_external", "depends_on": []},
        ]}
        self.assertEqual(autopilot.choose_task(data, None)["id"], "BUILD-1")

    def test_resumes_explicit_in_progress_task(self):
        data = {"tasks": [
            {"id": "BUILD-1", "priority": 1, "status": "in_progress", "depends_on": []}
        ]}
        self.assertEqual(autopilot.choose_task(data, "BUILD-1")["status"], "in_progress")

    def test_does_not_start_task_with_unreviewed_dependency(self):
        data = {"tasks": [
            {"id": "BUILD-1", "priority": 1, "status": "ready", "depends_on": []},
            {"id": "BUILD-2", "priority": 2, "status": "ready", "depends_on": ["BUILD-1"]},
        ]}
        with self.assertRaisesRegex(RuntimeError, "dependency is not review-ready"):
            autopilot.choose_task(data, "BUILD-2")

    def test_does_not_select_external_blocked_task(self):
        data = {"tasks": [
            {"id": "BUILD-1", "priority": 1, "status": "blocked_external", "depends_on": []}
        ]}
        with self.assertRaisesRegex(RuntimeError, "no ready/in-progress task"):
            autopilot.choose_task(data, None)

    def test_prompt_preserves_external_gate_and_no_publish_policy(self):
        prompt = autopilot.task_prompt({
            "id": "BUILD-1", "title": "Sample",
            "scope": ["backend"], "acceptance": ["unit tests"],
            "external_gates": ["provider credentials"],
        }, 1)
        self.assertIn("provider credentials", prompt)
        self.assertIn("Do not use secrets", prompt)
        self.assertIn("Do not modify .devflow/tasks.json", prompt)


if __name__ == "__main__":
    unittest.main()
