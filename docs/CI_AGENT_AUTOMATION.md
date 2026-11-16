# CI-completion-driven development agent

## Purpose

This integration removes minute-by-minute polling. GitHub Actions emits a
`workflow_run` completion event after **Backend tests** finishes. On a
successful run from a repository-owned `build/*` branch, the dispatcher sends
a signed-by-secret HTTPS request to an external coding-agent orchestrator.

The orchestrator is responsible for inspecting the current stacked Draft PR,
selecting the next incomplete BUILD, implementing it, running tests, updating
documentation, and opening a new Draft PR. It must never merge PRs.

## Required repository Actions secrets

Configure these under **Settings → Secrets and variables → Actions → Repository secrets**:

- `NEXUS_AGENT_WEBHOOK_URL`: HTTPS endpoint for the coding-agent orchestrator.
- `NEXUS_AGENT_WEBHOOK_TOKEN`: bearer token accepted by that endpoint.

The endpoint must authenticate the bearer token, validate the repository and
event, deduplicate by `workflow_run_id`, and enqueue work durably. Return a
2xx response only after the event is durably accepted. It should reject
duplicate event IDs idempotently.

## Event contract

The dispatcher sends JSON with:

- `event`: `build.validation.completed`
- `repository`, `workflow_run_id`, `workflow_run_url`
- `head_branch`, `head_sha`, `conclusion`
- `instructions`: preserve stacked Draft PRs, continue only after successful
  validation, add regression tests, never merge, and distinguish CI from live
  provider validation.

Only successful Backend tests runs from branches under `build/` are dispatched.
Failed, cancelled, fork-originated, and unrelated workflow runs are ignored.
The dispatcher has read-only GitHub permissions and does not execute PR code.

## Activation and limitations

1. Add the two repository secrets.
2. Provide and deploy the external coding-agent endpoint with GitHub repository
   access sufficient to create branches, commits, and Draft PRs.
3. Merge this workflow into the repository's default branch before expecting
   GitHub's `workflow_run` trigger to execute. GitHub only discovers this
   trigger from the default branch; a Draft PR alone does not activate it.
4. Run a successful Backend tests workflow on a `build/*` branch and verify
   the dispatcher run and the orchestrator's durable acceptance record.

This repository change supplies the event bridge, not the coding agent itself.
Without the endpoint and secrets, the workflow emits a warning and safely
skips dispatch. It does not claim that autonomous coding is active.
