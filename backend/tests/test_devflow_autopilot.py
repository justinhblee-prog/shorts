import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import devflow_autopilot as autopilot
import devflow_parallel as parallel


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

    def test_review_pending_dependency_is_not_treated_as_merged(self):
        data = {"tasks": [
            {"id": "BUILD-1", "priority": 1, "status": "review_pending", "depends_on": []},
            {"id": "BUILD-2", "priority": 2, "status": "ready", "depends_on": ["BUILD-1"]},
        ]}
        with self.assertRaisesRegex(RuntimeError, "dependency is not review-ready"):
            autopilot.choose_task(data, "BUILD-2")

    def test_agent_environment_does_not_forward_credentials(self):
        from unittest.mock import patch
        with patch.dict("os.environ", {
            "PATH": "/bin", "HOME": "/tmp/home",
            "OPENAI_API_KEY": "do-not-forward",
            "GITHUB_TOKEN": "do-not-forward",
            "AWS_SECRET_ACCESS_KEY": "do-not-forward",
        }, clear=True):
            env = autopilot.agent_environment()
        self.assertEqual(env, {"PATH": "/bin", "HOME": "/tmp/home"})

    def test_does_not_select_external_blocked_task(self):
        data = {"tasks": [
            {"id": "BUILD-1", "priority": 1, "status": "blocked_external", "depends_on": []}
        ]}
        with self.assertRaisesRegex(RuntimeError, "no ready/in-progress task"):
            autopilot.choose_task(data, None)

    def test_parallel_dispatch_selects_only_independent_ready_scopes(self):
        data = {"policy": {"max_parallel_worktrees": 3}, "tasks": [
            {"id": "A", "priority": 1, "status": "ready", "depends_on": [], "scope": ["backend/worker"]},
            {"id": "B", "priority": 2, "status": "ready", "depends_on": [], "scope": ["frontend/editor"]},
            {"id": "C", "priority": 3, "status": "ready", "depends_on": [], "scope": ["backend/worker"]},
            {"id": "D", "priority": 0, "status": "blocked_external", "depends_on": [], "scope": ["docs"]},
        ]}
        self.assertEqual(
            [task["id"] for task in parallel.select_parallel_tasks(data, 3)],
            ["A", "B"],
        )

    def test_parallel_dispatch_requires_merged_dependencies(self):
        data = {"policy": {"max_parallel_worktrees": 3}, "tasks": [
            {"id": "A", "priority": 1, "status": "review_pending", "depends_on": [], "scope": ["backend"]},
            {"id": "B", "priority": 2, "status": "ready", "depends_on": ["A"], "scope": ["docs"]},
        ]}
        with self.assertRaisesRegex(RuntimeError, "no dependency-ready tasks"):
            parallel.select_parallel_tasks(data, 3)

    def test_parallel_limit_cannot_exceed_policy(self):
        with self.assertRaisesRegex(RuntimeError, "parallel limit"):
            parallel.select_parallel_tasks(
                {"policy": {"max_parallel_worktrees": 2}, "tasks": []}, 3
            )

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
