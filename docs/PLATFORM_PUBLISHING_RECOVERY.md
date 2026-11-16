# Platform Publishing Recovery Contract

**Product:** NEXUS STUDIO PRO  
**Scope:** YouTube and TikTok publishing attempts, status polling, ambiguous outcomes, and operator recovery  
**Status:** Operational contract for the current implementation; not a claim of live-provider verification.

## Safety invariants

1. A publish attempt is a durable external side effect. A timeout, connection reset, worker crash, or malformed response after dispatch does **not** prove that the platform did nothing.
2. Never create a second publish attempt while the previous remote outcome is unresolved.
3. A confirmed terminal result is monotonic: a late processing response or poll error must not downgrade a completed/handoff state.
4. Human approval must still be current at the transaction that reserves the platform attempt. TikTok additionally requires explicit operator consent and `SELF_ONLY`.
5. Reconciliation and retry are separate actions. Evidence-based reconciliation may establish that an attempt was not executed; it must not silently enqueue or publish again.
6. Keep provider response bodies, credentials, signed URLs, and raw transport errors in protected server-side storage. Routine operator views expose only sanitized state and safe evidence metadata.

## Failure and recovery matrix

| Stage / observed condition | Durable interpretation | Automatic behavior | Safe operator action |
|---|---|---|---|
| Local validation fails before any remote request is dispatched | No remote side effect was initiated | Reject the operation; do not reserve/dispatch a platform request | Correct the input or policy issue, re-run preflight, and obtain current approval if artifacts changed |
| Request may have reached YouTube, but response is lost or ambiguous | Remote outcome unknown; attempt requires reconciliation | Do not start another upload for the same job | Inspect the original attempt and YouTube Studio/account state using the protected operational procedure; attach evidence and resolve the original attempt before any retry |
| YouTube resumable upload has an ambiguous transport outcome | Existing upload attempt remains unresolved | Do not create a fresh upload attempt merely because the client timed out | Determine whether the original upload completed or remains resumable; record evidence and reconcile. Retry only after non-execution is affirmatively established |
| TikTok initialization response is lost before a `publish_id` is persisted | Remote outcome unknown; `reconciliation_required` | Block another initialization request | Check the creator account/platform state and protected attempt evidence; do not infer non-execution from the missing ID |
| TikTok chunk upload response is lost after `publish_id` is known | `reconciliation_required`; retain the known `publish_id` | Block another initialization/upload action; use status confirmation where the attempt remains queryable | Poll/inspect the original publish ID first. If status cannot establish the outcome, escalate for evidence-based reconciliation |
| TikTok status poll temporarily fails while publication is non-terminal | Status remains pending/uncertain; poll failure is audited and backed off | Retry status polling according to the persisted backoff; do not reinitialize the publish | Investigate persistent auth/rate-limit/provider errors without creating another publish attempt |
| TikTok reports `SEND_TO_USER_INBOX` | Distinct inbox handoff state; not equivalent to public completion | Preserve the handoff state and suppress duplicate publish actions | Treat as an inbox handoff requiring the creator-side next step; do not label it publicly published |
| TikTok reports `PUBLISH_COMPLETE` | Terminal completion; persist returned video ID when present | Duplicate publish action returns the durable terminal result; no second init/upload | Verify the account-side result if needed; do not republish the same job |
| Late processing status or late poll error arrives after a terminal result | Stale observation | Record only informational audit context; do not downgrade terminal state | No retry or corrective publish is warranted solely because of the late observation |
| Operator has affirmative evidence the remote request was not executed | `not_executed_confirmed` only after explicit evidence-backed reconciliation | Reconciliation itself does not retry | A separately authorized retry may be considered after rechecking current approval, artifact identity, platform policy, and idempotency constraints |
| Operator cannot establish whether the remote request executed | Outcome remains unresolved | Fail closed; no retry | Escalate to platform/account support or continue evidence collection; preserve the unresolved state |

## Platform-specific rules

### YouTube

- Publishing is private-only in the current workflow.
- The real publisher reserves an attempt only while the durable queue job is still the approved `short_video_production` job, checked in the same immediate transaction as reservation.
- Ambiguous resumable-upload outcomes must be reconciled against the original attempt. A fresh upload is not a timeout recovery strategy.
- The operator must distinguish a confirmed completed upload from an incomplete or still-resumable session. Do not treat a missing local response as proof of failure.

### TikTok

- Publishing remains `SELF_ONLY`; no public-posting mode is introduced by this contract.
- Explicit operator consent, creator privacy capability, AIGC disclosure evidence, current review approval, and current approved queue state are prerequisites.
- When a `publish_id` is known, query the original publish status before considering any other action.
- `SEND_TO_USER_INBOX` is tracked separately from `PUBLISH_COMPLETE`.
- Lost initialization or chunk-upload responses enter `reconciliation_required`; duplicate initialization/upload is blocked until resolution.

## Reconciliation evidence checklist

For every ambiguous attempt, retain the following in the protected operational record:

- Internal job ID and platform attempt ID
- Platform and operation stage (initialization, chunk transfer, status poll, or completion)
- Request-dispatch timestamp and last known response/status timestamp
- Whether a platform-side identifier is known (for TikTok, the `publish_id`)
- Operator identity, timestamp, evidence reference, and concise rationale
- Explicit conclusion: executed, not executed, or still unknown

Never place access tokens, signed upload URLs, raw response bodies, or unredacted transport exceptions in the evidence reference or routine API response.

## Retry authorization gate

A retry is eligible only when **all** conditions hold:

1. The original attempt is affirmatively reconciled as not executed; uncertainty alone is insufficient.
2. Current human approval and the approved queue state are revalidated at reservation time.
3. The exact media artifact and caption/disclosure inputs are rechecked; changed artifacts require a new review.
4. Platform-specific privacy and consent requirements still hold.
5. The retry is a separate, auditable operator action.

A reconciliation operation must never implicitly trigger the retry.

## Implementation and validation boundary

The current regression suite covers transactional current-approval fencing, TikTok `SELF_ONLY` lifecycle and terminal status idempotency, late-status monotonicity, polling backoff, and ambiguous TikTok initialization/chunk-upload retry fencing. Existing YouTube tests cover private upload and ambiguous resumable-upload recovery protections. BUILD-00205's audited provider-attempt reconciliation is an AI/provider-attempt workflow and must not be represented as a platform-publishing reconciliation endpoint unless a dedicated platform endpoint is separately implemented.

All CI transport/provider tests use deterministic doubles. They do **not** establish live YouTube/TikTok OAuth validity, account permissions, actual upload behavior, platform-side status correctness, or production recovery readiness. Those remain explicit deployment-validation tasks.
