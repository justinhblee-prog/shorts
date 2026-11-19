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

    def test_job_completion_waits_for_exact_draft_pr_artifact(self):
        create = self.source.index("id: publish-pr")
        publish = self.source.index("name: Record exact Draft PR review artifact")
        self.assertLess(create, publish)
        self.assertIn("pull-request-head-sha", self.source[publish:])
        self.assertIn("NEXUS_REVIEW_HEAD_SHA", self.source[publish:])
        self.assertIn("python backend/publish_development_reviews.py", self.source[publish:])
        self.assertIn("draft: true", self.source)
        self.assertIn("review_pending", self.source)

    def test_manual_recovery_mode_is_read_only_and_skips_code_generation(self):
        self.assertIn("mode:", self.source)
        self.assertIn("- recover", self.source)
        recovery = self.source.index("name: Recover orphaned review-pending jobs (read-only)")
        execute = self.source.index("name: Execute one dependency-aware development cycle")
        create_pr = self.source.index("name: Create Draft PR for verified changes only")
        self.assertLess(recovery, execute)
        self.assertIn("if: github.event.inputs.mode == 'recover'", self.source[recovery:execute])
        self.assertIn("if: github.event.inputs.mode != 'recover'", self.source[execute:create_pr])
        self.assertIn("python backend/recover_development_reviews.py", self.source[recovery:execute])
        self.assertIn("no job was requeued", self.source[recovery:execute])
        self.assertIn("if: github.event.inputs.mode != 'recover'", self.source[create_pr:])
    def test_verified_pr_update_triggers_bounded_self_continuation(self):
        self.assertIn("remaining_cycles:", self.source)
        self.assertIn('default: "5"', self.source)
        self.assertIn("actions: write", self.source)
        continuation = self.source.index("name: Continue bounded autonomous development after verified PR update")
        publish = self.source.index("name: Record exact Draft PR review artifact")
        self.assertGreater(continuation, publish)
        step = self.source[continuation:]
        self.assertIn("pull-request-operation == 'created'", step)
        self.assertIn("pull-request-operation == 'updated'", step)
        self.assertIn("GH_WORKFLOW: nexus-development-job-worker.yml", step)
        self.assertIn("actions/workflows/$env:GH_WORKFLOW/dispatches", step)
        detect = self.source.index("name: Detect generated source changes")
        create = self.source.index("name: Create Draft PR for verified changes only")
        self.assertLess(detect, create)
        self.assertIn("steps.detect-changes.outputs.has_changes == 'true'", self.source[create:])
        self.assertIn("Existing Draft PR will be left untouched", self.source[detect:create])
        self.assertIn("remaining - 1", step)
        self.assertIn("$remaining -gt 10", step)
        self.assertIn("Bounded continuation limit reached", step)
        self.assertIn("No automatic merge or deployment is permitted.", self.source)

    def test_approved_scope_is_explicitly_required_by_environment_contract(self):
        self.assertIn("NEXUS_APPROVED_SCOPES", self.source)
        self.assertIn("NEXUS_GITHUB_READ_TOKEN", self.source)


if __name__ == "__main__":
    unittest.main()
