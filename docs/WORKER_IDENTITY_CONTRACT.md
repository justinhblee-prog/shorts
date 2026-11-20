# NEXUS STUDIO PRO — Worker Identity & Workspace Grant Contract

**Status:** Opt-in API protocol implemented; no worker credentials are configured and the existing direct-SQLite worker has not migrated.
**Date:** 2026-11-20
**Scope:** Trusted worker authentication, workspace grants, and lease fencing.

## Current state and security boundary

- The production worker currently opens the shared SQLite database directly and registers a process generation token in `worker_registry`.
- The generation token fences stale process incarnations; it is not an authentication credential. `worker_id`, hostname, lease token, and generation token do not independently prove a trusted machine or tenant grant.
- Legacy HTTP job claim/heartbeat/complete/fail endpoints authorize through the operator/reviewer permission system. They are disabled with HTTP 410 when worker credential mode is configured; they remain available only for the unconfigured legacy compatibility mode.
- Operator workspace membership protects operator APIs only. It must not be re-used as a worker authorization source.
- No customer-safe worker isolation claim is permitted until a worker credential is authenticated and bound to an explicit workspace allow-list.

## Implemented opt-in credential contract

- Added `backend/worker_auth.py` with SHA-256 digest verification and constant-time comparison. The plaintext token is never stored or returned.
- Added `NEXUS_WORKER_CREDENTIALS_JSON` configuration. Each worker entry requires a valid worker ID, a 64-character SHA-256 digest, and a unique, non-empty explicit workspace allow-list. Wildcards and NULL/unassigned grants are rejected.
- Added `/api/worker/v1/register`, `/claim`, and per-job `/heartbeat`, `/complete`, `/fail` endpoints. The authenticated credential determines worker ID and allowed workspaces; the API derives each job's workspace from the durable queue row rather than accepting a client workspace selector.
- Claim is restricted to the short_video_production job type and workspace-filtered. Every lease transition includes the resolved workspace ID plus the server-issued process generation token. Re-registration rotates the generation and stale claim/heartbeat/complete/fail calls are rejected. Legacy operator-token worker endpoints return 410 once credential mode is configured.
- The feature is dormant by default: no credentials or secrets were added to repository or runtime settings.

## Required credential contract

A future worker credential must be a high-entropy secret provisioned out of band for one worker identity. Runtime configuration should store only a SHA-256 digest, never the raw secret:

```json
{
  "worker-prod-a": {
    "token_sha256": "<64 lowercase hex characters>",
    "workspace_ids": ["ws_acme"]
  }
}
```

Requirements:

1. Reject missing, malformed, duplicate, empty, or unknown credential entries at startup/request time with fail-closed behavior.
2. Parse only a Bearer authorization credential; hash the presented token and compare with `hmac.compare_digest`.
3. Bind the credential to one immutable `worker_id`; ignore/reject a request body worker ID that does not exactly match the authenticated identity.
4. Bind each worker to an explicit, non-empty list of workspace IDs. No wildcard grants and no implicit access to NULL/unassigned legacy jobs.
5. Validate workspace ownership in the queue SQL query for claim and again in heartbeat/complete/fail transactions. A lease token is a fencing value, not a tenant authorization decision.
6. Require a server-issued process-generation token for every state-changing lease operation. Re-registration rotates the token and fences the previous process.
7. Keep credentials out of logs, error bodies, traces, crash reports, and worker metadata. Support rotation/revocation without changing customer identity.
8. Record append-only worker registration, grant change, revocation, and security failure audit events. Do not log raw credentials or credential hashes.
9. Use separate credentials per environment and worker. Production credentials must not be present in preview, CI, developer workstations, or untrusted PR jobs.

## Required protocol

- Register: authenticate the credential, verify configured worker identity, record hostname as untrusted diagnostic metadata, and issue a generation token.
- Claim: require the current generation token and claim only jobs whose immutable `workspace_id` is in the credential's allow-list. Do not claim unassigned legacy jobs.
- Heartbeat / complete / fail: authenticate the same worker credential, verify worker identity and current generation, then apply the lease transition with the job's workspace ID in the same transaction.
- Production provider execution: the execution process must receive the verified workspace from the claimed durable job; never accept a worker-supplied workspace selector as authority.
- Revocation: deny the next request and fence the process generation; any in-flight provider operation must follow the existing ambiguous-outcome reconciliation rules.

## Deployment prerequisites

- Decide whether the worker remains a same-host direct-DB process or becomes a separately authenticated API client. Do not mix these trust models implicitly.
- For direct-DB mode, enforce OS-level account isolation, database file ACLs, secret-file ACLs, and process/network sandboxing. A credential in an environment variable does not protect a process that can read the SQLite database directly.
- For remote API mode, implement the credential protocol above, TLS, secret rotation, rate limits, and workspace-scoped lease operations before migrating workers.
- The isolated Windows runner requirements in the worker-promotion audit remain separate; worker credentials do not replace OS-level sandboxing.

## Acceptance tests

- Unknown/malformed/expired/revoked credential is rejected.
- A worker cannot claim another worker's identity by changing JSON fields.
- Worker A cannot claim, heartbeat, complete, fail, or execute a job in workspace B.
- Worker credentials cannot access NULL/unassigned legacy jobs.
- A stale generation token cannot heartbeat or mutate after restart/re-registration.
- A credential with multiple explicit grants cannot access a workspace outside that list.
- No raw token, token digest, or authorization header appears in application logs or audit payloads.
- Revocation denies the next operation while preserving ambiguous provider outcomes for reconciliation.

## Remaining limitations / not implemented

- The current production worker still opens SQLite directly and does not consume the new remote worker API. Direct database access bypasses HTTP worker credential checks; do not treat this as full worker isolation.
- Registration/revocation audit events are not yet a separate append-only worker-security journal. Credential rotation/revocation is performed by changing the configured digest/grant map; there is no expiry metadata or automated rotation workflow.
- No credentials, environment values, runner settings, or production execution paths were activated. The opt-in API must not be used until the worker runtime is migrated and OS/network isolation is independently verified.
- The new API and authentication tests cover digest validation, grant restrictions, workspace-fenced claim/lease transitions, legacy endpoint shutdown, and stale-generation rejection. Current CI for the newest implementation commit is pending; do not mark this slice validated until Backend/Chromium and Compose workflows pass.
