# Windows self-hosted Agent runner setup

This connects the repository's isolated Git worktrees to a local Agent CLI on the Windows PC. The recommended zero-API-cost option is the locally installed Ollama model; no cloud model API key is required.

## Configure the local Ollama Agent

Prerequisites:
- Ollama is installed and running on the Windows PC.
- The model is already present locally (currently tested configuration: `qwen2.5-coder:7b`).
- Python 3.10+, PowerShell 7+, Git, and GitHub CLI are available.

From the repository root in PowerShell 7:

```powershell
ollama list
ollama ps
$env:DEVFLOW_AGENT_COMMAND = (Get-Command python).Source
$env:DEVFLOW_AGENT_ARGS_JSON = '["scripts/ollama-agent.py","--prompt-file","{prompt_file}","--model","qwen2.5-coder:7b"]'
[Environment]::SetEnvironmentVariable("DEVFLOW_AGENT_COMMAND", $env:DEVFLOW_AGENT_COMMAND, "User")
[Environment]::SetEnvironmentVariable("DEVFLOW_AGENT_ARGS_JSON", $env:DEVFLOW_AGENT_ARGS_JSON, "User")
& .\scripts\git-cli-agent-config.ps1 -Check
& .\scripts\test-real-agent-cli.ps1 -TimeoutSeconds 300
```

The Agent uses Ollama's local HTTP endpoint at `127.0.0.1:11434`. It provides repository-scoped file listing, reading, writing, text search, diff inspection, and a small allowlist of validation commands. It does not provide an arbitrary shell tool, network tool, credential access, or permission to modify `.devflow/tasks.json`. File access is confined to the assigned worktree. Model quality and tool-call reliability depend on the locally installed model and available PC resources.

If the smoke test fails, inspect that Ollama is running and that `ollama list` contains the configured model. Do not add an API key or switch to a paid provider to work around a local setup issue.

## Windows self-hosted Runner

1. Open the repository on GitHub: https://github.com/justinhblee-prog/shorts
2. Go to **Settings → Actions → Runners → New self-hosted runner**.
3. Select **Windows** and **x64**. Follow GitHub's current download and extraction instructions in a dedicated directory, for example `C:\\actions-runner-shorts`.
4. Generate the one-time registration token in that page only. Never paste it into ChatGPT, a repository file, a script, or a log.
5. Configure the runner with the URL and one-time token shown by GitHub. Add the custom label `shorts-agent`.
6. The runner process/service must run as the same Windows user that has Ollama running and owns the Agent environment variables. It must have access to the repository directory, Git, GitHub CLI, Python, PowerShell 7+, and the local Ollama endpoint. Do not run it as LocalSystem.
7. Confirm GitHub shows the runner as **Idle** and **Online**.

A Windows service may not inherit environment variables changed after it started. Restart the runner process/service after changing the user-level Agent configuration. Keep Ollama available in that user's session.

## Start a real run

1. Confirm Ollama is running and the runner is **Online**.
2. Open **Actions → Windows self-hosted Agent multi-flow → Run workflow**.
3. Select branch `fix/devflow-detached-supervisor-2026-11-20`.
4. Run the isolated Agent smoke test first if needed; otherwise select a task limit from 1 to 3.
5. Inspect the run log and its `windows-agent-multiflow-<run id>` artifact.

The workflow uses the configured local Agent CLI, existing task/lease/worktree gates, and Draft PRs only. It does not merge, deploy, or publish.

## Security and operational notes

- Self-hosted runners execute repository code with the runner account's local permissions. Keep this runner dedicated to this repository and do not run untrusted fork PR code on it.
- The workflow uses the job-scoped `GITHUB_TOKEN`; it does not persist a PAT.
- The runner must remain online while a workflow job is executing. The scheduler runs in the foreground so the job token remains available for GitHub operations.
- A green hosted GitHub Actions run is not proof of local Agent execution. Only a successful run on the `shorts-agent` self-hosted runner with real Agent logs establishes that.
