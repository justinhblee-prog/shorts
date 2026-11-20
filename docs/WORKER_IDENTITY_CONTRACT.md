# NEXUS STUDIO PRO — Worker Identity & Workspace Grant Contract

**Status:** Design contract only; no credential mode is enabled by this document.
**Date:** 2026-11-20
**Scope:** Trusted worker authentication, workspace grants, and lease fencing.

## Current state and security boundary

- The production worker currently opens the shared SQLite database directly and registers a process generation token in `worker_registry`.
- The generation token fences stale process incarnations; it is not an authentication credential. `worker_id`, hostname, lease token, and generation token do not independently prove a trusted machine or tenant grant.
- Legacy HTTP job claim/heartbeat/complete/fail endpoints currently authorize through the operator/reviewer permission system. They are not an independent worker identity protocol.
- Operator workspace membership protects operator APIs only. It must not be re-used as a worker authorization source.
- No customer-safe worker isolation claim is permitted until a worker credential is authenticated and bound to an explicit workspace allow-list.

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

## Explicitly not implemented

This file is a contract, not a live credential system. No worker secrets, environment variables, API credentials, runner configuration, or production execution paths were changed. Do not mark worker identity binding complete until implementation and acceptance tests pass.
