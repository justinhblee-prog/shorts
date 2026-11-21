# NEXUS Development Worker — Security Review

Date: 2026-11-21
Promotion PR: #416
Branch: `promotion/nexus-worker-mainline-2026-11-20`
Reviewed PR head: `8028d2688e5f5f6ba9db6e84099530cbc2a22df6`
Status: Hosted source validation passed; operational activation remains blocked.

## Scope reviewed

- `.github/workflows/nexus-development-job-worker.yml`
- `backend/development_github_intake.py`
- `backend/development_agent_executor.py`
- `backend/development_job_worker.py`
- `backend/development_jobs.py`
- `backend/publish_development_reviews.py`
- `backend/recover_development_reviews.py`
- `backend/tests/test_development_worker_workflow_contract.py`

## Verified source controls

1. Intake is read-only. Only open, labeled issues are candidates; issue text does not infer writable file scope.
2. File scope requires an explicit `NEXUS_APPROVED_SCOPES` mapping. Missing configuration fails closed. Mapping size/counts are bounded, canonical-repository-bound, and reject absolute paths, traversal, duplicates, and paths resolving outside the repository.
3. Executor checks protected paths and symlink targets, requires a clean worktree, limits actual changes to approved scope, runs `git diff --check` and `scripts/validate.sh`, and requires validation evidence.
4. The coding child process receives an isolated user configuration home and has workflow/provider credentials and credential-helper configuration removed from its environment.
5. Lease heartbeats use fencing tokens; expired leases revoke the old token before reclaim. SQLite write paths use `BEGIN IMMEDIATE`.
6. Completion requires evidence for the exact open, unmerged Draft PR, including repository, base/head refs, head SHA, and changed-file set.
7. Recovery is a separate `recover-reviews` job with read-only token permissions. It only inspects a matching existing Draft PR; ambiguous or missing matches remain pending. It does not create, merge, approve, or close PRs.
8. Worker continuation is bounded to 1–10 chained runs and is gated on a verified Draft PR update.
9. Workflow triggers are `workflow_dispatch` and a two-hour schedule. There are no `pull_request`, `pull_request_target`, `workflow_run`, or `issue_comment` execution triggers.

## GitHub token permission map

The workflow currently declares these exact permission maps:

- Workflow default: `{"contents":"read"}`
- `recover-reviews`: `{"contents":"read","pull-requests":"read"}`
- `development-cycle`: `{"contents":"write","pull-requests":"write","actions":"write"}`

The YAML-parsed workflow contract test asserts these maps exactly. This replaces earlier text-only assertions and guards against accidental permission expansion.

The read-only intake token (`NEXUS_GITHUB_READ_TOKEN`) is distinct from the job token used for Draft PR publication and bounded workflow continuation. The development job's write scopes are job-scoped, not workflow-global.

## Residual risks — hard activation blockers

### No OS-level sandbox

Aider runs as the Windows self-hosted runner account. Removing credentials from the child environment and constraining Git paths do not prevent access to other files, processes, local services, or network resources available to that account. Prompt instructions are not a security boundary.

Before activation, require:
- A dedicated runner machine or isolated VM for this repository.
- A dedicated low-privilege Windows account without personal browser sessions, unrelated workspaces, SSH keys, cloud credentials, or production secrets.
- Filesystem ACLs that confine the runner and Ollama model/cache directories.
- Outbound network restrictions to required GitHub endpoints and loopback Ollama; deny production databases and unrelated internal services.
- An audited inventory of runner environment variables, credentials, and secrets.

### Runtime evidence still missing

- Real Windows self-hosted runner execution under the intended restricted account.
- Actual local Ollama model availability and successful generation.
- Two or more separate workflow runs proving SQLite state persists under LocalAppData.
- Verified runner identity, filesystem ACL, network egress, and secret inventory.
- A disposable Draft PR publication/recovery round-trip.

Hosted CI and mocked Windows-process tests do not establish any of these runtime properties.

## Latest CI evidence

PR head `8028d2688e5f5f6ba9db6e84099530cbc2a22df6` passed [Backend tests run 44843382240](https://github.com/justinhblee-prog/shorts/actions/runs/44843382240). All job steps succeeded:
- dependency installation
- `sh scripts/validate.sh`, including Python compile checks and backend unittest discovery
- explicit PyYAML parse of the worker workflow

The preceding permission-contract commits `71adeb3ed0c85b0f54ee86714217d4bfd170fdd1` and `78ec6bd4b95254f9a64b89c24d4d6d37f1877521` also passed their recorded CI runs. The latest exact-head run above supersedes the earlier “CI pending” note.

This is hosted repository validation only. It is not evidence of Windows self-hosted execution, OS containment, or Ollama runtime success.

## Operational decision

**Do not activate the worker yet.** Keep PR #416 Draft and unmerged until all OS isolation, account/ACL/egress/secret audits, Windows/Ollama runtime checks, persistence checks, and disposable PR recovery checks are complete.

No workflow dispatch, schedule activation, runner configuration change, secret change, merge, or deployment was performed as part of this review.


## Development monitor security boundary — DEV-ORCH-008

- The monitor adds only authenticated GET routes guarded by `development.read`.
- The operator role receives this read permission; reviewer and worker roles do not. Admin retains its existing wildcard grant.
- Responses exclude worker lease tokens and hostnames. Job event details are intentionally omitted from the browser API.
- The configured SQLite path must already exist and pass a read-only schema inspection before the store is opened. Missing configuration/file/schema fails closed with HTTP 503 rather than creating an empty queue.
- The API exposes no development-job mutation, retry, recovery, runner dispatch, PR mutation, merge, or deployment action.
- The host-sharing requirement remains an operational gate: the API process must read the exact same persistent SQLite file used by the Windows worker. This code does not mount or copy LocalAppData data into a container.
- Hosted tests can validate route/RBAC contracts and read-only response behavior. They cannot establish actual Windows ACLs, shared-file visibility, or browser connectivity.
