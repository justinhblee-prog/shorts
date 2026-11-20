# Workspace Ownership and Timeline Integration

**Status:** Durable registry and authenticated operator API integrated; customer identity migration remains gated.  
**Date:** 2026-11-20

## Existing boundary

The EDL validation endpoint currently relies on fail-closed deployment configuration for operator-to-workspace membership. That mapping is an interim control, not a durable user/workspace lifecycle. EDL validation remains non-persistent and no upload, asset lookup, or render endpoint exists.

## Durable SQLite registry

The new `backend/workspace_store.py` resolves its default database path from `NEXUS_DB_PATH`, falling back to `data/nexus.sqlite3`, matching the API, worker and scheduler stores. An explicit constructor path remains available for isolated tests. This ensures the registry does not silently create a second database when deployed with a custom shared path. It creates:
- workspaces with opaque IDs, names and lifecycle state;
- workspace_memberships with unique principal/workspace pairs, role and revocation status;
- workspace_audit_events with append-only records protected by update/delete triggers.

Workspace creation and initial owner assignment are atomic. Member administration is role-gated. The last owner cannot be revoked, and every membership change is audited. The store requires callers to provide an authenticated principal; it does not treat request-body identity as authentication.

Regression coverage: `backend/tests/test_workspace_store.py`, `backend/tests/test_workspace_access.py`, and `backend/tests/test_operator_workspace_api.py`.

## Operator API integration

The registry is now wired to the existing per-operator review-token authentication boundary through these routes:
- `GET /api/operator/workspaces`: list only the authenticated operator's active workspaces.
- `POST /api/operator/workspaces`: create a workspace; the owner is derived from the authenticated token, never the request body.
- `GET /api/operator/workspaces/{workspace_id}/members`: list active members for a workspace member.\n- `GET /api/operator/workspaces/{workspace_id}/audit`: list bounded immutable audit events for workspace owners/admins.\n- `POST /api/operator/workspaces/{workspace_id}/members`: add an operator principal with admin/editor/viewer role.
- `DELETE /api/operator/workspaces/{workspace_id}/members/{principal_id}`: revoke a member.

All mutations additionally require the `media.manage` operator permission, and the registry enforces workspace owner/admin membership. Request-body principal IDs identify only the member being added or removed; they never establish the caller's identity. This is an operator-management integration, not general end-user/B2B account authentication.

The EDL endpoint supports an explicit migration switch: `NEXUS_WORKSPACE_AUTH_MODE=legacy_config` (default, preserves the existing fail-closed `NEXUS_OPERATOR_WORKSPACES_JSON` behavior) or `NEXUS_WORKSPACE_AUTH_MODE=sqlite` (uses only the durable registry and never falls back to config grants). Unknown modes fail closed. Do not switch production to SQLite mode until operator memberships are provisioned and verified. No automatic import of config mappings occurs.

Remaining gates before general B2B/end-user rollout:
1. Establish a trusted customer principal source for supported login/session/token flows; current principals are configured operators only.
2. Define workspace invitations, owner recovery, suspension, tenant deletion and support access policy.
3. Add a reviewed dry-run migration for existing operator mappings before enabling SQLite mode in production.
4. Expand FastAPI TestClient coverage as customer authentication and invitation flows are implemented; current operator API tests cover authentication, role checks, cross-workspace isolation and request-body identity spoofing.
5. Only then enable customer-owned media assets and workspace-scoped production resources.

No upload, asset read, render submission or MP4 renderer endpoint is added. Browser EDL export remains rendered=false.
