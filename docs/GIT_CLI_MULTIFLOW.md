# Git CLI multi-flow automation

The Git CLI multi-flow runner chains eligible BUILD tasks without asking for a new confirmation between tasks. It creates an isolated worktree for each task, invokes the configured coding-agent CLI, validates the result, commits and pushes the task branch, and opens a Draft PR.

## One-time Windows setup

Run these commands in PowerShell from the repository root. The executable and argument format must match an agent CLI already installed on the machine; the runner deliberately does not assume Codex, Claude, or another vendor.

```powershell
$env:DEVFLOW_AGENT_COMMAND = "C:\path\to\your-agent.exe"
$env:DEVFLOW_AGENT_ARGS_JSON = '["--prompt-file","{prompt_file}"]'
```

The argument JSON must be an array and must contain `{prompt_file}`. Optional placeholders are `{task_id}` and `{worktree}`. Use the agent's documented prompt-file argument syntax.

## Run

```powershell
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

The current implementation chains task runs sequentially. It does not claim concurrent agent execution. `blocked_external` tasks are never auto-run. Merge, deployment, publishing, credential changes, and external provider spend are never automated.
