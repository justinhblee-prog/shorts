# Git CLI multi-flow automation

The Git CLI multi-flow runner chains eligible BUILD tasks without asking for a new confirmation between tasks. It creates an isolated worktree for each task, invokes the configured coding-agent CLI, validates the result, commits and pushes the task branch, and opens a Draft PR.

## One-time Windows setup

Install PowerShell 7 or newer, Git, Python 3.11+, GitHub CLI (`gh`), and the coding-agent CLI you intend to use. Authenticate GitHub once with `gh auth login` and authenticate the Agent CLI using its own documented login flow. Run all commands in PowerShell 7 (`pwsh`) from the repository root. The runner requires PowerShell 7 because it uses .NET `ProcessStartInfo.ArgumentList`. The executable and argument format must match an agent CLI already installed on the machine; the runner deliberately does not assume Codex, Claude, or another vendor.

```powershell
$env:DEVFLOW_AGENT_COMMAND = "C:\path\to\your-agent.exe"
$env:DEVFLOW_AGENT_ARGS_JSON = '["--prompt-file","{prompt_file}"]'
```

The argument JSON must be an array and must contain `{prompt_file}`. Optional placeholders are `{task_id}` and `{worktree}`. Use the agent's documented prompt-file argument syntax.

## Agent CLI configuration and preflight

Configure the installed Agent CLI once from PowerShell 7 in the repository root:

```powershell
.\scripts\git-cli-agent-config.ps1 -Configure
```

The helper prompts for the executable name/full path and the Agent CLI's documented prompt-file argument syntax. The JSON argument array must contain the `{prompt_file}` placeholder exactly once; `{task_id}` and `{worktree}` are optional. It stores only the executable and argument template in the current Windows user's environment. Do not put API keys, tokens, passwords, or other credentials in the argument list. Authenticate with the Agent CLI's own login/credential flow. Open a new PowerShell 7 window after configuration if you want the saved user environment to be reloaded automatically.

To verify the machine before running:

```powershell
.\scripts\git-cli-agent-config.ps1 -Check
```

The `-Run` launcher performs this preflight automatically. It checks PowerShell 7+, Git, Python, GitHub CLI authentication, repository cleanliness, the task manifest, Agent executable resolution, and the argument contract without printing the configured values or credentials.

## Run

The planner checks open pull requests through the authenticated GitHub CLI. Without `gh` authentication it can display candidates, but duplicate-PR status is unverified; execution always requires authenticated `gh` access.

```powershell
# Confirm GitHub CLI access before planning
gh auth status

# Preview eligible tasks without changing the repository
.\scripts\start-devflow-autopilot.ps1 -Plan

# Execute up to three independent eligible tasks concurrently
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

The `-Run` path now dispatches independent eligible tasks to separate PowerShell worker processes, each with its own Git worktree and an exclusive per-task lease file. The scheduler caps active workers at the manifest `max_parallel_worktrees` value (maximum 3), records durable task state under the sibling `*-multiflow-state` directory, enforces an agent timeout, and retains failed worktrees for inspection. The lease is held with an OS-exclusive file handle so a second worker cannot acquire the same task while the first worker is alive. Dependencies still require an explicitly completed prerequisite; dependent work is not optimistically started. The current manifest has no runnable independent tasks, so parallel execution has not yet been exercised against real agent work. `blocked_external` tasks are never auto-run. Merge, deployment, publishing, credential changes, and external provider spend are never automated.

## Empty queue behavior

If the planner reports `No eligible tasks without an existing open PR`, it found no task that simultaneously passes the dependency/status gates and the open-PR duplicate check. `blocked_external` tasks remain excluded until their external prerequisites are explicitly resolved; do not change their status merely to force execution.

## Parallel worker state and recovery

The runner stores `state.json`, per-task lease files, and task prompt snapshots in a sibling `*-multiflow-state` directory. A worker owns an exclusive lease for its task until it exits. Worker failures and timeouts are recorded; their worktrees are deliberately retained for inspection. A task recorded as `draft_pr_created` is not dispatched again. A stale `running` state is eligible for recovery only after the OS lease is no longer held. Failed tasks can be retried by a later scheduler invocation after the failed worktree and state have been reviewed; automatic in-run retry is not enabled yet. The scheduler does not mark manifest tasks completed, merge PRs, or deploy.

## Automated parallel integration test

CI also validates the Agent CLI argument contract and rejects credential-like CLI arguments. It cannot authenticate to or certify a specific third-party Agent provider. CI runs `scripts/test-git-cli-multiflow-parallel.ps1` on Windows PowerShell 7. The harness creates a temporary bare Git remote and isolated fixture repository, injects a fake `gh` CLI and fake Agent process, dispatches two independent tasks, and verifies overlapping Agent start times, independent pushed branches, durable `draft_pr_created` states, dependency gating, and no duplicate redispatch on a second scheduler invocation. It does not access production task entries, GitHub credentials, or create real pull requests. This verifies process-level concurrency and the worker-to-Draft-PR pipeline using local fixtures; it does not validate any particular external Agent vendor integration.
