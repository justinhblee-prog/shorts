# TikTok AIGC Disclosure Adapter

**Scope:** Content Posting API Direct Post request metadata only.

## Verified platform contract

TikTok's official Direct Post API documents the optional boolean `is_aigc` field. Setting it to `true` causes TikTok to attach an AI-generated label to the post description. The video object also exposes `is_aigc` as the AI-generated-content indicator.

- Direct Post API: https://developers.tiktok.com/docs/en/content-posting-api-reference-direct-post
- Video object: https://developers.tiktok.com/docs/en/tiktok-api-v2-video-object

## Implemented mapping

`backend/tiktok_disclosure.py` maps the production media classification to the API field:

| Production classification | `is_aigc` |
|---|---:|
| `none` | false |
| `ai_assisted_nonrealistic` | false |
| `ai_generated` | true |
| `realistic_alteration` | true |
| `unknown` | Reject |

Unknown or unsupported values fail closed. This helper does not upload or publish anything.

## Implemented private publishing adapter

- `backend/tiktok_publishing.py` implements creator-info query, Direct Post initialization, sequential FILE_UPLOAD transfer, status polling and an immutable publication event log.
- API routes: `POST /api/tiktok/publish/{job_id}`, `GET /api/tiktok/publications/{job_id}`, `POST /api/tiktok/publications/{job_id}/refresh-status`, and `POST /api/tiktok/publications/{job_id}/reconcile`.
- Every publish request requires the current human approval, explicit creator upload consent, caption confirmation, operator ID and explicit paid-partnership/own-brand declarations.
- Until TikTok app audit is completed, the adapter only uses `SELF_ONLY` visibility and disables comments, Duet and Stitch. It checks that `SELF_ONLY` is currently offered by the creator account.
- Chunk transfer follows TikTok's minimum/maximum chunk and trailing-chunk rules. Unknown outcomes are blocked from retry until an operator reconciles them.
- TikTok web OAuth is wired through `/api/tiktok/oauth/authorize`, the state-validated `/api/tiktok/oauth/callback`, and the authenticated `/api/tiktok/oauth/status` endpoint. Access and rotating refresh tokens are encrypted at rest with Fernet; the API publisher obtains refreshed access tokens through the OAuth store.
- Required server environment: `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REDIRECT_URI` (must exactly match the registered HTTPS callback), and `TIKTOK_TOKEN_ENCRYPTION_KEY` (Fernet key). The OAuth flow requests `user.info.basic,video.publish` and rejects a token response that does not grant `video.publish`.
- Generate the encryption key with Python: `from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())`. Store it as a server secret; never commit it or expose it to the browser.
- The current implementation supports one active TikTok creator account per database. Multi-tenant OAuth isolation and token revocation/disconnect are not implemented yet.
- The API requires explicit paid-partnership and own-brand promotion declarations because TikTok's `brand_content_toggle` is a required request field. Both cannot be true at once.
- Uncertain initialization or transfer outcomes enter `reconciliation_required`; the authenticated operator reconciliation endpoint records a confirmed published/not-published outcome before any retry.

## Integration boundary

- The dashboard includes a TikTok account connect/status control and explicit operator confirmation for creator consent and caption confirmation, plus an explicit commercial relationship choice. A dedicated TikTok export screen that renders creator identity, account privacy choices and interaction settings is still pending; do not broaden the UI or enable public posting before that UX is implemented and audited.
- When the Content Posting API client is added, merge the returned mapping into the Direct Post request body and persist the requested disclosure value with the publish audit record.
- Keep the user's explicit review/approval gate. Do not auto-publish publicly until OAuth scopes, creator eligibility, privacy options, moderation, and the full publish-status lifecycle have been verified.
- The API field applies the TikTok label; an operator checkbox in the local UI alone is not a substitute.
- The API's `is_aigc` label is not a blanket approval of rights, consent, accuracy, or policy compliance.

## Validation

The adapter tests cover consent, private-only publishing, AIGC labels, status polling, sponsorship declarations, operator reconciliation, chunk sizing, untrusted upload URLs and retry blocking. Earlier branch CI passed 260 tests on commit b4123f5. The OAuth integration includes state replay/expiry, encrypted-at-rest token, required scope, HTTPS redirect and current/legacy error-schema tests. Current CI run https://github.com/justinhblee-prog/shorts/actions/runs/43691474527 is pending; no real TikTok developer app credentials, approved `video.publish` scope, app audit or live channel upload has been used.
