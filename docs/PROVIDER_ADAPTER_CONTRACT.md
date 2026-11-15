# AI provider adapter contract

This contract is the integration boundary between the production pipeline and a vendor's script, text-to-speech (TTS), or video-rendering API. The core pipeline currently uses `JsonProvider` (JSON POST with an optional Bearer token). A vendor that does not implement this contract needs a small vendor-specific adapter; do not point the generic adapter at an unrelated vendor endpoint and assume compatibility.

## Integration status

- Script, voice and render stages are implemented in the orchestrator.
- Generic JSON transport and mocked contract tests are implemented.
- No vendor has been selected or authenticated in this repository.
- No live provider request, paid generation, billing check, or real media generation is verified.
- Provider credentials must be supplied by the operator as runtime secrets. Never commit them or paste them into source code.

## Runtime configuration

| Stage | URL | Bearer token |
|---|---|---|
| Script | `SCRIPT_PROVIDER_URL` | `SCRIPT_PROVIDER_TOKEN` |
| Voice/TTS | `VOICE_PROVIDER_URL` | `VOICE_PROVIDER_TOKEN` |
| Render | `RENDER_PROVIDER_URL` | `RENDER_PROVIDER_TOKEN` |

Remote URLs must use HTTPS. Loopback HTTP is permitted only for local development. The protected `GET /api/preflight` endpoint checks URL shape and credential presence only; it does not contact vendors.

## Request and response contracts

All requests are UTF-8 JSON POST bodies. Successful responses must be JSON objects and use a 2xx status.

### 1. Script generation

Request fields currently sent by the orchestrator:

- `task`: `create_short_video_script`
- `brand`, `region`, `language`, `topic`
- `format`: `vertical_short`
- `require_fact_check`: boolean
- `brand_profile`, `editorial_constraints`
- `trend_context` and `policy_preflight`
- `platform_compliance_instructions`, `trend_context_handling`

Minimum response:

```json
{
  "script": "Narration and scene-ready script text",
  "provider": "vendor/model identifier",
  "source_urls": ["https://source.example/article"],
  "factual_claims_verified": false,
  "fact_check_notes": "Claims requiring reviewer attention"
}
```

Only `script` is mandatory for pipeline progression. The remaining fields are quality/review metadata, not proof that claims were independently verified. Do not return fabricated source URLs or attestations.

### 2. Voice generation

Request fields: `script`, `language`, `brand`, `format=narration`, `voice_tone`, and `target_audience`.

Minimum response:

```json
{
  "audio_url": "https://artifact.example/audio.mp3",
  "provider": "vendor/model identifier",
  "duration_seconds": 42.5,
  "codec": "mp3",
  "voice_profile": "configured voice identifier"
}
```

`audio_url` must identify a real retrievable audio artifact. The current pipeline records the URL and metadata; the render vendor must be able to access it, or a future authenticated audio-staging adapter must be added. A successful HTTP response is not proof that the audio plays correctly.

### 3. Video rendering

Request fields: `script`, `audio_url`, `brand`, `region`, `language`, `aspect_ratio=9:16`, `subtitles=true`, and `brand_profile`.

Minimum response:

```json
{
  "video_url": "https://allowlisted-cdn.example/video.mp4",
  "provider": "vendor/model identifier",
  "duration_seconds": 42.5,
  "width": 1080,
  "height": 1920,
  "aspect_ratio": "9:16",
  "subtitles": true
}
```

`video_url` must point to the completed artifact, not a transient job-status page. The hostname must be included in `RENDER_ARTIFACT_HOSTS`. The staging endpoint downloads only allowlisted HTTPS artifacts, rejects redirects and non-public DNS destinations, applies the byte limit, checks the MP4 signature, then invokes ffprobe to verify video/audio streams, vertical dimensions and duration before upload.

## Error, timeout and idempotency behavior

- Current generic transport timeout is 90 seconds. Vendors that render asynchronously must be wrapped with an adapter that polls a vendor job to completion within the configured contract; returning a job ID as `video_url` is invalid.
- HTTP 429 is classified as retryable. Other HTTP failures, connection failures, timeouts and malformed responses are currently fail-closed/non-retryable to avoid duplicate paid generation after an ambiguous provider outcome.
- Provider error response bodies are deliberately discarded. Return actionable, non-sensitive diagnostics through your adapter's own safe error mapping; never include tokens, prompts or user content in exception messages.
- Do not add blind retries around a paid POST. Before enabling retry, confirm vendor-side idempotency support and persist a stable request key for each production job and stage.
- Provider calls are sequential: script → voice → render. A later stage must not be called if an earlier stage fails or the worker loses its fenced lease.

## Vendor adapter acceptance checklist

1. Confirm the vendor's API terms, region availability, content/license rights, retention policy, and commercial-use permissions.
2. Record model/voice identifiers, per-unit pricing, concurrency limits, rate limits, quotas, and cancellation/refund behavior.
3. Implement an adapter that maps the vendor's authentication, request schema, async polling, and response schema to this contract.
4. Keep API keys in runtime secret storage; use a dedicated least-privilege key per stage where supported.
5. Test successful output, malformed response, 429, 5xx, timeout, connection loss, expired URL, oversized artifact, redirect, DNS rebinding/private IP and missing media streams.
6. Run one operator-authorized low-cost live generation, inspect the actual audio/video, and record cost and latency before enabling routine schedules.

## Deliberately not automated yet

Vendor selection, account creation, payment authorization, secret provisioning, live API calls, model/voice choice, and acceptance of vendor terms require the operator. The repository must not guess a vendor or initiate paid requests without explicit authorization.
