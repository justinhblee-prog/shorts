# NEXUS Development Worker — Security Review

Date: 2026-11-20  
Promotion PR: #416  
Branch: `promotion/nexus-worker-mainline-2026-11-20`  
Reviewed code head: `fc012073d4dc447b4d2e871840bb2b1f56fc836b`  
Status: Static review and repository CI complete; operational activation blocked.

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
3. Approval configuration is bounded (64 KiB JSON, at most 500 issue entries and 100 paths per issue), tied to canonical issue references in the configured repository, and rejects absolute paths, traversal, duplicate paths, and paths that resolve outside the repository. Executor validation additionally rejects protected paths and symlink targets resolving to protected paths.
4. The coding child process receives an isolated user configuration home and has workflow/Git/provider credentials and credential-helper configuration removed.
5. The executor requires a clean worktree, checks all changed paths against the declared scope, runs `git diff --check` and `scripts/validate.sh`, and requires a validation evidence reference.
6. Lease heartbeats use fencing tokens; expired leases revoke the old token before the job can be claimed again. SQLite write paths use `BEGIN IMMEDIATE`.
7. Job completion is gated on an exact, open, unmerged Draft PR whose repository, base/head refs, head SHA, and changed-file set are checked.
8. Recovery only inspects an existing matching Draft PR. Ambiguous or missing matches leave jobs pending; recovery does not create, merge, approve, or close PRs.
9. Workflow continuation is bounded by a 1–10 run counter and does not run in recovery mode.
10. The workflow's only configured triggers are manual `workflow_dispatch` and a repository schedule. It has no `pull_request`, `pull_request_target`, or `workflow_run` execution trigger. Keep it that way: untrusted fork PR content must never be an execution trigger.

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

The workflow-level token requests `contents: read`, `pull-requests: write`, and `actions: write`; the job elevates `contents` to `write` only for the development job that pushes the stable automation branch. The write permissions support Draft PR publication and bounded workflow continuation. Unused `issues` permissions were removed from both scopes. Keep intake/recovery credentials read-only and separately scoped. Before activation, verify that repository policy and the selected token model preserve this least-privilege boundary.

### Runtime evidence still missing

- Real Windows self-hosted runner execution.
- Actual local Ollama model availability and generation.
- Two or more separate workflow runs proving SQLite state persists under LocalAppData.
- Runner identity, filesystem ACL, network egress, and secret inventory audit.
- A real Draft PR publication/recovery round-trip on a disposable test repository or approved isolated test branch.

## CI evidence

Code head `fc012073d4dc447b4d2e871840bb2b1f56fc836b` passed the full backend validation and worker workflow YAML parse in [Backend tests run 44651878820](https://github.com/justinhblee-prog/shorts/actions/runs/44651878820). The run completed successfully on that exact commit. All job steps passed:
- dependency installation
- `sh scripts/validate.sh` (Python compile check and full backend unittest discovery)
- explicit PyYAML parse of the worker workflow

This CI run validates the repository test environment, not the Windows self-hosted runner, OS isolation, or Ollama runtime.

## Operational decision

**Do not merge or activate the scheduled/manual worker yet.** Keep PR #416 Draft until the activation blockers above are verified. No workflow dispatch, schedule activation, runner configuration change, secret change, deployment, or merge was performed as part of this review.


## Follow-up static review — 2026-11-20

A second review of the current PR head identified one additional least-privilege gap that must be closed before activation:

### Recovery mode inherits write-capable job permissions

The workflow currently implements development and recovery as conditional steps inside the same `development-cycle` job. That job grants `contents: write`, `pull-requests: write`, and `actions: write` for the entire job, including when `mode=recover`. Recovery code itself only performs GitHub GET requests and writes local SQLite evidence, but its job token still has write-capable permissions. The separate `NEXUS_GITHUB_READ_TOKEN` does not reduce the permissions of the job-scoped `GITHUB_TOKEN`.

Required remediation before activation:
- Split recovery into a distinct job with only `contents: read` and `pull-requests: read` (and no Actions write permission).
- Keep write permissions only on the development job that publishes the stable Draft PR and dispatches bounded continuation.
- Keep the recovery job's token unavailable to the Aider execution path; recovery must remain read-only.
- Add workflow-contract tests that assert the recovery job has no write permissions and the development job has only the exact writes it needs.

This is a source-level permission-boundary issue, not evidence of an observed unauthorized write. No workflow was dispatched and no repository permissions or secrets were changed. The current CI result does not validate GitHub token effective permissions at runtime.
