# BUILD-00353 — Provider offline contract coverage

**Status:** partial offline validation only; live provider validation remains externally blocked.

## Scope inspected

The repository currently contains two publication/OAuth integrations:

- YouTube OAuth uses Google authorization/token endpoints, encrypted refresh-token storage, required upload/read scopes, and injectable transport/factories for offline tests.
- TikTok Login Kit OAuth uses token/revoke endpoints, encrypted access/refresh token storage, scope enforcement, token rotation, and an injectable transport.
- YouTube publication uses the Google API client with private visibility, prior human approval, immutable artifact snapshot verification, staged media fingerprint verification, and ambiguous-outcome reconciliation.
- TikTok publication uses Content Posting API init/chunk/status endpoints, explicit privacy/AIGC disclosure, creator capability checks, approval/fingerprint verification, host allowlisting and ambiguous-outcome reconciliation.

Existing offline suites already exercise fake transports and service factories in `test_youtube_oauth.py`, `test_tiktok_oauth.py`, `test_youtube_publishing.py`, and `test_tiktok_publishing.py`. They do not constitute verification against the live HTTPS services.

## Contract gaps fixed in this increment

- Both OAuth token adapters now reject valid JSON values that are not an object before accessing provider fields. This avoids leaking an `AttributeError` and prevents malformed provider responses from reaching token persistence.
- TikTok OAuth token expiry fields must be positive JSON integers. Boolean values, zero, negative values and non-integer types are rejected before encrypting or persisting either token.
- New deterministic fake-transport tests cover non-object Google/TikTok token responses and ensure no credentials are persisted; TikTok expiry boundary/type tests cover invalid values.
- These tests do not call the network and do not require credentials.

## Offline test matrix

| Contract | Existing offline coverage | Added coverage |
|---|---|---|
| Google OAuth state, HTTPS redirect, scopes, encrypted refresh token, secret-free status | `test_youtube_oauth.py` | non-object token payload |
| TikTok OAuth state, HTTPS redirect, scopes, encrypted token rotation, refresh lease | `test_tiktok_oauth.py` | non-object payload; expiry type/range |
| YouTube upload private visibility, approval/fingerprint, idempotency and uncertain outcomes | `test_youtube_publishing.py` | existing suite retained |
| TikTok init/chunk/status, privacy/AIGC disclosure, creator limits, URL allowlist, uncertain outcomes | `test_tiktok_publishing.py` | existing suite retained |

## External gates still required

1. Operator-provided YouTube/TikTok OAuth credentials and approved spend ceiling.
2. Provider contract, terms, licensing, content rights and data-processing review.
3. Workspace-scoped provider connections and secret ownership. Current OAuth stores are singleton/global; the workspace connection design remains design-only in `WORKSPACE_PROVIDER_CONNECTION_CONTRACT.md`.
4. Authorized test channels/accounts and explicit private-only test authorization.
5. Actual HTTPS contract verification, real generated script/voice/video provenance, provider latency/cost/failure evidence and human review before any publishing action.

No credentials, account connections, provider scopes, external uploads or public posts were created or changed. No live HTTP requests are part of this PR. BUILD-00353 remains `blocked_external` for its live acceptance criteria.

## Exact-head validation

- Draft PR #475 exact head `eca95fc3da429b7ffd117436af68bf413a7794f1` passed Backend [run 44888635179](https://github.com/justinhblee-prog/shorts/actions/runs/44888635179): 949 tests and Playwright browser smoke.
- Compose [run 44888635188](https://github.com/justinhblee-prog/shorts/actions/runs/44888635188) passed service isolation, ClamAV readiness, real FFmpeg render/adoption/review, authenticated upload/review/private preview and encrypted backup/isolated restore.
- These are offline contract and generated-fixture CI checks only; they do not verify live provider HTTPS endpoints or customer account credentials.


## Nested TikTok publishing response hardening

- TikTok creator-info and video-init responses now require an object-valued `data` member before provider fields are accessed.
- The initialization `publish_id` must be a non-empty string within the existing 64-character bound; arrays and other JSON types are rejected.
- Malformed creator-info data fails before a publish-init request. Malformed initialization data occurs after the remote request boundary and therefore keeps the attempt in `reconciliation_required`; it does not permit an automatic duplicate retry.
- Added fake-transport regression tests for non-object creator data, non-object init data and non-string publish IDs. No live HTTP calls or credentials are used.
- Exact code/test head `ee5e563330d9e4e1956f24b3ba710fc19ebb048f`: Backend [run 44889554706](https://github.com/justinhblee-prog/shorts/actions/runs/44889554706) passed repository validation and Playwright browser smoke; Compose [run 44889554618](https://github.com/justinhblee-prog/shorts/actions/runs/44889554618) passed ClamAV readiness, worker isolation, real FFmpeg render/adoption/review, authenticated API upload-to-worker/private-preview E2E, encrypted backup and isolated restore.
- These results validate offline fake-transport contract tests and generated fixture media only. Live Google/YouTube/TikTok provider compatibility remains blocked by credentials, spend ceiling, legal/provider review and authorized private accounts.


## Latest exact-head validation

The latest provider implementation and tests at `ee5e563330d9e4e1956f24b3ba710fc19ebb048f` passed Backend [run 44889554706](https://github.com/justinhblee-prog/shorts/actions/runs/44889554706) and Compose [run 44889554618](https://github.com/justinhblee-prog/shorts/actions/runs/44889554618). Backend validation and Playwright browser smoke passed; Compose exercised ClamAV readiness, worker isolation, generated-media FFmpeg render/adoption/review, authenticated API E2E, encrypted backup and isolated restore. This follow-up changes only documentation/task-ledger evidence; exact-head reruns are required.


## YouTube upload completion response hardening

- The resumable upload completion response must be an object, and its `id` must be a non-empty string before the local upload is finalized as uploaded.
- A malformed response or invalid video ID after the remote upload request has started leaves the attempt in `reconciliation_required`; automatic retry remains blocked until an operator reconciles the remote outcome.
- Added offline fake-service tests for non-object completion responses and non-string video IDs, asserting that neither is recorded as a confirmed upload.
- Exact code/test head `b4934a69507d120a5cb484234d72c712d5671d3f` passed Backend [run 44890001360](https://github.com/justinhblee-prog/shorts/actions/runs/44890001360): **954 tests**, font fallback and Playwright browser smoke. Compose [run 44890002208](https://github.com/justinhblee-prog/shorts/actions/runs/44890002208) passed ClamAV readiness, worker isolation, real FFmpeg render/adoption/review, authenticated upload-to-worker/private-preview E2E, encrypted backup and isolated restore.
- These tests use fake provider services and generated media. They do not establish live Google/YouTube HTTPS behavior or customer account compatibility.
