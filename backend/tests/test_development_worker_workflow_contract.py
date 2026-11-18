from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "nexus-development-job-worker.yml"


class DevelopmentWorkerWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = WORKFLOW.read_text(encoding="utf-8")

    def test_development_job_database_is_persistent_outside_checkout(self):
        configure = self.source.index("name: Configure persistent development-job state")
        execute = self.source.index("name: Execute one dependency-aware development cycle")
        self.assertLess(configure, execute)
        step = self.source[configure:execute]
        self.assertIn("$env:LOCALAPPDATA", step)
        self.assertIn("NEXUS_DEVELOPMENT_DB=", step)
        self.assertIn("$env:GITHUB_ENV", step)
        self.assertIn("outside GITHUB_WORKSPACE", step)
        self.assertIn("databaseFull.StartsWith($workspace", step)

    def test_schedule_and_manual_dispatch_are_configured(self):
        self.assertIn("workflow_dispatch:", self.source)
        self.assertIn('cron: "17 */2 * * *"', self.source)

    def test_only_trusted_self_hosted_windows_runner_is_targeted(self):
        self.assertIn("runs-on: [self-hosted, windows, nexus-local-ai]", self.source)
        self.assertIn("ollama list", self.source)
        self.assertIn("qwen2.5-coder:7b", self.source)

    def test_read_only_intake_token_is_separate_from_pr_token(self):
        self.assertIn("GITHUB_TOKEN: ${{ secrets.NEXUS_GITHUB_READ_TOKEN }}", self.source)
        self.assertIn("token: ${{ secrets.GITHUB_TOKEN }}", self.source)
        self.assertIn("pull-requests: write", self.source)

    def test_automated_pull_request_is_draft_and_uses_stable_branch(self):
        self.assertIn("branch: automation/nexus-development-cycle", self.source)
        self.assertIn("draft: true", self.source)
        self.assertIn("No automatic merge or deployment is permitted.", self.source)

    def test_approved_scope_is_explicitly_required_by_environment_contract(self):
        self.assertIn("NEXUS_APPROVED_SCOPES", self.source)
        self.assertIn("NEXUS_GITHUB_READ_TOKEN", self.source)


if __name__ == "__main__":
    unittest.main()
