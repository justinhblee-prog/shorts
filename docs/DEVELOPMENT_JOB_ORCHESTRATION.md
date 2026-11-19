# NEXUS STUDIO PRO — Development Job Orchestration

**Checkpoint:** BUILD-00320 (Windows local-runner toolchain and Python isolation)  
**Updated:** 2026-11-19  
**Repository:** https://github.com/justinhblee-prog/shorts  
**Status:** BUILD-00319 exact PR head `95844080e8635354ab8f8e2511c4b64b5bfe91ae` passed GitHub Actions run [44437965780](https://github.com/justinhblee-prog/shorts/actions/runs/44437965780). BUILD-00320 adds Windows toolchain preflight and isolated backend/Aider virtual environments; exact-head CI is pending. Live Windows runner/Ollama execution remains unverified.

## 1. Why this exists

The development process must be driven by a durable job graph, not by repeated chat prompts or a model being invoked on a timer. A workflow run is not a completed development job. A job is complete only when its source change, regression test, validation result, and review artifact are recorded and independently verifiable.

This is a development-control plane. It is separate from the product's existing content-production queue and recurring publishing scheduler.

## 2. Verified repository baseline (2026-11-17)

- Default branch is `main`; the repository is Python-based.
- `main` contains the product runtime queue and scheduler: `backend/queue_store.py`, `backend/scheduler.py`, and `backend/scheduler_store.py`. These manage content-production work and scheduled production dispatch, not the engineering backlog.
- The bootstrap local-model workflow and `nexus-development-job-worker.yml` scheduled worker workflow exist only on development branches/Draft PRs until reviewed and merged. Their schedules are not active from `main` yet.
- Workflow run [44061280928](https://github.com/justinhblee-prog/shorts/actions/runs/44061280928) completed with a successful Actions conclusion. The agent step and focused queue test step completed, but the workflow detected no meaningful product diff and skipped Draft PR creation. This is an automation execution, not a delivered code change.
- Open Draft PRs #313–#318 form a sequential development branch chain. Each PR's base is the preceding development branch; they must be reviewed and validated in dependency order.
- Open Draft PRs #319 and #320 each contain only a one-line `.gitignore` change (`.aider*`) and are not evidence of product development. Keep them Draft; do not merge them as feature work.
- GitHub reports 208 open issues, but that count includes pull requests and must not be represented as 208 remaining development tasks.
- Current self-hosted runner availability was not established by the read-only evidence. A completed past run does not prove a runner is online now.

## 3. Target operating model

1. **Discover:** collect open issues, Draft PRs, repository roadmap, TODO/FIXME markers, test gaps, and known deployment blockers.
2. **Normalize:** convert findings into stable job IDs; deduplicate by scope and affected files; link each job to source evidence.
3. **Plan:** define prerequisites, conflict domains, priority, risk, acceptance criteria, and validation commands.
4. **Schedule:** select only jobs whose prerequisites are complete; run independent jobs in parallel only when their file/resource conflict sets do not overlap.
5. **Lease:** atomically claim each job with owner, lease expiry, heartbeat, and fencing token; prevent duplicate execution.
6. **Execute:** give each worker one bounded job, exact scope, repository state, and required evidence.
7. **Verify:** require a meaningful source diff AND a regression test, run the relevant suite, inspect the diff, and record CI evidence. No-op runs are failed/no-op jobs, never completions.
8. **Review:** publish Draft PRs only. Never auto-merge, close, deploy, publish, or alter secrets.
9. **Advance:** after a job passes its completion gate, unlock dependent jobs automatically. Retry transient failures with bounded backoff; quarantine repeated or ambiguous failures.
10. **Observe:** expose truthful states, worker heartbeats, active leases, changed paths, test outcomes, PR links, and blockers in the dashboard.

## 4. Initial job graph

The following are implementation jobs for the engineering automation itself. They are not claims that the product backlog has been fully inventoried.

| Job ID | Work item | Depends on | Completion evidence |
|---|---|---|---|
| DEV-ORCH-001 | Persist normalized development jobs, source references, dependencies, and status history | — | schema + migration + repository tests |
| DEV-ORCH-002 | Implement dependency-aware ready-job selection and cycle detection | 001 | deterministic scheduler tests |
| DEV-ORCH-003 | Add atomic leases, heartbeat, expiry recovery, and fencing | 001, 002 | concurrent claim and stale-worker tests |
| DEV-ORCH-004 | Implement bounded worker execution contract and result/evidence recording | 001–003 | worker lifecycle tests |
| DEV-ORCH-005 | Add completion gate: source diff, regression test, validation, and review artifact required | 004 | no-op and test-only rejection tests |
| DEV-ORCH-006 | Add retry/backoff, dead-letter/quarantine, and operator recovery | 001–005 | retry/recovery/idempotency tests |
| DEV-ORCH-007 | Connect GitHub Issues/PRs/Actions as read-only evidence sources; reconcile without auto-merging | 001–006 | fixture-backed integration tests |
| DEV-ORCH-008 | Add truthful development-job API and dashboard view | 001–007 | API/UI tests and live-state contract |
| DEV-ORCH-009 | Wire scheduled/manual GitHub Actions dispatch and prove autonomous continuation on the default branch | 001–008 | observed end-to-end run creating a real Draft PR from a meaningful code+test diff |\n| DEV-ORCH-010 | Verify real Ollama worker end-to-end execution and dependent-job advancement | 009 | real model-generated product diff, passing tests, Draft PR, and unlocked dependent job |

### Product backlog intake (separate graph)

After the control plane is reliable, create product jobs from the actual open PR/issue inventory and the BUILD roadmap. Preserve the existing PR dependency chain (#313 → #314 → #315 → #316 → #317 → #318) for review; do not silently retarget or merge it. Inspect each PR's diff and CI before classifying it as ready, blocked, duplicate, or incomplete. The two no-op automation PRs (#319/#320) remain excluded from feature-completion counts.

## 5. Job state machine

`discovered → ready → leased → running → verifying → review_pending → completed`

Failure paths:

- transient failure: `running → retry_wait → ready` (bounded attempts and backoff)
- lease loss: `leased/running → lease_expired → ready` only after fencing old worker writes
- repeated/ambiguous failure: `failed → quarantined` pending operator review
- no meaningful diff: `verifying → no_op` (not completed)
- tests fail: `verifying → retry_wait` or `quarantined`, depending on failure class
- external approval/security/cost/data-loss decision: `blocked_external`

All state changes must be append-only in the job event history and guarded by compare-and-swap/fencing semantics.

## 6. Parallelism rules

- Parallelize only jobs with satisfied dependencies and disjoint declared write/resource scopes.
- Serialize changes to shared schemas, migrations, central API contracts, workflow files, and the same feature module unless an explicit integration plan exists.
- Reserve an integration job to reconcile parallel outputs and run the full validation suite.
- Limit concurrency by available trusted workers and resource budget; never equate multiple agent invocations with useful parallel progress.

## 7. Safety and truthfulness gates

- Least-privilege GitHub permissions; no secrets in prompts, logs, or browser code.
- Draft PR only; no auto-merge or auto-deploy.
- Do not execute untrusted PR code on the self-hosted runner.
- No destructive migrations, data resets, external publishing, or paid-provider calls without explicit approval.
- Report the exact changed files, commit, PR, tests, and unresolved blockers for every completed stage.
- Distinguish workflow success, test success, code-change success, and product/runtime validation.
- Never claim background continuation unless a scheduled workflow is on the default branch, a trusted runner is online, and an actual subsequent run is observed.

## 8. Implemented prototype and remaining gates

The current Draft PR #321 contains the following prototype components:

- `backend/development_jobs.py`: SQLite-backed job graph, dependency checks, leases, heartbeat/fencing, append-only events, retry/quarantine, and completion evidence gate.
- `backend/development_job_worker.py`: bounded worker lifecycle, heartbeat, retries, and idle draining; a cycle stops after its first review_pending diff so a second task cannot run against an uncommitted worktree.
- `backend/tests/test_development_worker_workflow_contract.py`: regression checks for the two-hour schedule, manual dispatch, trusted runner/model, split GitHub credentials, and stable Draft PR branch.
- `backend/development_github_intake.py`: read-only GitHub Issues/PR/Actions intake, deduplication, and explicit per-issue file-scope approval.
- `backend/development_backlog_service.py`: sync → register → worker cycle coordinator.
- `backend/run_development_agent.py`: one-cycle runner that seeds the engineering graph and injects the local Aider/Ollama executor.
- `backend/development_agent_executor.py`: constrained Aider executor with protected-path checks, credential-stripped child environment, scoped diff check, and repository validation.
- `.github/workflows/nexus-development-job-worker.yml`: scheduled/manual self-hosted runner workflow, Draft PR creation, and a post-publication verification step using the action's exact PR URL/head SHA outputs.
- Automated Draft PR publication reuses the stable `automation/nexus-development-cycle` branch so scheduled runs update the same review surface instead of creating a new PR branch every cycle.
- `backend/app.py` and `frontend/app.js`: authenticated read-only development-job API and live status/event panel; lease tokens and raw error details are redacted. `backend/tests/test_development_job_api_security.py` covers the access-control and redaction contract.
- The monitor summary now reports active and expired lease counts, latest update time, and the most recent successful validation reference; the UI exposes these alongside the job list.
- `development_workers` persists runner presence, hostname, active job, last-seen heartbeat, and clean shutdown state. The authenticated `/api/development/workers` endpoint and monitor distinguish online from stale/offline workers.

The new runner and workflow are code-level implementations, not proof of autonomous operation. CI on hosted Linux validates the Python code and fixtures; it does not validate the Windows self-hosted runner, Ollama availability, real model edits, GitHub token permissions, or scheduled execution from `main`.

Before enabling the workflow on the default branch, configure `NEXUS_GITHUB_READ_TOKEN` as a fine-grained token limited to read-only Issues, Pull requests, Actions, and repository metadata. Configure `NEXUS_APPROVED_SCOPES` only with explicitly approved issue-to-path mappings. The workflow's built-in `GITHUB_TOKEN` is kept separate and is used only by the Draft-PR publication action.

### Persistent runner state (BUILD-00316)

The development-job database must survive separate scheduled GitHub Actions jobs. The workflow now sets `NEXUS_DEVELOPMENT_DB` to `%LOCALAPPDATA%\NexusStudioPro\shorts\development.sqlite3` (falling back to `%USERPROFILE%\AppData\Local`) before the worker starts. This path is outside `GITHUB_WORKSPACE`, because the checkout action cleans the workspace and would otherwise remove an untracked SQLite file between runs.

Use one trusted persistent Windows runner host/account for this local database. Multiple runners with the same label would have separate local job graphs; no shared database or off-host backup is provided by this change. The database contains engineering job state and audit events, not product media or provider credentials. Do not delete the LocalAppData directory as part of routine runner cleanup.

The workflow-contract test checks that the path is configured before the worker cycle and is outside the checkout. Hosted CI does not prove that the Windows runner actually reuses the database across separate runs; that remains an end-to-end release gate.

### BUILD-00317 — exact Draft PR review-artifact completion gate

The worker now records validated source changes as review_pending; this state is not terminal and does not unlock dependent jobs. The worker releases its lease but keeps the file scope reserved, and it stops after the first changed job in a cycle so another job cannot run against the same uncommitted worktree.

After peter-evans/create-pull-request@v7 runs, backend/publish_development_reviews.py performs GET-only GitHub API verification. It checks that the returned PR belongs to the configured repository, is open, unmerged and Draft, targets the default branch, uses the expected automation head branch, and has the exact head SHA returned by the action. It then reads the complete PR file list and requires every changed path recorded for the job to be present before DevelopmentJobStore.publish_review_artifact records the PR URL/head SHA and transitions the job to completed.

If the action returns no PR URL/head SHA, the PR is not Draft/open, the head SHA changes, the base/head branch differs, the API read fails, or a changed file is missing, the job remains review_pending; dependent jobs remain blocked. No PR mutation, approval, merge, deployment or public publishing is performed by the verification script.

Regression coverage includes successful publication, missing files, head-SHA mismatch, non-Draft/closed PR, branch/base mismatch, repository mismatch, idempotent same-head recording, dependency blocking until publication, review-pending scope reservation, and one changed job per worker cycle. Hosted CI remains fixture-backed; it does not prove the Windows runner or real Ollama execution.

### BUILD-00318 — safe orphaned review_pending recovery

Implemented on `build/build-00318-orphaned-review-pending-recovery`; see [BUILD_00318.md](BUILD_00318.md).

- Added paginated read-only discovery of open pull requests and a recovery path for the stable automation branch.
- Recovery requires exactly one open, unmerged Draft PR with the expected head/base repositories and branch names. It then re-reads that exact PR and verifies the full head SHA and every changed file through the existing publication gate.
- Zero or multiple matching PRs leave the job and immutable event history unchanged.
- Added `backend/recover_development_reviews.py` and a manual `workflow_dispatch` mode named `recover`. This mode skips Aider/Ollama execution and Draft PR creation.
- No automatic requeue, branch mutation, PR mutation, merge, or deployment is performed. A no-match case requires operator inspection of the persistent runner worktree/branch before any separate requeue decision.
- Regression tests cover exact recovery, no-match preservation, ambiguous candidates, and no-op when there are no pending jobs. CI and live self-hosted-runner verification remain pending.

### BUILD-00319 — bounded autonomous continuation

Implemented on `build/build-00319-bounded-autonomous-continuation`.

- Added a `remaining_cycles` workflow-dispatch input (default 5, hard maximum 10).
- After a development run produces or updates the stable Draft PR, and only after the exact PR URL/head SHA review-artifact step succeeds, the workflow dispatches the same workflow again on the default branch with the remaining count decremented.
- Each invocation remains one bounded development cycle. The worker stops after the first changed job because the worktree must be published and verified before another job can safely use it.
- A run with no new PR change, missing PR evidence, failed validation, or recovery-only mode does not dispatch another development run.
- The chain is serialized by the existing workflow concurrency group. It never merges, deploys, or publicly publishes.
- The scheduled workflow remains a two-hour fallback. This is bounded chained continuation, not an always-on daemon and not proof of a live runner. It still requires this workflow to be merged into `main`, a continuously available trusted Windows runner with Ollama/Aider, and correctly configured GitHub secrets/permissions.
- The workflow contract test covers the bounded decrement, maximum, verified-PR gating, and dispatch endpoint.

### Remaining ordered gates

1. Review the stacked control-plane PR chain (#321 → #327) in dependency order; no PR is merged without explicit user approval.
2. After the workflow is deliberately integrated into main, configure the fine-grained NEXUS_GITHUB_READ_TOKEN and explicit NEXUS_APPROVED_SCOPES mappings.
3. Verify the trusted Windows self-hosted runner toolchain, isolated Python environments, Ollama model access, and persistent LocalAppData database across at least two separate workflow runs.
4. Verify a real Ollama-generated scoped diff, exact open Draft PR publication, successful review-artifact recording, and dependent-job advancement.
5. Verify the read-only API/dashboard against that real runner cycle; then continue product integration and the remaining release gates.


### BUILD-00320 — Windows runner preflight and isolated Python environments

Implemented on `build/build-00320-windows-validation-shell-preflight`.

- Fail fast before model execution unless the trusted Windows runner has Python 3.11+, Git Bash/POSIX sh, Node.js 18+, a responding loopback Ollama API, and the exact `qwen2.5-coder:7b` model tag.
- Replace substring model matching with exact CLI/API tag checks so similarly named variants cannot satisfy the runtime gate.
- Create separate per-run workspace virtual environments for backend requirements and Aider. Do not install backend or Aider packages into the runner user's global/user Python site-packages.
- Pass the backend interpreter explicitly through `NEXUS_BACKEND_PYTHON` and the Aider executable through `NEXUS_AIDER_EXECUTABLE`; repository validation therefore uses the backend dependency environment while Aider remains isolated.
- Add PyYAML as an explicit backend validation dependency because `scripts/validate.sh` parses `compose.yaml`.
- Add workflow-contract tests and executor tests for the explicit Aider path. This is source/CI validation only; it does not prove the owner's Windows runner, Ollama model, or local disk persistence.
