# BUILD-00352 EDL FFmpeg renderer

## Supported EDL v1 render subset

The worker accepts sequential video clips, bounded text overlays and up to eight optional audio tracks.

- Video clips must begin at timeline zero and be contiguous, without gaps or overlaps.
- Video source trims are applied with FFmpeg `trim`, then normalized to the configured output canvas, frame rate and pixel format before concat.
- Title clips are rendered as timed `drawtext` overlays. Title content is written to per-job UTF-8 text files and passed with `textfile` plus `expansion=none`; it is never interpolated into an FFmpeg command string. The font must be an absolute, regular, non-symlink file supplied by trusted worker configuration.
- Audio tracks carry an opaque workspace asset ID, timeline start, source in/out, linear gain and optional fade-in/fade-out durations. Audio is trimmed, timestamp-reset, gained, delayed, faded, mixed with `amix` and protected by `alimiter`.
- Video and audio are muxed into a staged MP4. The final output is checked by bounded ffprobe for duration, stream profile and byte-size limits.
- Before FFmpeg runs, the renderer copies each clean asset into a private per-job work directory, verifies its SHA-256, runs a bounded source-media ffprobe check, and enforces source-trim bounds.
- The renderer recomputes the canonical normalized EDL SHA-256 and rejects queue payloads that do not match the immutable snapshot digest.

Transitions, subtitles, arbitrary filters, URL inputs, arbitrary file paths, timeline gaps and overlaps remain unsupported. Video clips must be contiguous; gaps and overlaps are rejected rather than silently rendered.

## Worker and API integration

- `workspace_asset_resolver(asset_store)` requires clean workspace assets and returns a trusted SHA-256.
- `TimelineRenderWorker` passes workspace and immutable snapshot-owner context, cancels active FFmpeg work on lease loss or graceful shutdown, and discards unadopted staged output.
- `RenderArtifactStore` rechecks the live lease, worker generation and snapshot binding before adopting output and handing it to the review queue. This is not publishing.
- The authenticated operator API supports bounded private uploads, quarantine/rescan, render submission/status, pending artifact listing, download and review decisions.
- ClamAV and ffprobe failures leave media quarantined. `NEXUS_MEDIA_SCAN_ENABLED` must be enabled and trusted ClamAV signatures available before uploads can become renderable; the default is fail-closed/pending.
- The Compose render worker is isolated with no network, read-only root filesystem, dropped Linux capabilities, no-new-privileges, bounded tmpfs, CPU/memory/PID limits and graceful shutdown.
- The render worker periodically reconciles crash-left staging outputs and unindexed adopted-artifact files every five minutes with a two-hour grace period. The current follow-up adds structured removal counts and failure-type logs; this is orphan cleanup only, not indexed artifact retention/deletion or a hard disk quota.

## Validation evidence

GitHub Actions on the integrated Draft PR #467:
- Exact code head `6b81e697c3537d81aa5051eb6208f8db2ce2defb): **914 backend tests passed**; UI browser smoke passed, including authenticated Korean rendering, desktop/mobile, keyboard search, workspace isolation, review approval/audit, analytics pagination/CSV and partial API failure handling.
- Compose integration smoke passed: current ClamAV database readiness and EICAR rejection, service readiness, render-worker isolation/resource limits, real FFmpeg/ffprobe fixture render and artifact adoption/review, authenticated API upload → separate worker render → approval → private preview, and scheduled encrypted backup plus isolated restore.
- The authenticated E2E uses generated MP4 media and isolated Docker volumes. It proves the Compose integration path, not arbitrary customer-media compatibility, physical-device QA, target-host persistence/quotas, or live YouTube/TikTok provider validation.

## Render artifact storage guard

- `NEXUS_RENDER_ARTIFACT_MAX_BYTES` defaults to 20 GiB and caps the installation-wide sum of indexed adopted render artifacts. The aggregate is checked inside the SQLite write transaction immediately before adoption, preventing concurrent workers from exceeding the logical indexed-artifact cap.
- `NEXUS_RENDER_ARTIFACT_MIN_FREE_BYTES` defaults to 1 GiB. Adoption fails closed if the artifact filesystem has less free space than the configured reserve or free space cannot be inspected; `0` disables only this preflight.
- This is not a physical filesystem quota or block reservation. The logical cap excludes temporary staging and unindexed orphan files. Host/container quotas and monitoring remain necessary.
- When capacity is exhausted, the staged output is not adopted and the worker's normal failure path discards it. Existing indexed artifacts are preserved; no automatic deletion is performed.
- The worker's five-minute orphan reconciliation and two-hour grace period remove only crash-left staging and unindexed generated files. Indexed artifact retention/deletion is a separate policy and remains open.

## Remaining production gates

- Pin FFmpeg/ffprobe to reviewed versions and verify against an independently maintained checksum manifest; the image currently generates its manifest from the installed binaries.
- Validate ClamAV signature provisioning and a real clean/infected upload scan in the target environment.
- Configure host-level disk quotas and retention limits for private assets, staging and adopted artifacts.
- Validate on the actual target host and representative customer media before production use.
- No provider API, upload to social platforms, public publishing or production deployment is included.


## Concurrent artifact capacity race validation

- Added a two-worker/two-workspace concurrent adoption regression. With the installation cap set to exactly one output, both workers start adoption together; SQLite write-lock serialization allows one adoption and rejects the other without losing its staged output.
- Exact-head commit `2e5eede30bc2712e72b33c5ba988928be3ccaa30`: Backend [44908311824](https://github.com/justinhblee-prog/shorts/actions/runs/44908311824), **921 tests passed** plus authenticated Playwright smoke; Compose [44908311922](https://github.com/justinhblee-prog/shorts/actions/runs/44908311922) passed real FFmpeg render/adoption/review, authenticated API-to-worker private preview, ClamAV, encrypted backup/restore and teardown.
- This proves the race guard on isolated CI SQLite/filesystem volumes; target-host persistent storage and production quota/monitoring remain unverified.
