# Git CLI multi-flow automation

The Git CLI multi-flow runner chains eligible BUILD tasks without asking for a new confirmation between tasks. It creates an isolated worktree for each task, invokes the configured coding-agent CLI, validates the result, commits and pushes the task branch, and opens a Draft PR.

## One-time Windows setup

Install PowerShell 7 or newer and GitHub CLI (`gh`), authenticate once with `gh auth login`, and run the commands below in PowerShell 7 (`pwsh`) from the repository root. The runner requires PowerShell 7 because it uses .NET `ProcessStartInfo.ArgumentList`. The executable and argument format must match an agent CLI already installed on the machine; the runner deliberately does not assume Codex, Claude, or another vendor.

```powershell
$env:DEVFLOW_AGENT_COMMAND = "C:\path\to\your-agent.exe"
$env:DEVFLOW_AGENT_ARGS_JSON = '["--prompt-file","{prompt_file}"]'
```

The argument JSON must be an array and must contain `{prompt_file}`. Optional placeholders are `{task_id}` and `{worktree}`. Use the agent's documented prompt-file argument syntax.

## Run

The planner checks open pull requests through the authenticated GitHub CLI. Without `gh` authentication it can display candidates, but duplicate-PR status is unverified; execution always requires authenticated `gh` access.

```powershell
# Confirm GitHub CLI access before planning
gh auth status

# Preview eligible tasks without changing the repository
.\scripts\start-devflow-autopilot.ps1 -Plan

# Execute up to three eligible tasks in sequence
.\scripts\start-devflow-autopilot.ps1 -Run -MaxTasks 3
```

You can select one task with `-Task BUILD-xxxxx` or override the base branch with `-Base branch-name`.

## Flow and safety gates

1. Select tasks in `ready` or `in_progress` whose dependencies are all `completed`.
2. Skip tasks already represented by an open PR, preventing duplicate work.
3. Enforce the manifest's `max_parallel_worktrees` cap and require a clean primary checkout.
4. Create a timestamped branch and isolated Git worktree from the configured base.
5. Invoke the configured agent with the task scope and acceptance criteria.
6. Run `scripts/devflow.py validate`, block likely secret files, run staged diff checks, commit, push, and create a Draft PR.
7. Leave dependency completion under human control. A dependent task cannot run until its prerequisite is reviewed, merged, and explicitly marked `completed` in `.devflow/tasks.json`.

The current implementation chains task runs sequentially. `max_parallel_worktrees` is a safety cap on existing worktrees, not a promise that multiple coding agents run concurrently. True concurrent agent scheduling is not implemented yet. `blocked_external` tasks are never auto-run. Merge, deployment, publishing, credential changes, and external provider spend are never automated.

## Empty queue behavior

If the planner reports `No eligible tasks without an existing open PR`, it found no task that simultaneously passes the dependency/status gates and the open-PR duplicate check. `blocked_external` tasks remain excluded until their external prerequisites are explicitly resolved; do not change their status merely to force execution.
