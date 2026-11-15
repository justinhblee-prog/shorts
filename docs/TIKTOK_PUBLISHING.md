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
5. Poll the status endpoint through the explicit refresh route. Supported statuses include PROCESSING_UPLOAD, PROCESSING_DOWNLOAD, SEND_TO_USER_INBOX, PUBLISH_COMPLETE and FAILED.

A network failure after a remote request begins is marked `reconciliation_required`. The adapter blocks duplicate retries. An operator must investigate the TikTok creator inbox/status before any future retry.

## Credentials and authorization

Set `TIKTOK_ACCESS_TOKEN` in the backend runtime. The access token must belong to an authorized creator and include the `video.publish` and creator-info query scopes required by TikTok. This repository does not perform OAuth authorization-code exchange or refresh-token rotation for TikTok yet. The upload follows TikTok's floor-based chunk count: 64 MiB chunks, with the final chunk absorbing the remainder up to TikTok's 128 MiB final-chunk limit.

TikTok may require app review, creator authorization, posting caps, and additional product eligibility. The local code cannot bypass these controls.

## Validation boundary

Unit tests use a deterministic HTTP transport and temporary SQLite database. They verify request shape, privacy, consent, AIGC label, chunk transfer, status tracking, and fail-closed behavior. They do not constitute a live TikTok account upload test.

Official references:
- https://developers.tiktok.com/doc/content-posting-api-reference-direct-post
- https://developers.tiktok.com/doc/content-posting-api-media-transfer-guide
- https://developers.tiktok.com/doc/content-posting-api-reference-get-video-status
