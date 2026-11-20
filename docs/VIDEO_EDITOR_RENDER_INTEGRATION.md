# NEXUS STUDIO PRO — Timeline Render Integration Design

**Status:** Design / implementation boundary (2026-11-20)  
**Scope:** Convert the browser-local edit decision list into a real, reviewable MP4 render without exposing local paths or trusting client-supplied media URLs.

## Current verified boundary

The frontend timeline currently supports local video selection and browser preview, title clips, clip ordering, non-destructive in/out points, selected-range playback, basic title overlay preview, duration summary, and edit-decision-list (EDL) JSON download. Browser-local object URLs and file bytes are not uploaded. The downloaded EDL explicitly declares `rendered: false`. No MP4 is produced by this editor.

The backend already has a provider-agnostic script/voice/render production pipeline, an allowlisted HTTPS artifact stager, ClamAV scanning integration, ffprobe media inspection, and a human review workflow. The existing renderer contract accepts generated audio and video artifact URLs; it does not yet accept a browser EDL with uploaded source assets. Do not treat the existing production render stage as an EDL timeline renderer.

## Target architecture

1. **Upload and register source assets**
   - Authenticated multipart/resumable upload endpoint; require a dedicated `media.upload` permission.
   - Stream to a private temporary file with strict byte limits (default no greater than the existing 256 MiB media cap), bounded request duration, and atomic promotion only after validation.
   - Validate actual file signatures/container using ffprobe; do not trust browser MIME or filename.
   - Malware scan must be enabled and healthy before accepting production media. Fail closed if required scanner configuration is missing or unavailable.
   - Generate server-side opaque asset IDs and SHA-256 fingerprints. Never accept a filesystem path from the browser.
   - Persist owner/workspace scope, retention deadline, media metadata and scan status. Tenant ownership must be checked on every subsequent read/render.

2. **Submit a validated EDL**
   - Versioned schema: `nexus-edit-decision-list`, explicit timebase (milliseconds or rational frame rate), ordered tracks, asset IDs, in/out points, title overlays, audio gain/fades, transitions and output profile.
   - Reject unknown schema versions, duplicate IDs, missing assets, negative or non-finite timestamps, out-points beyond source duration, empty timelines, unsupported codecs/effects, and aggregate duration/asset counts over configured limits.
   - Resolve every asset ID server-side under the authenticated workspace. Never accept remote source URLs or arbitrary local paths in the EDL.
   - Store an immutable render snapshot plus idempotency key; retries must not mutate an already accepted snapshot.

3. **Execute rendering asynchronously**
   - Enqueue a durable render job and use the existing lease/fencing model. Worker validates asset ownership again immediately before execution.
   - Use a pinned FFmpeg build in a restricted worker/container: no network protocols, no arbitrary filter/script input, bounded CPU/memory/runtime/output size, isolated temp directory, and process-tree cancellation.
   - Prefer generated filter graphs from a strict allowlist; never interpolate raw user strings into shell commands. Invoke FFmpeg with argument arrays and `-nostdin`.
   - Keep renderer provider support as an optional adapter. Provider output must be HTTPS and staged through the existing host allowlist, public-IP pinning, size checks, scanner and ffprobe inspection.

4. **Review and publish**
   - Render completion creates a private artifact and transitions to `review_pending`, never directly to publishing.
   - Run media inspection, policy checks, subtitle/speech alignment, dimensions, duration and audio checks before review.
   - Human approval remains mandatory before YouTube/TikTok publishing. Preserve audit events for upload, render, replacement, approval, rejection and cleanup.

5. **Retention and cleanup**
   - Source assets and intermediates have explicit retention policies and per-workspace quotas.
   - Delete only after terminal render state and retention expiry; never delete the only source copy before confirmed output and approval.
   - Keep durable hashes/metadata/audit records after binary cleanup.

## API contract proposal (not implemented)

- `POST /api/media/assets`: authenticated streamed upload; returns opaque `asset_id`, size, hash, probe summary and scan status.
- `GET /api/media/assets/{asset_id}`: owner-scoped metadata only; no public filesystem path.
- `POST /api/timeline/renders`: accepts versioned EDL + idempotency key; returns durable `render_job_id`.
- `GET /api/timeline/renders/{render_job_id}`: stage, progress, warnings, output metadata and review state.
- `DELETE /api/media/assets/{asset_id}`: permitted only when no active render/review/publish dependency references it and retention rules allow deletion.

## Acceptance gates

- Upload: spoofed MIME, malformed container, oversized/chunked body, scanner unavailable, path traversal filename, duplicate hash, symlink and tenant-crossing tests.
- EDL: schema fuzzing, invalid timestamps, overlapping tracks, missing/deleted asset, ownership mismatch, idempotent duplicate submission and immutable snapshot tests.
- Renderer: no network protocol access, shell injection payloads, timeout, cancellation/process-tree cleanup, output-size limit, disk exhaustion, crash/retry and lease-loss tests.
- Output: real FFmpeg integration fixture verifies frame order, trim boundaries, aspect ratio, audio mix, subtitles, title overlays, codec/container and ffprobe metadata.
- Workflow: render is never publishable without media scan, inspection, policy pass and explicit human approval.
- Runtime: dedicated isolated worker with measured CPU/memory/disk quotas and verified artifact retention.

## Current blockers

- No authenticated source-asset upload/registry API with workspace ownership and retention.
- No EDL schema validator or durable render-job model.
- No restricted FFmpeg render worker wired to the timeline editor.
- No tenant isolation contract in the existing local timeline UI.
- Real renderer output and browser-to-backend end-to-end test are not yet available.

Until these gates are implemented and validated, the UI must continue to label its export as an EDL only and must not imply that an MP4 has been rendered.


## Implemented first backend increment — EDL validation only

`backend/timeline_edl.py` now provides a side-effect-free validator for the explicitly supported `nexus-edit-decision-list` v1 subset. It validates the schema/version/timebase, exact field allowlists, unique opaque identifiers, clip-count and one-hour duration limits, finite non-negative timeline/source bounds, source-vs-timeline duration consistency, and bounded non-empty title text. It rejects browser paths, remote URLs, unknown renderer directives and extra fields. Regression coverage is in `backend/tests/test_timeline_edl.py`.

This is deliberately **not** an upload endpoint, asset registry, ownership check, render-job API or renderer. The current API uses a shared `NEXUS_REVIEW_TOKEN` asserted by the caller and does not provide a verified multi-user workspace principal. Consequently, asset ownership and tenant isolation cannot yet be enforced; adding upload/render routes now would create a false security boundary. The validator is ready to be composed into a future authenticated submission service once a real identity/workspace model exists. The current browser EDL export remains `rendered: false`.
