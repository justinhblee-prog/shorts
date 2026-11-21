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
- Upload streams reserve workspace quota incrementally before each chunk is written to private staging; concurrent in-flight uploads therefore count against the same serialized quota, not only after staging completes. Reservations are renewed while chunks arrive and expire fail-closed.
- `TimelineRenderWorker` passes workspace and immutable snapshot-owner context, cancels active FFmpeg work on lease loss or graceful shutdown, and discards unadopted staged output.
- `RenderArtifactStore` rechecks the live lease, worker generation and snapshot binding before adopting output and handing it to the review queue. This is not publishing.
- The authenticated operator API supports bounded private uploads, quarantine/rescan, render submission/status, pending artifact listing, download and review decisions.
- ClamAV and ffprobe failures leave media quarantined. `NEXUS_MEDIA_SCAN_ENABLED` must be enabled and trusted ClamAV signatures available before uploads can become renderable; the default is fail-closed/pending.
- The Compose render worker is isolated with no network, read-only root filesystem, dropped Linux capabilities, no-new-privileges, bounded tmpfs, CPU/memory/PID limits and graceful shutdown.
- The repository contains a reviewed `backend/media-binaries.sha256` lockfile for `/usr/bin/ffmpeg` and `/usr/bin/ffprobe`. The image pins Debian FFmpeg package `7:7.1.5-0+deb13u1`, copies the reviewed lockfile and verifies both digests with `sha256sum --check` during image build.
- Worker construction repeats exact configured-path verification against the same immutable image manifest before opening the render queue or registering a worker generation; a missing, unsafe or mismatched manifest fails startup closed.
- Update the package version and both reviewed digests together only after inspecting the new binary provenance and confirming the Compose render smoke; never regenerate the manifest from the just-installed binaries.

## Validation evidence

GitHub Actions on the integrated Draft PR:
- 910 backend tests passed.
- UI browser smoke passed, including desktop/mobile, keyboard navigation and authenticated API checks.
- Real FFmpeg/ffprobe smoke generated a two-second MP4 with a title overlay and audio track, validated the output, adopted the artifact under the live worker lease, exposed it for review and recorded an approval bound to the artifact hash.
- Compose smoke verified worker isolation/resource limits and encrypted backup/restore.

The smoke uses generated fixture media. It does not establish production compatibility across arbitrary user media or prove a malware-signature update on the deployment host.

## Workspace upload capacity controls

- Each workspace has a durable private-media byte quota configured by `NEXUS_MAX_WORKSPACE_ASSET_BYTES` (default: 2 GiB); the per-file limit remains independently controlled by `NEXUS_MAX_ASSET_BYTES`.
- Each upload reserves its first chunk before writing it to disk, then extends its reservation per chunk under a short SQLite `BEGIN IMMEDIATE` transaction. Active asset bytes and all unexpired reservations are counted together before each chunk is staged.
- Reservations are refreshed while chunks arrive and released in the same transaction that registers the asset, or on failure; an expired reservation causes the upload to fail closed, and abandoned reservations expire after ten minutes.
- Quota rejection occurs before the rejected chunk is written to the staging file and before the completed file is adopted into the workspace asset directory. The in-memory chunk buffer remains bounded to 1 MiB per read.
- Host filesystem quotas and total disk limits for render staging/artifacts are still required operational controls; this workspace quota does not replace them.

## Remaining production gates

- Maintain reviewed FFmpeg/ffprobe package versions and checksum lockfile updates as an explicit supply-chain review gate; the current lockfile pins Debian FFmpeg `7:7.1.5-0+deb13u1`.
- Validate ClamAV signature provisioning and a real clean/infected upload scan in the target environment.
- Configure host-level disk quotas and retention limits for private assets, staging and adopted artifacts.
- Validate on the actual target host and representative customer media before production use.
- No provider API, upload to social platforms, public publishing or production deployment is included.
