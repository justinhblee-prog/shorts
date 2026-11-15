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
- The API uses `TIKTOK_ACCESS_TOKEN`; OAuth token issuance/refresh and per-user encrypted token storage are not yet implemented.

## Integration boundary

- This is a backend publishing adapter; the creator-facing export/consent screen is not yet implemented. Do not expose a public-facing auto-publish control until that screen is connected to the explicit consent and caption confirmation fields.
- When the Content Posting API client is added, merge the returned mapping into the Direct Post request body and persist the requested disclosure value with the publish audit record.
- Keep the user's explicit review/approval gate. Do not auto-publish publicly until OAuth scopes, creator eligibility, privacy options, moderation, and the full publish-status lifecycle have been verified.
- The API field applies the TikTok label; an operator checkbox in the local UI alone is not a substitute.
- The API's `is_aigc` label is not a blanket approval of rights, consent, accuracy, or policy compliance.

## Validation

The adapter tests cover consent, private-only publishing, AIGC labels, status polling, sponsorship declarations, operator reconciliation, chunk sizing, untrusted upload URLs and retry blocking. CI must pass before this branch is considered ready to integrate.
