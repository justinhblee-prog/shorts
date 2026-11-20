# NEXUS Development Worker — Security Review

Date: 2026-11-20  
Promotion PR: #416  
Branch: `promotion/nexus-worker-mainline-2026-11-20`  
Status: Static review complete; operational activation blocked.

## Review scope

- `.github/workflows/nexus-development-job-worker.yml`
- `backend/development_github_intake.py`
- `backend/development_agent_executor.py`
- `backend/development_job_worker.py`
- `backend/development_jobs.py`
- `backend/publish_development_reviews.py`
- `backend/recover_development_reviews.py`

## Verified in source

1. Backlog intake is read-only. Only open, labeled issues are candidates; issue text does not infer file scope.
2. Import requires an explicit `NEXUS_APPROVED_SCOPES` mapping. Missing configuration becomes an empty mapping and therefore fails closed.
3. Scope validation rejects traversal, protected paths, repository escapes, and symlink targets resolving to protected paths.
4. The coding child process receives an isolated user configuration home and has workflow/Git/provider credentials and credential-helper configuration removed.
5. The executor requires a clean worktree, checks all changed paths against the declared scope, runs `git diff --check` and `scripts/validate.sh`, and requires a validation evidence reference.
6. Lease heartbeats use fencing tokens; expired leases revoke the old token before the job can be claimed again. SQLite write paths use `BEGIN IMMEDIATE`.
7. Job completion is gated on an exact, open, unmerged Draft PR whose repository, base/head refs, head SHA, and changed-file set are checked.
8. Recovery only inspects an existing matching Draft PR. Ambiguous or missing matches leave jobs pending; recovery does not create, merge, approve, or close PRs.
9. Workflow continuation is bounded by a 1–10 run counter and does not run in recovery mode.

## Residual risks — activation blockers

### No OS-level sandbox

The Aider process runs as the Windows self-hosted runner account. Removing credentials from its child environment and constraining Git paths does **not** prevent access to other files, processes, local services, or network resources available to that account. Prompt text is not a security boundary.

Required before activation:
- Dedicated runner machine or isolated VM exclusively for this repository.
- Dedicated low-privilege Windows account; no personal profile, browser sessions, unrelated workspaces, SSH keys, cloud credentials, or production secrets.
- Restrict outbound network access to required GitHub endpoints and loopback Ollama; deny access to production databases and unrelated internal services.
- Keep runner service permissions and local Ollama model/cache directories scoped to that account.
- Never accept fork pull-request or other untrusted external events as execution triggers.

### GitHub permissions

The job requests `contents: write`, `pull-requests: write`, and `actions: write`. These are used for pushing the stable automation branch, creating/updating a Draft PR, and bounded workflow continuation. Review whether repository policy and a dedicated GitHub App/token can reduce the permission surface before activation. Keep intake/recovery credentials read-only and separately scoped.

### Runtime evidence still missing

- Real Windows self-hosted runner execution.
- Actual local Ollama model availability and generation.
- Two or more separate workflow runs proving SQLite state persists under LocalAppData.
- Runner identity, filesystem ACL, network egress, and secret inventory audit.
- A real Draft PR publication/recovery round-trip on a disposable test repository or approved isolated test branch.

## CI evidence

Latest PR head: `13f9b1308a660e2a1799aba2c5aba39212008217`

Run [44649909418](https://github.com/justinhblee-prog/shorts/actions/runs/44649909418) passed on that exact head:
- dependency installation
- `sh scripts/validate.sh`
- explicit PyYAML parse of the worker workflow

This CI run validates the repository test environment, not the Windows self-hosted runner or Ollama runtime.

## Operational decision

**Do not merge or activate the scheduled/manual worker yet.** Keep PR #416 Draft until the activation blockers above are verified. No workflow dispatch, schedule activation, runner configuration change, secret change, deployment, or merge was performed as part of this review.
