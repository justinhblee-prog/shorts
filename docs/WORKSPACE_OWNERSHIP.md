# Workspace Ownership and Timeline Integration

**Status:** Durable registry increment; API migration remains gated.  
**Date:** 2026-11-20

## Existing boundary

The EDL validation endpoint currently relies on fail-closed deployment configuration for operator-to-workspace membership. That mapping is an interim control, not a durable user/workspace lifecycle. EDL validation remains non-persistent and no upload, asset lookup, or render endpoint exists.

## Durable SQLite registry

The new backend/workspace_store.py uses the shared NEXUS_DB_PATH SQLite database and creates:
- workspaces with opaque IDs, names and lifecycle state;
- workspace_memberships with unique principal/workspace pairs, role and revocation status;
- workspace_audit_events with append-only records protected by update/delete triggers.

Workspace creation and initial owner assignment are atomic. Member administration is role-gated. The last owner cannot be revoked, and every membership change is audited. The store requires callers to provide an authenticated principal; it does not treat request-body identity as authentication.

Regression coverage: backend/tests/test_workspace_store.py.

## API integration gates

The registry is deliberately not yet wired into FastAPI authentication. Existing review credentials identify configured operators, not general end users. Automatically importing NEXUS_OPERATOR_WORKSPACES_JSON would silently convert deployment settings into persistent grants.

Before replacing the interim mapping:
1. Establish a trusted principal source for every supported login/session/token.
2. Define workspace invitations, owner recovery and suspension policy.
3. Add a reviewed dry-run migration for existing operator mappings.
4. Prove request-body identity spoofing and cross-workspace access fail in API tests.
5. Only then enable workspace-scoped media assets.

No upload, asset read, render submission or MP4 renderer endpoint is added. Browser EDL export remains rendered=false.
