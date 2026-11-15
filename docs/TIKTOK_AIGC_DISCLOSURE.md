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

## Integration boundary

- The TikTok publishing client is not yet implemented in this repository.
- When the Content Posting API client is added, merge the returned mapping into the Direct Post request body and persist the requested disclosure value with the publish audit record.
- Keep the user's explicit review/approval gate. Do not auto-publish publicly until OAuth scopes, creator eligibility, privacy options, moderation, and the full publish-status lifecycle have been verified.
- The API field applies the TikTok label; an operator checkbox in the local UI alone is not a substitute.
- The API's `is_aigc` label is not a blanket approval of rights, consent, accuracy, or policy compliance.

## Validation

The unit tests cover all supported classification values and reject unknown classifications. CI must pass before this branch is considered ready to integrate.
