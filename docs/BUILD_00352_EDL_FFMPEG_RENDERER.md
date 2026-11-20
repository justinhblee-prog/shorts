# BUILD-00352 EDL FFmpeg renderer

## Supported EDL v1 render subset

The worker renderer accepts sequential video clips and up to eight optional audio tracks.

- Video clips must begin at timeline zero and be contiguous, without gaps or overlaps.
- Video source trims are applied with FFmpeg `trim`, then normalized to the configured output canvas, frame rate and pixel format before concat. Before processing, the renderer recomputes the canonical normalized EDL SHA-256 and rejects a queue payload that does not match the immutable snapshot digest.
- Audio tracks carry an opaque workspace asset ID, timeline start, source in/out, linear gain and optional fade-in/fade-out durations.
- Audio is trimmed, timestamp-reset, gained, delayed to its timeline position, faded, mixed with `amix` and protected by `alimiter`.
- The video-only and audio-mix outputs are muxed into a staged MP4. Video is stream-copied during the final mux.
- A bounded ffprobe pass validates the final output duration, video stream, optional audio stream and byte-size ceiling.

Title clips, transitions, arbitrary filters, URL inputs and arbitrary file paths are rejected by the renderer. The EDL validator may preserve title clips for other consumers, but this renderer refuses to claim they were rendered.

## Worker integration

Construct `TimelineFFmpegRenderer` with:
- a private staging root,
- a trusted resolver callback accepting `(workspace_id, principal_id, asset_id)`,
- absolute configured FFmpeg and ffprobe binary paths,
- bounded dimensions, frame rate, output bytes and execution timeout.

`workspace_asset_resolver(asset_store)` supplies a resolver that requires clean workspace assets and returns their trusted SHA-256. The renderer copies each resolved asset into a per-job private work directory and verifies the copied bytes against the trusted digest before passing paths to FFmpeg.

Pass the renderer to `TimelineRenderWorker` and pass a `RenderArtifactStore` as `artifact_store`. The optional `backend/timeline_render_worker_service.py` entrypoint builds these dependencies from environment variables and is available through the Compose `render` profile. It claims only `timeline_render` jobs and has a separate stable worker identity. The worker supplies workspace and creator identity to renderers that accept that context. It passes its lease-loss and graceful-shutdown events into the renderer; FFmpeg processes are run without a shell, with bounded runtime and cancellation.

On success the renderer returns a staged MP4 path. The artifact store rechecks the live lease, generation and EDL snapshot binding before atomically adopting it into private artifact storage and moving the queue row to `review_pending`. This is not publishing.

## Important production gates

- CI uses fixture media and a fake process runner; it does not prove a real FFmpeg encode or validate codec availability.
- The target host must pin and configure trusted FFmpeg/ffprobe binaries and validate their checksums.
- The worker must run in an isolated container with CPU, memory, disk, process-count and network restrictions.
- A real malware scanner and trusted input-media probe must populate clean status and actual source duration metadata.
- Title overlays, transitions, subtitles and richer timeline compositing need explicit schema and rendering semantics before implementation.
- The renderer currently requires contiguous video clips. Timeline gaps/overlaps need an explicit black-frame/overlay policy.
- The optional worker service is implemented but not enabled by default. Authenticated API upload/render submission routes and production worker orchestration are not yet wired.
- No real-media, production isolation or publishing success is claimed.
