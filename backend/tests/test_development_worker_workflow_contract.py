from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "nexus-development-job-worker.yml"


class DevelopmentWorkerWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = WORKFLOW.read_text(encoding="utf-8")

    def test_global_permissions_are_read_only_by_default(self):
        top_level = self.source.split("jobs:", 1)[0]
        self.assertIn("permissions:\n  contents: read", top_level)
        self.assertNotIn("pull-requests: write", top_level)
        self.assertNotIn("actions: write", top_level)

    def test_recovery_is_a_separate_read_only_job(self):
        recovery = self.source.split("  recover-reviews:", 1)[1].split("  development-cycle:", 1)[0]
        permissions = recovery.split("    permissions:", 1)[1].split("    steps:", 1)[0]
        self.assertIn("if: github.event_name == 'workflow_dispatch' && inputs.mode == 'recover'", recovery)
        self.assertIn("contents: read", permissions)
        self.assertIn("pull-requests: read", permissions)
        self.assertNotIn("write", permissions)
        self.assertNotIn("Aider", recovery)
        self.assertIn("GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}", recovery)
        self.assertIn("backend/recover_development_reviews.py", recovery)
        self.assertNotIn("backend/run_development_agent.py", recovery)

    def test_development_job_has_only_required_write_permissions(self):
        development = self.source.split("  development-cycle:", 1)[1]
        permissions = development.split("    steps:", 1)[0]
        self.assertIn("contents: write", permissions)
        self.assertIn("pull-requests: write", permissions)
        self.assertIn("actions: write", permissions)
        self.assertNotIn("issues:", permissions)

    def test_recovery_and_development_use_the_same_persistent_database(self):
        recovery = self.source.split("  recover-reviews:", 1)[1].split("  development-cycle:", 1)[0]
        development = self.source.split("  development-cycle:", 1)[1]
        for section in (recovery, development):
            self.assertIn('"NexusStudioPro\\shorts"', section)
            self.assertIn('"development.sqlite3"', section)
            self.assertIn("NEXUS_DEVELOPMENT_DB=", section)
            self.assertIn("outside GITHUB_WORKSPACE", section)

    def test_recovery_uses_no_write_capable_personal_token_or_aider(self):
        recovery = self.source.split("  recover-reviews:", 1)[1].split("  development-cycle:", 1)[0]
        self.assertNotIn("NEXUS_GITHUB_READ_TOKEN", recovery)
        self.assertNotIn("NEXUS_APPROVED_SCOPES", recovery)
        self.assertNotIn("NEXUS_AIDER_EXECUTABLE", recovery)
        self.assertIn("pull-requests: read", recovery)

    def test_untrusted_pull_request_events_cannot_trigger_worker_execution(self):
        trigger_block = self.source.split("permissions:", 1)[0]
        self.assertIn("workflow_dispatch:", trigger_block)
        self.assertIn("schedule:", trigger_block)
        for event in ("pull_request:", "pull_request_target:", "workflow_run:", "issue_comment:"):
            self.assertNotIn(event, trigger_block)

    def test_schedule_and_manual_dispatch_are_configured(self):
        self.assertIn("workflow_dispatch:", self.source)
        self.assertIn('cron: "17 */2 * * *"', self.source)
        self.assertIn("- recover", self.source)

    def test_node24_actions_are_guarded_by_self_hosted_runner_version_preflight(self):
        preflight = self.source.index("name: Verify self-hosted runner supports Node 24 actions")
        checkout = self.source.index("name: Check out default branch", self.source.index("  development-cycle:"))
        guard = self.source[preflight:checkout]
        self.assertIn("Runner.Listener", guard)
        self.assertIn("2.327.1", guard)
        self.assertIn("actions/checkout@v7", self.source)
        self.assertIn("peter-evans/create-pull-request@v8", self.source)
        self.assertNotIn("actions/checkout@v5", self.source)
        self.assertNotIn("peter-evans/create-pull-request@v7", self.source)

    def test_development_job_keeps_persistent_isolated_tooling(self):
        development = self.source.split("  development-cycle:", 1)[1]
        backend = development.index("name: Install isolated backend runtime dependencies")
        aider = development.index("name: Install and verify isolated local Aider CLI")
        execute = development.index("name: Execute one dependency-aware development cycle")
        backend_script = development[backend:aider]
        aider_script = development[aider:execute]
        for script in (backend_script, aider_script):
            self.assertIn('"NexusStudioPro\\tooling"', script)
            self.assertIn("GetFullPath($env:GITHUB_WORKSPACE)", script)
            self.assertIn("$toolRootFull.StartsWith($workspace", script)
            self.assertIn("Persistent runner tooling must be outside GITHUB_WORKSPACE", script)
            self.assertNotIn("Join-Path $env:GITHUB_WORKSPACE", script)
        self.assertIn('"backend-venv"', backend_script)
        self.assertIn('"aider-venv"', aider_script)
        self.assertIn("NEXUS_BACKEND_PYTHON=", backend_script)
        self.assertIn("NEXUS_AIDER_EXECUTABLE=", aider_script)
        self.assertIn("incomplete; refusing destructive repair", backend_script)
        self.assertIn("incomplete; refusing destructive repair", aider_script)
        self.assertIn("backend/run_development_agent.py", development)
        self.assertIn("backend/publish_development_reviews.py", development)

    def test_intake_token_is_separate_from_pr_publication_token(self):
        self.assertIn("GITHUB_TOKEN: ${{ secrets.NEXUS_GITHUB_READ_TOKEN }}", self.source)
        self.assertIn("token: ${{ secrets.GITHUB_TOKEN }}", self.source)

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
        self.assertIn("backend/publish_development_reviews.py", self.source[publish:])
        self.assertIn("review_pending", self.source)

    def test_verified_pr_update_triggers_bounded_self_continuation(self):
        self.assertIn("remaining_cycles:", self.source)
        self.assertIn('default: "5"', self.source)
        continuation = self.source.index("name: Continue bounded autonomous development after verified PR update")
        publish = self.source.index("name: Record exact Draft PR review artifact")
        self.assertGreater(continuation, publish)
        step = self.source[continuation:]
        self.assertIn("pull-request-operation == 'created'", step)
        self.assertIn("pull-request-operation == 'updated'", step)
        self.assertIn("GH_WORKFLOW: nexus-development-job-worker.yml", step)
        self.assertIn("actions/workflows/$env:GH_WORKFLOW/dispatches", step)
        self.assertIn("remaining - 1", step)
        self.assertIn("$remaining -gt 10", step)
        self.assertIn("Bounded continuation limit reached", step)

    def test_approved_scope_is_explicitly_required_by_environment_contract(self):
        self.assertIn("NEXUS_APPROVED_SCOPES", self.source)


if __name__ == "__main__":
    unittest.main()