# TikTok private-only publishing

## Scope and safety defaults

The TikTok publishing adapter supports a human-approved, explicitly consented **SELF_ONLY** Direct Post workflow. It does not provide public-post selection or unattended publishing.

The operator must send `explicit_consent=true` on each publish request. The adapter then verifies:

- The latest human review decision is approved.
- The approved artifact snapshot contains current policy evidence.
- TikTok is one of the selected platforms.
- The AIGC classification is known and the required `is_aigc` acknowledgement exists.
- The media file is inside `NEXUS_MEDIA_DIR`, is a supported video type, and is within the configured file-size limit.
- The creator account currently offers `SELF_ONLY` visibility.

## API routes

All routes require the existing `X-Review-Token`.

- `GET /api/tiktok/creator-info`: query and expose the creator's current privacy and capability options before the export/consent step.
- `POST /api/tiktok/publish/{job_id}`: send the approved video to TikTok using SELF_ONLY only.
- `GET /api/tiktok/publications/{job_id}`: retrieve the local publish record and immutable event history.
- `POST /api/tiktok/publications/{job_id}/refresh-status`: query TikTok's publish status endpoint and append the result.

The publish body contains `media_path`, `title`, `operator_id`, `explicit_consent`, `brand_content_toggle`, and `brand_organic_toggle`. Both commercial-content declarations are required explicitly and are saved in the publication audit. If either is true, the approved policy snapshot must contain commercial-relationship disclosure evidence.

## Remote flow

1. Query creator info and confirm SELF_ONLY is available.
2. Initialize Direct Post with `privacy_level=SELF_ONLY`, the explicit `is_aigc` disclosure, and both commercial-content declarations.
3. Upload the staged media to TikTok's returned HTTPS upload URL using HTTP PUT in byte-range chunks. Do not forward the OAuth bearer token to the signed upload URL.
4. Persist the publish ID, operator consent, AIGC declaration, commercial-content declarations and local audit events.
5. The scheduler automatically polls pending publish IDs in small batches (up to two per scheduler interval, no more often than once per minute per record). Operators can also refresh status manually. Supported statuses include PROCESSING_UPLOAD, PROCESSING_DOWNLOAD, SEND_TO_USER_INBOX, PUBLISH_COMPLETE and FAILED.

A network failure after a remote request begins is marked `reconciliation_required`. The adapter blocks duplicate retries. When a publish ID exists, the scheduler continues status reconciliation with backoff; if no publish ID was returned, an operator must investigate the TikTok creator inbox before any future retry. Poll failures are retained as immutable audit events.

## Credentials and authorization

Preferred setup is the server-side TikTok Login Kit web OAuth flow:

1. Register Login Kit and Content Posting API in the TikTok developer console.
2. Register the exact HTTPS callback URI `TIKTOK_REDIRECT_URI=https://your-domain/api/tiktok/oauth/callback`.
3. Set `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, and a stable `TIKTOK_TOKEN_ENCRYPTION_KEY`. Generate the Fernet key once with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`; keep it secret and back it up.
4. In the portal, select **TikTok 계정 연결**. The server creates a one-time ten-minute OAuth state, stores its hash, and binds it to a Secure, HttpOnly, SameSite=Lax browser cookie. The callback checks both cookie and server-side one-time state before exchanging the code.
5. The server stores access and refresh tokens encrypted with Fernet. Access tokens are refreshed proactively; each successful refresh replaces the rotated refresh token. The scheduler and API share a SQLite refresh lease to prevent concurrent rotation.
6. Required scopes are `user.info.basic` and `video.publish`. TikTok app review and creator authorization are external requirements; the code cannot grant these scopes itself.
7. The portal's disconnect action calls TikTok's revoke endpoint before clearing the encrypted local token record. A static `TIKTOK_ACCESS_TOKEN` fallback must be removed from the runtime separately.

TikTok access tokens are valid for two hours and refresh tokens for 180 days according to the current developer documentation. If the refresh token expires or is revoked, reconnect the account. Never expose client secrets or tokens in the browser or logs.

An optional `TIKTOK_ACCESS_TOKEN` environment variable remains available as a manual fallback, but it does not provide automatic refresh/rotation. The upload follows TikTok's floor-based chunk count: 64 MiB chunks, with the final chunk absorbing the remainder up to TikTok's 128 MiB final-chunk limit.

TikTok may require app review, creator authorization, posting caps, and additional product eligibility. The local code cannot bypass these controls.

## Validation boundary

Unit tests use a deterministic HTTP transport and temporary SQLite database. They verify request shape, privacy, consent, AIGC label, chunk transfer, status tracking, and fail-closed behavior. They do not constitute a live TikTok account upload test.

Official references:
- https://developers.tiktok.com/doc/content-posting-api-reference-direct-post
- https://developers.tiktok.com/doc/content-posting-api-media-transfer-guide
- https://developers.tiktok.com/doc/content-posting-api-reference-get-video-status
- https://developers.tiktok.com/docs/en/oauth-get-a-user-access-token
- https://developers.tiktok.com/docs/en/oauth-refresh-a-user-access-token
- https://developers.tiktok.com/docs/en/oauth-user-access-token-management
- https://developers.tiktok.com/docs/en/oauth-revoke-a-user-access-token
