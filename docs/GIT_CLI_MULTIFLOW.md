# Git CLI multi-flow automation

The Git CLI multi-flow runner chains eligible BUILD tasks without asking for a new confirmation between tasks. It creates an isolated worktree for each task, invokes the configured coding-agent CLI, validates the result, commits and pushes the task branch, and opens a Draft PR.

## One-time Windows setup

Install PowerShell 7 or newer, Git, Python 3.11+, GitHub CLI (`gh`), and the coding-agent CLI you intend to use. Authenticate GitHub once with `gh auth login` and authenticate the Agent CLI using its own documented login flow. Run all commands in PowerShell 7 (`pwsh`) from the repository root. The runner requires PowerShell 7 because it uses .NET `ProcessStartInfo.ArgumentList`. The executable and argument format must match an agent CLI already installed on the machine; the runner deliberately does not assume Codex, Claude, or another vendor.


## Agent CLI configuration and preflight

Configure the installed Agent CLI once from PowerShell 7 in the repository root:

```powershell
.\scripts\git-cli-agent-config.ps1 -Configure
```

The helper prompts for the executable name/full path and the Agent CLI's documented prompt-file argument syntax. The JSON argument array must contain exactly one prompt placeholder: `{prompt_file}` passes the prompt file path, while `{prompt_text}` passes its UTF-8 contents directly to CLIs that accept a prompt string. `{task_id}` and `{worktree}` are optional. It stores only the executable and argument template in the current Windows user's environment. Do not put API keys, tokens, passwords, or other credentials in the argument list. Authenticate with the Agent CLI's own login/credential flow. Open a new PowerShell 7 window after configuration if you want the saved user environment to be reloaded automatically.

To verify the machine before running:

```powershell
.\scripts\git-cli-agent-config.ps1 -Check
```

A single `-Run` invocation drains up to 20 currently eligible independent tasks; no extra confirmation is required between tasks. At most three workers run concurrently, as bounded by the task manifest. Tasks represented by open Draft PRs remain excluded, and dependent tasks remain blocked until their dependency is explicitly marked completed. The `-Run` launcher performs this preflight automatically. It checks PowerShell 7+, Git, Python, GitHub CLI authentication, repository cleanliness, the task manifest, Agent executable resolution, and the argument contract without printing the configured values or credentials.


### Claude CLI (Codex excluded)

For this Windows workflow, use Claude CLI only; Codex is not part of the configured worker path. After confirming `claude --help` on the installed version and completing Claude's own sign-in flow, configure the runner with the prompt-text placeholder so Claude receives the actual task instructions rather than a file path:

```powershell
.\\scripts\\git-cli-agent-config.ps1 -Configure -AgentCommand "claude" -AgentArgsJson '["-p","{prompt_text}","--permission-mode","acceptEdits"]'
.\\scripts\\git-cli-agent-config.ps1 -Check
```

The `acceptEdits` mode allows normal workspace edits while preserving Claude's permission checks for other tool actions. Do not use bypass-permissions or dangerously-skip-permissions flags. If the installed Claude CLI does not list `--permission-mode` or `acceptEdits` in its own help, stop and adapt the arguments to that installed version rather than guessing. Real Claude execution remains unverified until the local preflight and a real worker run succeed.

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
