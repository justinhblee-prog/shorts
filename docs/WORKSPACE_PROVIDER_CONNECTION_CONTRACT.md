# Workspace Provider Connection Contract

**Version:** 0.1  
**Date:** 2026-11-20  
**Status:** Design and migration contract only. Existing OAuth integrations remain global/singleton.

## 1. Problem and boundary

The current YouTube and TikTok OAuth stores use singleton token rows and global OAuth state. Publication jobs, provider attempts, and analytics records now have workspace ownership, but the credentials used to publish and collect metrics are still service-wide. This is not yet independent B2B channel connectivity.

No workspace may be allowed to use another workspace's provider credentials, creator identity, refresh token, analytics history, or disconnect operation.

## 2. Target data model

Use provider-neutral connection metadata with provider-specific encrypted token payloads.

- provider_connections: immutable connection ID, workspace_id NOT NULL, provider (youtube/tiktok), provider account ID, display label, connection status, granted scopes, created/updated/verified timestamps, revocation metadata.
- provider_oauth_states: hashed state, workspace ID, initiating principal ID, provider, redirect URI fingerprint, PKCE verifier ciphertext/reference, expiry, consumed timestamp, creation timestamp.
- provider_token_secrets: connection ID, encrypted access token, encrypted refresh token, encryption key version, nonce/algorithm metadata, token expiry timestamps, updated timestamp.
- provider_refresh_leases: connection ID, owner ID, lease token, expiry; one active refresh per connection.
- provider_connection_events: append-only connection-created, token-refreshed, scope-changed, verification-failed, disconnected, revoked, and key-rotated audit events.

Use foreign keys and indexes beginning with workspace ID. Do not put access tokens, refresh tokens, authorization codes, PKCE verifiers, or raw provider responses into audit events.

## 3. Encryption and secret management

- Use envelope encryption with a managed KMS/key vault in production. Encrypt token payloads with a data-encryption key and wrap that key with a versioned KMS key.
- Local development may use an explicit 32-byte key supplied through an out-of-band secret manager or local-only secret file; never commit the key or use a hardcoded fallback.
- Store key version and algorithm metadata with ciphertext so rotation can decrypt/re-encrypt without exposing plaintext.
- Use authenticated encryption (AES-256-GCM or an approved KMS envelope primitive); verify authentication tags before returning tokens.
- Fail closed if encryption configuration is missing, malformed, or the key version is unavailable. Do not silently read/write singleton global tokens in tenant mode.

## 4. OAuth flow

1. Authenticated operator chooses an active workspace and provider.
2. Server verifies workspace.read plus a provider-specific connect permission and active membership.
3. Server creates a random one-time OAuth state, stores only its hash, and binds it to workspace, principal, provider, redirect URI, PKCE metadata, and short expiry.
4. Callback consumes the state exactly once and verifies provider, workspace, principal, redirect URI, expiry, and PKCE before token exchange.
5. Server verifies provider account identity and granted scopes, encrypts token material, creates a workspace-owned connection, and appends an audit event.
6. Every publish, refresh, creator-info, analytics, disconnect, and status request resolves the connection by the authenticated workspace. A caller cannot select an arbitrary connection ID outside its workspace.

Do not put workspace IDs or access tokens into a client-controlled callback parameter without a signed, one-time server state binding.

## 5. API contract

- GET /api/provider-connections: list only connections for the active workspace; return account label, scopes, state, and timestamps, never token material.
- POST /api/provider-connections/{provider}/oauth/start: create one-time workspace-bound OAuth state.
- GET /api/provider-connections/{provider}/oauth/callback: consume and validate state; never accept caller-supplied workspace ownership.
- POST /api/provider-connections/{connection_id}/verify: verify the connected account and scopes.
- POST /api/provider-connections/{connection_id}/disconnect: revoke/disconnect only a connection owned by the active workspace.
- Publish, analytics collection, and metrics refresh APIs must resolve the workspace connection internally from the parent production job or explicit active workspace. No request may supply a raw token.

## 6. Migration policy

- Existing singleton YouTube/TikTok token rows migrate to a legacy unassigned (workspace_id = NULL) connection only.
- Never infer a customer workspace from a brand name, job name, operator ID, or historical usage.
- Legacy global publishing is available only in the legacy compatibility mode. When tenant provider mode is enabled, workspace-owned jobs without a matching workspace connection fail closed.
- Keep the old singleton rows read-only during a defined rollback window; never duplicate their token into multiple workspaces.
- Migrate refresh leases and OAuth state to connection-scoped keys before enabling multi-workspace provider workers.

## 7. Required acceptance tests

- Workspace A cannot list, verify, publish with, refresh, or disconnect workspace B's connection.
- Missing workspace scope returns only unassigned legacy connection metadata, never tenant credentials.
- OAuth state is one-time, short-lived, provider-bound, workspace-bound, principal-bound, redirect-bound, and PKCE-verified.
- Token ciphertext is authenticated; tampering, wrong key version, missing KMS, or invalid tag fails closed.
- Refresh lease contention is isolated per connection; two workspaces can refresh independently.
- Revocation and key rotation produce immutable audit records without secret material.
- Tenant mode rejects global singleton token fallback.
- Historical NULL connections remain NULL until explicit owner-verified migration.

## 8. Decisions required before implementation/activation

1. Account cardinality: one YouTube/TikTok account per workspace, or multiple channels/accounts per workspace with an explicit active connection selector?
2. Production key management: which KMS/key vault is approved (AWS KMS, Azure Key Vault, GCP KMS, or another managed provider)?
3. OAuth ownership: customer-owned OAuth apps per workspace, or one platform OAuth app with per-customer authorization?
4. Tenant activation: which workspace(s) are authorized for first live provider connection and verification?

No provider credentials, OAuth secrets, KMS keys, callback URLs, or external account connections were changed while preparing this contract.
