# Windows self-hosted Agent runner setup

This connects the repository to the Windows PC that already has the configured Agent CLI. It does not use Codex and does not change the existing checkout.

## One-time setup on the Windows PC

1. Open the repository on GitHub: https://github.com/justinhblee-prog/shorts
2. Go to **Settings → Actions → Runners → New self-hosted runner**.
3. Select **Windows** and **x64**. Follow GitHub's current download and extraction instructions in a dedicated directory, for example `C:\\actions-runner-shorts`.
4. Generate the one-time registration token in that page only. Do not paste it into ChatGPT, a repository file, a script, or a log.
5. In an elevated PowerShell window in the runner directory, configure the runner using the URL and one-time token shown by GitHub. Add the custom label `shorts-agent` (retain the default labels).
6. Configure the runner service to log on as the same Windows user that owns the existing `DEVFLOW_AGENT_COMMAND` / `DEVFLOW_AGENT_ARGS_JSON` user environment variables and Claude CLI authentication. The service account must have access to the repository directory, Git, GitHub CLI, Python, PowerShell 7+, and the Agent CLI. Do not run it as LocalSystem if the Agent login is stored in the user's profile.
7. Start the runner service and confirm GitHub shows it as **Idle** and **Online**.

If service execution cannot access the existing Agent CLI login, stop the runner and resolve the Windows service logon/profile configuration first. Do not copy credentials into repository secrets or workflow YAML.

## Start a real run

1. Confirm the runner is **Online**.
2. Open **Actions → Windows self-hosted Agent multi-flow → Run workflow**.
3. Select branch `fix/devflow-detached-supervisor-2026-11-20`.
4. Select a task limit from 1 to 3 and dispatch.
5. Inspect the run log and its `windows-agent-multiflow-<run id>` artifact.

The workflow refuses to run from any branch other than the dedicated PR branch. It runs the real configured Agent CLI, uses the existing task/lease/worktree gates, and creates Draft PRs only. It does not merge, deploy, or publish.

## Security and operational notes

- Treat this runner as a trusted machine: self-hosted runners execute repository code with the runner account's local permissions.
- Keep it dedicated to this repository and do not run untrusted fork PR code on it.
- The workflow uses the job-scoped `GITHUB_TOKEN`; it does not persist a PAT.
- The runner must remain online while a workflow job is executing. This workflow runs the scheduler in the foreground so the job token remains available for GitHub operations.
- A green hosted GitHub Actions run is not proof of this PC's real Agent execution. Only a successful run on the `shorts-agent` self-hosted runner with real Agent logs establishes that.
