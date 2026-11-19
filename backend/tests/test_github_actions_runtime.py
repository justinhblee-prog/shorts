import unittest
from pathlib import Path


class GitHubActionsRuntimeContractTests(unittest.TestCase):
    def test_workflows_use_node24_compatible_major_versions(self):
        root = Path(__file__).resolve().parents[2]
        workflow_dir = root / ".github" / "workflows"
        workflows = [
            workflow_dir / "backend-tests.yml",
            workflow_dir / "compose-smoke.yml",
        ]
        for path in workflows:
            content = path.read_text(encoding="utf-8")
            with self.subTest(workflow=path.name):
                self.assertIn("uses: actions/checkout@v7", content)
                self.assertNotIn("actions/checkout@v4", content)
                if path.name == "backend-tests.yml":
                    self.assertIn("uses: actions/setup-python@v7", content)
                    self.assertNotIn("actions/setup-python@v5", content)


if __name__ == "__main__":
    unittest.main()
