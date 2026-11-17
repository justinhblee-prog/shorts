# NEXUS STUDIO PRO — Development Job Orchestration

**Checkpoint:** BUILD-00313 (planning and repository-state baseline)  
**Updated:** 2026-11-17  
**Repository:** https://github.com/justinhblee-prog/shorts  
**Status:** Control-plane prototype implemented on Draft PR #321; default-branch autonomous execution is not yet verified.

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
- `backend/development_job_worker.py`: bounded worker lifecycle, heartbeat, retries, and idle draining.
- `backend/development_github_intake.py`: read-only GitHub Issues/PR/Actions intake, deduplication, and explicit per-issue file-scope approval.
- `backend/development_backlog_service.py`: sync → register → worker cycle coordinator.
- `backend/run_development_agent.py`: one-cycle runner that seeds the engineering graph and injects the local Aider/Ollama executor.
- `backend/development_agent_executor.py`: constrained Aider executor with protected-path checks, credential-stripped child environment, scoped diff check, and repository validation.
- `.github/workflows/nexus-development-job-worker.yml`: scheduled/manual self-hosted runner workflow and Draft PR publication step.
- `backend/app.py` and `frontend/app.js`: authenticated read-only development-job API and live status/event panel; lease tokens and raw error details are redacted. `backend/tests/test_development_job_api_security.py` covers the access-control and redaction contract.

The new runner and workflow are code-level implementations, not proof of autonomous operation. CI on hosted Linux validates the Python code and fixtures; it does not validate the Windows self-hosted runner, Ollama availability, real model edits, GitHub token permissions, or scheduled execution from `main`.

Before enabling the workflow on the default branch, configure `NEXUS_GITHUB_READ_TOKEN` as a fine-grained token limited to read-only Issues, Pull requests, Actions, and repository metadata. Configure `NEXUS_APPROVED_SCOPES` only with explicitly approved issue-to-path mappings. The workflow's built-in `GITHUB_TOKEN` is kept separate and is used only by the Draft-PR publication action.

### Remaining ordered gates

1. Confirm the newest `scripts/validate.sh` CI run passes after the runner configuration fix.
2. Review and safely integrate PR #321 into the development branch chain; do not merge it without user approval.
3. After the workflow reaches `main`, verify a manual dispatch on the trusted Windows runner before claiming the schedule is operational.
4. Verify a real Ollama-generated scoped diff, full test result, Draft PR creation, and dependent-job advancement.
5. Verify the existing read-only API/dashboard against a real worker run, then extend it with heartbeat age, active lease expiry, runner availability, and the last successful validation reference.
