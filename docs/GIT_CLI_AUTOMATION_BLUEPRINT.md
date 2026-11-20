# Git CLI Development Automation Blueprint — v0.2

Repository: justinhblee-prog/shorts  
Primary workflow: Git CLI + isolated Git worktrees + GitHub CLI (gh)  
Default PR base: feat/engineering-orchestrator-2026-11-20  
Safety: Draft PR only; no auto-merge, deploy, or public publishing.

## 1. Whole lifecycle map

### Product operation

    Trend and competitor discovery
      -> Opportunity scoring
      -> Human topic selection
      -> Script generation
      -> Voice generation
      -> Video rendering
      -> Artifact staging and integrity checks
      -> Human review
      -> Reject/revise: return to script or production
      -> Approve: private platform upload
      -> Metrics and revenue/cost ledger
      -> Performance analysis
      -> Feed evidence back to opportunity scoring

Public publishing remains outside automation. Provider compatibility, licensing, live generation, OAuth, financial reconciliation and production-host recovery require real external evidence.

### Engineering delivery

    Roadmap / issue intake
      -> Task manifest (scope, priority, dependencies, acceptance)
      -> Select a ready task
      -> Create Git branch + isolated worktree
      -> Coding agent implements in that worktree
      -> Static checks and focused tests
      -> Full repository validation
      -> Failure: repair in same worktree and repeat
      -> Pass: commit -> push branch -> open Draft PR
      -> CI and human review
      -> Changes requested: return to implementation
      -> Approved: human-authorized merge
      -> Refresh base and unlock dependent tasks

## 2. Git CLI as source of truth

- Each independent task gets its own branch and Git worktree. Never run concurrent agents in one worktree.
- The primary checkout is not used for concurrent edits.
- Task metadata is stored in .devflow/tasks.json; Git branch, commit and PR state remain authoritative for delivery.
- Default concurrency cap: three worktrees. Raise only after runner capacity and test isolation are measured.
- A dependent task starts only after its prerequisite task is marked completed after merge; `review_pending` PRs do not unlock downstream tasks. External gates must also be satisfied.
- Validation runs in the same worktree proposed for review.
- Every task ends in a Draft PR. Merge, release, deploy, production upload and public publishing remain human-controlled.

## 3. Git CLI sequence

From a clean primary checkout:

    git status --short
    git fetch origin --prune
    git switch feat/engineering-orchestrator-2026-11-20
    git pull --ff-only
    python scripts/devflow.py start BUILD-00352 --base feat/engineering-orchestrator-2026-11-20

The helper prints the isolated worktree path. Run the coding agent in that path only. From inside that worktree:

    python scripts/devflow.py validate
    python scripts/devflow.py finish --message "BUILD: Implement secure FFmpeg render worker" --title "BUILD: Secure FFmpeg render worker"

The finish command re-runs validation, checks staged diff hygiene, blocks likely secret files, commits, pushes the task branch and uses gh pr create --draft when GitHub CLI is installed. Without gh, it stops after push and reports that a Draft PR must be opened manually.

## 4. Parallel task plan

| Task | Priority | State | Execution |
|---|---:|---|---|
| BUILD-00352 secure FFmpeg worker | 1 | Ready | First; establishes render interfaces |
| BUILD-00353 real provider validation | 2 | External gate | After worker interface; needs credentials and approved spend |
| BUILD-00354 production deployment/recovery | 3 | External gate | After real media flow; needs target host and authorization |

The first task is deliberately singular because the render worker establishes interfaces consumed by later integration. Once stable, provider adapters, UI review surfaces and operational docs can be split into independent worktrees.

## 5. Windows workstation prerequisites

- Git for Windows with Git Bash on PATH
- Python 3.11+
- GitHub CLI (gh), authenticated to the intended repository
- Docker Desktop for Compose integration
- A supported coding-agent CLI or IDE integration configured separately

Verify:

    git --version
    python --version
    bash --version
    gh auth status
    git status --short

Do not point a worktree at the Guardian repository. Keep the primary checkout clean before starting another task. The helper's default worktree directory is a sibling folder named shorts-worktrees.

## 6. Automation boundary

Automated by the Git CLI helper:
- clean-checkout guard;
- isolated task branch/worktree creation;
- repository validation;
- diff hygiene and conservative secret-filename checks;
- commit, push and Draft PR creation.

Not automated yet:
- autonomous task selection from live issue/PR state;
- spawning an AI coding agent (requires a supported agent CLI and explicit credential/spend boundary);
- semantic conflict resolution;
- PR approval/merge, production deployment or public publishing.

Git itself does not write code. A coding agent must be installed and invoked inside the worktree. The next safe increment is a provider-specific agent adapter with bounded command, repository scope, token budget, timeout and human stop control.

## 7. Risk controls

- Worktrees isolate files, not shared external resources. Tests using SQLite, ports, Docker volumes or provider accounts need per-worktree isolation.
- Filename checks are not a full secret scanner. Keep CI secret scanning enabled.
- A pushed branch may trigger CI; it does not prove production readiness.
- Never use force push, hard reset, unattended PR merge, deployment commands or public upload in unattended flows.
- Do not automatically rebase or merge task branches. Preserve the exact tested commit.

## 8. Acceptance criteria

- [ ] Worktree creation succeeds from a clean checkout.
- [ ] Independent worktrees do not modify the primary checkout.
- [ ] Validation fails closed on test errors.
- [ ] Secret-like files block staging.
- [ ] Completion commits and pushes only the current task branch.
- [ ] Draft PR is opened with the configured base.
- [ ] No merge, deploy or public publishing occurs.
- [ ] Agent adapter remains disabled until provider, spend limit and credentials are explicitly configured.

## 9. Version history

- v0.1: Whole-lifecycle map, dependency-aware task manifest, Git CLI worktree helper and guarded Draft-PR completion flow.
- v0.2: Bounded local coding-agent supervisor with task selection, isolated worktree, validation/repair loop and Draft-PR handoff.


## 10. One-command autonomous coding flow — v0.2 increment

`scripts/devflow_autopilot.py` now connects the task manifest to a locally installed coding-agent CLI:

1. Select the highest-priority `ready` or `in_progress` task (or an explicitly named task).
2. Verify the primary checkout is clean and all dependencies are completed/merged.
3. Create a dedicated Git branch and worktree from the configured base.
4. Invoke the configured coding agent in that worktree only.
5. Run `scripts/devflow.py validate`; if validation fails, send the failure back to the same agent for a bounded repair attempt (default: two repairs).
6. Mark the task `review_pending` only after validation succeeds, then commit, push and open a Draft PR through the existing Git CLI helper.

Configure the agent once in the workstation environment. Example for Codex CLI:

**PowerShell**
```powershell
$env:DEVFLOW_AGENT_COMMAND_JSON='["codex","exec","--full-auto"]'
$env:DEVFLOW_BASE='feat/ffmpeg-render-execution-guard-2026-11-20'
python scripts/devflow_autopilot.py --task BUILD-00352
```

The command is a JSON argument array, not a shell command string. The supervisor appends the task prompt as the final argument and launches the process with `shell=False`. The agent process receives a restricted environment allowlist (PATH and basic home/temp/system variables); API keys, cloud credentials, CI tokens and provider secrets are not forwarded. The agent executable, local authentication and usage limits must already be configured on that workstation. The supervisor does not create credentials or silently authorize provider spend.

Options:
- `--task BUILD-00352`: resume a specific ready/in-progress task; omit to select the highest-priority runnable task.
- `--base BRANCH`: choose the exact existing base branch.
- `--max-repairs 2`: bounded repair attempts (maximum 3).
- `--agent-timeout 3600`: per-attempt timeout in seconds.

Safety boundaries:
- One task/worktree at a time in this initial supervisor; it is not yet a multi-agent parallel scheduler.
- Primary checkout must be clean. Existing worktrees are never overwritten or deleted automatically.
- The coding agent is instructed not to modify task state, use secrets, publish, deploy, merge, force-push or run destructive Git commands.
- The supervisor only marks `review_pending` after repository validation passes; external gates remain open.
- Draft PR creation and CI may trigger GitHub workflows. Merge, deploy, provider calls and public publishing remain human-controlled.
- If the agent CLI is absent, the task stops before creating a worktree. If it fails after worktree creation, the worktree is retained for inspection.

This is an executable local automation runner, not a claim that the current ChatGPT session can execute commands on the user's Windows workstation. The first end-to-end run requires the configured agent CLI and authenticated `git`/`gh` on that workstation.
