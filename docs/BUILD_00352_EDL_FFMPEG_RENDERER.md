# BUILD-00352 EDL FFmpeg renderer

## Supported EDL v1 render subset

The worker renders ordered video clips, bounded timed title overlays, and up to eight independent audio tracks.

- Video starts at timeline zero. Adjacent clips may use a hard cut, a declared crossfade, or a declared internal black interval.
- Crossfades are whole-millisecond durations from 100–5000 ms, reference the exact adjacent clips, and must be shorter than both source segments. FFmpeg uses the bounded `xfade=transition=fade` graph for declared overlaps; undeclared or mismatched overlaps are rejected.
- Internal black intervals are whole-millisecond durations from 100–10000 ms and reference adjacent clips. The renderer inserts a generated black color segment into the graph. A join cannot declare both a crossfade and a black interval.
- An optional `project_duration_ms` may extend the project beyond the video sequence. The renderer pads the video tail with black frames; title overlays and audio may continue within the declared duration. Legacy snapshots that omit this field retain their previous normalized digest shape.
- Video source trims are applied with FFmpeg `trim`, then normalized to the configured output canvas, frame rate and pixel format before concat/xfade composition.
- Title clips are rendered as timed `drawtext` overlays. Title content is written to per-job UTF-8 text files and passed with `textfile` plus `expansion=none`; it is never interpolated into an FFmpeg command string. The font must be an absolute, regular, non-symlink file supplied by trusted worker configuration.
- Audio tracks carry an opaque workspace asset ID, timeline start, source in/out, linear gain and optional fade-in/fade-out durations. Audio is trimmed, timestamp-reset, gained, delayed, faded, mixed with `amix` and protected by `alimiter`.
- Video and audio are muxed into a staged MP4. The final output is checked by bounded ffprobe for duration, stream profile and byte-size limits.
- Before FFmpeg runs, the renderer copies each clean asset into a private per-job work directory, verifies its SHA-256, runs a bounded source-media ffprobe check, and enforces source-trim bounds.
- The renderer recomputes the canonical normalized EDL SHA-256 and rejects queue payloads that do not match the immutable snapshot digest.

Subtitles, arbitrary filters, URL inputs, arbitrary file paths and undeclared timeline intervals remain unsupported. The API validator and renderer both enforce the same transition/gap timing contract; malformed or ambiguous joins fail closed.

## Worker and API integration

- `workspace_asset_resolver(asset_store)` requires clean workspace assets and returns a trusted SHA-256.
- `TimelineRenderWorker` passes workspace and immutable snapshot-owner context, cancels active FFmpeg work on lease loss or graceful shutdown, and discards unadopted staged output.
- `RenderArtifactStore` rechecks the live lease, worker generation and snapshot binding before adopting output and handing it to the review queue. This is not publishing.
- The authenticated operator API supports bounded private uploads, quarantine/rescan, render submission/status, pending artifact listing, download and review decisions.
- ClamAV and ffprobe failures leave media quarantined. `NEXUS_MEDIA_SCAN_ENABLED` must be enabled and trusted ClamAV signatures available before uploads can become renderable; the default is fail-closed/pending.
- The Compose render worker is isolated with no network, read-only root filesystem, dropped Linux capabilities, no-new-privileges, bounded tmpfs, CPU/memory/PID limits and graceful shutdown.
- The private artifact volume has a shared physical-storage quota configured by `NEXUS_RENDER_MAX_STORAGE_BYTES` (default 20,000,000,000 bytes, bounded to 1–1,000,000,000,000). Every adoption checks the quota while holding the queue write lock and counts all regular files in the artifact root, including unindexed crash leftovers and operator-retained files; quota exhaustion rejects the new artifact without moving it out of staging. `storage_usage()` exposes file count, used bytes and remaining bytes for operator telemetry.
- The worker periodically reconciles crash-left staging outputs and unindexed generated artifact files. The interval is `NEXUS_RENDER_RECONCILE_INTERVAL_SECONDS` (default 300 seconds, bounded to 60–86400); each sweep uses a two-hour grace period and logs removed counts and bytes. Cleanup errors are logged and retried at the next interval without taking the worker offline.
- Reconciliation never deletes indexed review artifacts. Indexed-artifact retention, user deletion, quotas and backup-retention interaction require an explicit operator policy.

## Validation evidence

- Exact PR #493 worker checkpoint `3eeb1d9ae66f385ee3f3398135a93dfceb5242a3`: backend/browser/responsive validation passed in [run #44916373730](https://github.com/justinhblee-prog/shorts/actions/runs/44916373730); Compose real FFmpeg/ffprobe render, ClamAV scan, authenticated upload-to-worker render, private review preview/approval and encrypted backup/restore passed in [run #44916373618](https://github.com/justinhblee-prog/shorts/actions/runs/44916373618).
- The exact current UI head `15487609dfd4c429ba978480f37b8934b0b2d937` passed backend validation, authenticated timeline editor/EDL API-contract Playwright smoke and responsive workbench smoke in [run #44923689502](https://github.com/justinhblee-prog/shorts/actions/runs/44923689502). This run also checks deferred thumbnail loading, detached-media cleanup and the no-IntersectionObserver fallback.
- Compose smoke uses generated fixture media and isolated volumes. It proves the exercised FFmpeg/ffprobe and worker integration path, not compatibility with every customer codec, target-host filesystem behavior or production malware-signature freshness.

## Remaining validation and operator gates

- Validate representative customer media on the target runtime, including uncommon codecs, variable frame rates and long-duration inputs.
- Verify ClamAV signature provisioning and a real clean/infected upload scan on the target host before enabling production uploads.
- Exercise lease-loss/crash recovery and artifact reconciliation against the target persistent filesystem.
- Measure production workload resource usage and enforce host-level disk quotas, network-egress policy and retention limits for private assets, staging and adopted artifacts.
- Independently review/pin FFmpeg and ffprobe versions and binary integrity policy; the current image manifest is generated from the installed binaries and is not an independent supply-chain attestation.
- Validate the actual target host and persistent storage before production use. These gates do not prevent continued implementation or isolated CI validation.

No provider API, social-platform upload, public publishing or production deployment is included.

## Frontend integration — BUILD-00361

The browser timeline submits the supported EDL v1 subset through the authenticated operator API. Video clips and audio tracks are uploaded to the active workspace and must receive a clean ClamAV/ffprobe attestation before render. The UI builds ordered video clips, explicit crossfade or black-gap joins, optional project duration, timed title overlays and up to eight audio tracks. It submits an idempotent immutable snapshot, polls worker-owned render status, fetches the integrity-checked private review artifact, and records an artifact-bound human decision. This is not a public publishing flow. The client does not expose arbitrary URLs, paths or filters.

## UI media shelf and visual timeline — BUILD-00362

The frontend adds a searchable local media shelf and a graphical timeline over the existing editor state. Shelf cards show local video/title previews and metadata; selection updates the source preview and clip inspector. The visual timeline displays the time ruler, video sequence and crossfade/black-gap markers, timed title overlays, and up to eight independent audio lanes. Thumbnail loading is deferred with a shelf-rooted IntersectionObserver and bounded prefetch; browsers without IntersectionObserver use an eager compatibility fallback. Rerender cleanup pauses detached videos and releases their media sources. Browser smoke covers the observer path, fallback, cleanup, API contract and responsive layout.

Remaining UI validation is limited to representative customer codecs/file sizes and performance with larger media libraries and long timelines on target browsers.
