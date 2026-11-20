# NEXUS STUDIO PRO — Customer Identity Contract (Provider-Neutral)

Date: 2026-11-20  
Version: 0.11.0  
Branch: `ui/nexus-premium-visual-refresh-2026-11-20`  
PR: #417 (Draft / Open / Unmerged)

## Status

This document defines the application-side contract required before customer authentication can be connected. It deliberately does **not** select, configure, or activate an identity provider. Provider selection, contractual terms, data residency, billing, and security configuration remain an explicit product/security decision.

The current `reviewer_auth` and operator credentials are internal operator/reviewer credentials. They are not customer identities and must not be repurposed as customer login.

## Canonical principal

A customer principal is the immutable pair:

`(issuer, subject)`

- `issuer` is the exact issuer identifier from a cryptographically verified identity token.
- `subject` is the exact subject identifier from that same verified token.
- The pair is namespaced and compared exactly. Do not lowercase, trim, case-fold, or otherwise normalize either value.
- Email, display name, username, phone number, and organization name are profile attributes, never primary identity keys.
- Never accept a principal, issuer, subject, role, or workspace owner from request JSON, query parameters, browser storage, or untrusted proxy headers.

The application should derive a stable internal opaque principal ID from a durable database mapping, not expose raw provider identifiers as resource IDs. A suggested mapping is:

- `customer_identities(id, issuer, subject, status, created_at, updated_at)`
- Unique constraint on `(issuer, subject)`
- `id` is an opaque internal identifier.
- Identity rows are retained as tombstones when access is revoked; do not silently recycle IDs.

## Token verification boundary

A future provider adapter must return a verified identity context only after all checks succeed:

1. Verify signature using trusted issuer metadata/JWKS and an allowlisted algorithm policy.
2. Validate exact `iss`, intended `aud`, expiry, not-before, and issued-at policy.
3. Validate nonce/state and PKCE for interactive authorization flows where applicable.
4. Reject missing, malformed, ambiguous, expired, or unverifiable claims.
5. Resolve `(issuer, subject)` to the internal principal mapping.
6. Attach the principal to request context through trusted server-side middleware/dependencies.

Do not trust a decoded-but-unverified JWT. Do not use an email claim as a fallback when `sub` is absent. Do not infer tenant membership from a verified identity alone.

## Workspace ownership and authorization

Identity answers **who** is making the request. Workspace membership answers **which tenant resources** that principal may access.

- A customer principal must have an explicit active membership row for every workspace access.
- Workspace roles remain `owner`, `admin`, `editor`, and `viewer`; each API operation must enforce a documented minimum role/capability.
- Workspace IDs supplied by clients are selectors only. They never grant access by themselves.
- Resolve membership from the authenticated principal and requested workspace on every request; fail closed on missing, revoked, suspended, or unknown membership.
- Resource queries must scope by `workspace_id` in the database query itself, not fetch globally and filter in application memory.
- Child resources must be checked against the same workspace as their parent. Reject mismatched parent/child workspace IDs.
- Operator/reviewer administration remains a separate trust domain and must not implicitly grant customer workspace access.

## Account linking

Account linking is a security-sensitive workflow, not an email matching operation.

- Linking a second identity requires proof of control of both the currently authenticated account and the new identity, or a separately approved recovery process.
- Never auto-link identities solely because email addresses match, even when an email is marked verified.
- Record who initiated the link, which identity was added, the time, and the result in an append-only security audit event.
- Unlinking must not strand the account without a usable authentication method; enforce recovery policy before removal.
- Support duplicate and concurrent linking attempts with database uniqueness and transactional conflict handling.

## Workspace provisioning and lifecycle

- Initial workspace ownership must be assigned by a trusted server-side provisioning operation to the authenticated internal principal.
- Do not accept `owner_principal_id` from customer request bodies.
- Invitations must be single-use, expiring, scoped to one workspace and one intended role, and redeemed only by an authenticated principal.
- Revocation takes effect on the next authorization check. Existing access tokens must not preserve workspace access after membership revocation.
- Workspace suspension blocks all customer reads and writes, including background task submission and signed asset URL issuance.
- Deletion/retention behavior must be defined separately from membership revocation and must preserve legally required audit evidence.

## Data and worker propagation requirements

Before customer multi-tenancy can be called complete:

1. Add nullable `workspace_id` to tenant-owned records with additive migrations.
2. Preserve legacy rows as explicitly unassigned; never guess ownership during backfill.
3. Resolve workspace ownership at the API boundary and persist it with every created resource.
4. Propagate immutable `workspace_id` and internal principal attribution through queue payloads, leases, worker execution, provider attempts, reconciliation, and audit events.
5. Enforce workspace scope in trend, brand, production, review, schedule, publishing, analytics, finance, and asset queries.
6. Partition OAuth connections and provider credentials by workspace and provider account; never share a tenant token implicitly.
7. Store uploaded assets under tenant-scoped opaque paths and authorize every read, write, preview, and signed URL.
8. Scope idempotency keys, quotas, retention, exports, and background retries to the workspace.
9. Add cross-tenant denial tests for every resource family and every parent/child relationship.

A workspace ID in a queue message is not authorization by itself. Workers must validate that the referenced job and resource records belong to that workspace before acting.

## Migration and rollout gates

- Keep `NEXUS_WORKSPACE_AUTH_MODE=legacy_config` as the compatibility default until a separately reviewed migration is complete.
- The current SQLite workspace registry is an operator-facing foundation; it is not proof of customer authentication or complete tenant isolation.
- Do not bulk-assign existing records to a workspace without verified ownership evidence and a reversible migration plan.
- Run schema expansion, dual-read/compare, explicit ownership backfill, enforcement, and cleanup as separately observable stages.
- Provide rollback instructions for each migration stage; do not drop legacy columns or records during initial rollout.
- Production enforcement requires cross-tenant tests, migration rehearsal on a copy, backup/restore verification, and security review.

## Required test matrix

- Same `sub` from different `iss` values resolves to different principals.
- Same `iss` + `sub` resolves consistently across sessions and token refresh.
- Email changes do not change principal identity.
- Unverified, expired, wrong-audience, wrong-issuer, and malformed tokens are rejected.
- Request-body identity/owner/role spoofing is ignored or rejected.
- Missing, revoked, suspended, and cross-workspace memberships are denied.
- A user cannot read or mutate another workspace's parent or child resources.
- Queue/worker/provider retries preserve workspace attribution and cannot cross tenant boundaries.
- Concurrent invitations, identity linking, and membership changes preserve uniqueness and audit integrity.
- Legacy unassigned records remain inaccessible to customer-scoped queries until explicitly assigned.

## Explicitly unresolved external decisions

The following must be approved before activation:

- Identity provider and contractual plan.
- Supported login methods and account recovery policy.
- Required regions/data residency and retention policy.
- MFA/enterprise SSO requirements.
- Customer account lifecycle, invitations, and support-assisted recovery.
- Billing/account ownership relationship.

No provider credentials, redirect URIs, secrets, production settings, or live login flows were configured as part of this work.
