# NEXUS Development Worker — Security Review

Date: 2026-11-21  
Promotion PR: #416  
Branch: `promotion/nexus-worker-mainline-2026-11-20`  
Reviewed workflow/permission contract: `71adeb3ed0c85b0f54ee86714217d4bfd170fdd1`  
Latest PR head at documentation update: `d84273bcc005ec11817aa6894b56c2ecfaec52f7` (documentation-only follow-up after the latest full test run)  
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


## Superseded review note — 2026-11-20

An earlier review note incorrectly claimed that recovery ran inside the write-capable development job. That finding was based on a mistaken reading and is withdrawn. The workflow already had a separate read-only `recover-reviews` job; the correction is documented below. Do not treat the withdrawn finding as an outstanding vulnerability. The remaining operational activation blockers are unchanged.

## Follow-up remediation — 2026-11-20 (source changes; exact-head CI passed)

The two source-level gaps above have been addressed on the promotion branch:

1. **Recovery token boundary:** recovery now runs as a separate `recover-reviews` job with only `contents: read` and `pull-requests: read`. The workflow's top-level permissions default to `contents: read`; write permissions are scoped to `development-cycle`. The development job is explicitly skipped for `mode=recover`, so the read-only path cannot also enter the Aider / PR-publishing job. Recovery uses the job-scoped `GITHUB_TOKEN` rather than a separate personal read token.
2. **Worker presence mismatch:** when the job lease heartbeat succeeds but the worker-presence heartbeat no longer matches the active job context, the worker now treats that mismatch as uncertain ownership, cancels the executor, and returns `lease_lost`. A regression test covers this case.

These source-level changes and regression tests passed on exact PR head `fb9807ee906ba2fa4039176930ac433e9485b2bc` in [Backend tests run 44662978507](https://github.com/justinhblee-prog/shorts/actions/runs/44662978507). The run completed successfully. This validates repository tests and workflow YAML parsing only. It does not remove the OS-level sandbox requirement or provide real Windows/Ollama runtime evidence.


## Latest promotion checkpoint — 2026-11-20

- Exact current PR #416 head `aa28b9d09813f65dd274ff7ec13026b0c703c876` passed [Backend tests run 44664632333](https://github.com/justinhblee-prog/shorts/actions/runs/44664632333): 618 backend tests and explicit worker workflow YAML parsing.
- This confirms source-level regression coverage for the current promotion branch only. It does not establish a real Windows self-hosted runner execution, LocalAppData persistence across runs, Ollama generation, runner account ACLs, network egress restrictions, or OS-level containment.
- Keep PR #416 Draft/open/unmerged. Do not dispatch the worker, enable its schedule, alter runner settings/secrets, merge, or deploy until the dedicated isolated runner and all activation gates are verified.


### Windows process-tree cancellation hardening — 2026-11-20
- On lease loss or executor cancellation, the Windows executor now invokes `taskkill /PID <pid> /T /F` before waiting for Aider, so child processes in the Aider process tree are terminated rather than only the root process. If taskkill fails, it falls back to terminating the root process; this remains best-effort and is not an OS sandbox.
- Added unit coverage for successful process-tree termination and fallback when taskkill fails. Hosted CI validates the code path with mocked Windows process behavior; it does not substitute for real Windows runner execution.


## Current promotion branch verification and activation gate — 2026-11-20

- Current PR #416 documentation head `3b7e99ad97193e6ee95d3a0603ebf6daca7dbb9a` passed exact-head backend/workflow validation in [run 44667178175](https://github.com/justinhblee-prog/shorts/actions/runs/44667178175). The worker implementation head `e671027536d99a17ac211d223281aa103d90c810` passed [run 44667166106](https://github.com/justinhblee-prog/shorts/actions/runs/44667166106), including 620 backend tests and Windows process-tree cancellation/fallback regressions.
- These are hosted CI/source checks only. They do not verify the Windows runner's actual identity, profile isolation, filesystem ACLs, outbound network policy, LocalAppData persistence, or real Ollama generation.
- **Activation remains blocked** until a dedicated low-privilege runner/VM is audited, outbound egress is restricted to required GitHub endpoints and loopback Ollama, unrelated credentials/workspaces are absent, two or more isolated workflow runs prove state persistence, and a disposable Draft-PR recovery roundtrip is observed. No workflow dispatch, schedule activation, runner mutation, secret change, merge or deployment is authorized by this documentation update.


## Latest exact-head checkpoint — 2026-11-20

- Current PR #416 head `f002ce2557ce3180e3333b6674013c3d888c8b32` passed exact-head backend/workflow validation in [run 44670607500](https://github.com/justinhblee-prog/shorts/actions/runs/44670607500).
- The worker implementation head `e671027536d99a17ac211d223281aa103d90c810` passed [run 44667166106](https://github.com/justinhblee-prog/shorts/actions/runs/44667166106), including the Windows process-tree cancellation/fallback regressions.
- PR #416 remains Draft/open/unmerged. Hosted CI does not establish actual Windows runner isolation, account ACLs, network egress restrictions, multi-run LocalAppData persistence or real Ollama generation.
- **Activation remains blocked** until the dedicated low-privilege runner/VM audit and every runtime gate above are completed. No workflow dispatch, schedule activation, runner setting change, secret change, merge or deployment is authorized.


## Review correction — 2026-11-21

The follow-up note above incorrectly described the recovery permission split as still outstanding. Reinspection of the current workflow at promotion head `7cd1941074315ce715c8d1fcb86592f9df21e747` shows that this remediation was already present: `recover-reviews` is a separate job with exactly `contents: read` and `pull-requests: read`; `development-cycle` is separately scoped to `contents: write`, `pull-requests: write`, and `actions: write`; top-level permissions are `contents: read`. The existing workflow-contract suite already asserted the recovery/development split. The earlier follow-up gap statement is therefore superseded and should not be treated as an outstanding vulnerability.

Additional hardening in commit `71adeb3ed0c85b0f54ee86714217d4bfd170fdd1` adds a YAML-parsed exact-map assertion for all three permission scopes. This prevents unreviewed extra write permissions from being silently introduced while retaining the existing structural tests. CI for this exact new test commit is pending at the time of this note.

The operational activation blockers remain unchanged: OS-level sandboxing, dedicated low-privilege runner/VM and ACL audit, outbound egress restrictions, secret inventory, real Windows runner/Ollama execution, cross-run LocalAppData persistence, and a disposable Draft PR recovery round-trip. No worker dispatch or activation was performed.


## Latest permission-contract CI verification — 2026-11-21

- Workflow source at the current branch has three explicit permission scopes: global `{"contents":"read"}`; `recover-reviews` has exactly `{"contents":"read","pull-requests":"read"}`; `development-cycle` has exactly `{"contents":"write","pull-requests":"write","actions":"write"}`.
- Added YAML-parser-based exact-map assertions in test commit `71adeb3ed0c85b0f54ee86714217d4bfd170fdd1`.
- Push run [44842242282](https://github.com/justinhblee-prog/shorts/actions/runs/44842242282) and PR run [44842249505](https://github.com/justinhblee-prog/shorts/actions/runs/44842249505) both passed on test commit `71adeb3ed0c85b0f54ee86714217d4bfd170fdd1`.
- Documentation follow-up run [44842253418](https://github.com/justinhblee-prog/shorts/actions/runs/44842253418) passed on documentation commit `78ec6bd4b95254f9a64b89c24d4d6d37f1877521`. Its logs confirm **621 backend tests passed**, `scripts/validate.sh` succeeded, and the worker workflow YAML parse succeeded.
- The latest PR head `d84273bcc005ec11817aa6894b56c2ecfaec52f7` is a later documentation-only commit; no CI run is shown for that exact SHA. Do not describe it as exact-head tested. The source/test commit `71adeb3...` and the subsequent documentation commit `78ec6bd...` have successful CI evidence as listed above.
- PR #416 was rechecked as Open, Draft, Unmerged, and mergeable. No workflow dispatch, schedule activation, runner/secret change, merge, or deployment was performed.

**Activation remains blocked** on dedicated low-privilege Windows runner/VM isolation, ACL and outbound-egress audit, secret inventory, real Windows self-hosted execution, actual Ollama generation, cross-run LocalAppData persistence, and a disposable Draft PR publication/recovery round-trip.
