# BUILD-00352 EDL FFmpeg renderer

## Supported EDL v1 render subset

The worker accepts ordered non-overlapping video clips, black timeline gaps, bounded text overlays, optional explicit project duration and up to eight optional audio tracks.

- Video clips are ordered by timeline start; gaps (including an initial gap) render as black. An overlap is accepted only when an explicit adjacent `crossfade` transition declares the exact overlap duration; undeclared overlaps remain invalid.
- EDL v1 `transitions[]` is optional for backward compatibility. Each entry has a unique ID, `type: "crossfade"`, adjacent `from_clip_id` / `to_clip_id`, and a whole-millisecond duration from 100 to 5000 ms. Transition durations on either side of a clip may not exceed that clip's available duration.
- Crossfades are rendered by FFmpeg's video `xfade=transition=fade` filter with a deterministic offset derived from the previous clip's timeline end. Clip streams are normalized to the same dimensions, frame rate, pixel format and timebase before composition. Existing audio-bed tracks remain independently positioned on the same project timebase and are mixed/muxed to the exact final project duration; optional audio-track fades remain explicit. This does not yet crossfade embedded source audio between video clips.
- `project_duration_ms` is optional, whole milliseconds, and must cover every clip and audio track. When supplied it controls the final output length, including a trailing black segment; when omitted the last video clip end determines the duration.
- Video source trims are applied with FFmpeg `trim`, then normalized to the configured output canvas, frame rate and pixel format before concat.
- Title clips are rendered as timed `drawtext` overlays. Title content is written to per-job UTF-8 text files and passed with `textfile` plus `expansion=none`; it is never interpolated into an FFmpeg command string. The font must be an absolute, regular, non-symlink file supplied by trusted worker configuration.
- Audio tracks carry an opaque workspace asset ID, timeline start, source in/out, linear gain and optional fade-in/fade-out durations. Audio is trimmed, timestamp-reset, gained, delayed, faded, mixed with `amix` and protected by `alimiter`.
- Video and audio are muxed into a staged MP4. The final output is checked by bounded ffprobe for duration, stream profile and byte-size limits.
- Before FFmpeg runs, the renderer copies each clean asset into a private per-job work directory, verifies its SHA-256, runs a bounded source-media ffprobe check, and enforces source-trim bounds.
- The renderer recomputes the canonical normalized EDL SHA-256 and rejects queue payloads that do not match the immutable snapshot digest.

Subtitles, arbitrary filters, URL inputs and arbitrary file paths remain unsupported. Only the bounded adjacent video crossfade is supported; all other overlap patterns are rejected. Gaps are explicit black video segments, and an explicit project duration can preserve trailing black time.

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
- Earlier integrated code head `6b81e697c3537d81aa5051eb6208f8db2ce2defb`: **914 backend tests passed**; UI browser smoke passed, including authenticated Korean rendering, desktop/mobile, keyboard search, workspace isolation, review approval/audit, analytics pagination/CSV and partial API failure handling.
- EDL black-gap/project-duration and explicit crossfade changes are tracked in Draft PR #470. The exact-head backend and Compose runs must both pass before this increment is considered CI-validated.
- Compose integration smoke passed: current ClamAV database readiness and EICAR rejection, service readiness, render-worker isolation/resource limits, real FFmpeg/ffprobe fixture render and artifact adoption/review, authenticated API upload → separate worker render → approval → private preview, and scheduled encrypted backup plus isolated restore.
- The authenticated E2E uses generated MP4 media and isolated Docker volumes. It proves the Compose integration path, not arbitrary customer-media compatibility, physical-device QA, target-host persistence/quotas, or live YouTube/TikTok provider validation.

## EDL gap and crossfade validation increment

Draft PR #470 adds optional whole-millisecond `project_duration_ms`, black initial/internal/trailing timeline gaps and bounded adjacent video crossfades.

- Crossfades use EDL v1 `transitions[]` entries with unique IDs, exact adjacent clip references and whole-millisecond durations from 100 to 5000 ms.
- A declared transition must exactly match the overlap; undeclared overlaps are still rejected by the timeline renderer. Incoming plus outgoing transition durations cannot exceed the clip's available timeline duration.
- The FFmpeg graph normalizes clip streams and uses `xfade=transition=fade` with a deterministic absolute timeline offset.
- Audio-bed tracks remain positioned on the same timeline and are muxed to the final project duration. Embedded source-audio crossfades are not implemented by this increment.
- The Compose real-media smoke now renders two overlapping clips through the actual FFmpeg worker, lease-fenced artifact adoption and review handoff.

Exact crossfade code head `f336a1c2019c8732d5f0e196d970174f0fa24039` passed Backend [run 44884777926](https://github.com/justinhblee-prog/shorts/actions/runs/44884777926) (**925 tests plus Playwright browser smoke**) and Compose [run 44884777927](https://github.com/justinhblee-prog/shorts/actions/runs/44884777927) (real FFmpeg crossfade render, worker isolation, authenticated API E2E, review/private preview and encrypted backup/isolated restore). This is generated-fixture CI evidence, not representative customer-media or target-host validation.

## Embedded source-audio transition follow-up

Video clips may opt in to embedded source audio with `include_source_audio: true`. The renderer reuses the same hash-verified staged video asset, probes for an audio stream and trims audio to the clip's source in/out points. A request fails closed if the source video has no audio stream.

For each declared video crossfade, the source clip's audio is faded out over the transition duration and the destination clip's audio is faded in over the same duration. Both fades begin at the video crossfade's timeline start, so source audio and picture transition together. Source audio is mixed with any explicit audio-bed tracks using the existing bounded shell-free audio mixer. The combined source-audio plus audio-bed count is limited to eight. Legacy EDL v1 jobs remain unchanged when the optional field is omitted.

This remains a separate Draft follow-up to #470. Exact-head Backend and real-media Compose validation are pending; do not infer source-audio crossfade support from the previously validated video-only crossfade.

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
