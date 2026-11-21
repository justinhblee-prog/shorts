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
