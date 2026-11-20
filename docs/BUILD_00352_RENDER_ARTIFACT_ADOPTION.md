# BUILD-00352 — Lease-fenced render artifact adoption

## Scope

The render worker can now be configured with a `RenderArtifactStore`. When
enabled, the renderer must return a `staged_path` inside a private staging
root. The store adopts only a regular, non-symlink `.mp4`, `.m4a`, or
`.aac` file whose size is within the configured byte limit.

## Adoption transaction

1. Resolve the staged path and require it to remain beneath the configured
   staging root. Reject symlinks, unsupported suffixes, empty files and
   oversized files.
2. Calculate SHA-256 and byte size. Require staging and artifact roots to share
   a filesystem so the final move is atomic.
3. Begin an immediate SQLite transaction on the queue database.
4. Re-check worker generation, job ownership, live lease and workspace.
5. Match the output to the immutable EDL snapshot ID and SHA-256 in the claimed
   queue payload.
6. Atomically move the staged file into a generated private storage key.
7. Insert an immutable artifact record, transition the job to
   `review_pending`, clear the lease and append the completion event in the
   same SQLite transaction.

The artifact is not published. The queue transition and artifact metadata are
committed together; a stale worker cannot adopt output after losing its lease.
A process crash between the filesystem rename and SQLite commit can leave an
unindexed private file, so the store provides a grace-period orphan reconciler.
It takes the queue write lock and removes only old, generated artifact filenames
that have no metadata row. Artifact reads are workspace-scoped and re-verify
the stored checksum and size.

## Worker wiring

Pass an initialized store as `artifact_store` to `TimelineRenderWorker`.
With artifact adoption enabled, the renderer callback must return a mapping
containing `staged_path`. Configure `ffprobe_path` on the store to enable bounded
local ffprobe validation; validated duration, dimensions and audio stream count
are persisted with the artifact. Without a configured binary, the worker still
checks path, size, suffix and checksum but does not claim media-stream validity.
Without a store, the existing injected-renderer review handoff remains available
for compatibility.

## Remaining production gates

- Run the concrete EDL renderer with pinned real FFmpeg/ffprobe binaries and
  validate playable real-media outputs on the target worker runtime.
- Pin FFmpeg/ffprobe versions and run them in a production-isolated container
  with CPU, memory, disk, network and process-count limits.
- Run real-media integration and crash/lease-loss tests on the target runtime.
- Add authenticated upload/render/review APIs and retention cleanup.
- CI tests use generated fixture bytes and a mocked ffprobe process. The actual
  ffprobe binary, real FFmpeg rendering and production filesystem isolation
  still require target-runtime validation.

## Concrete EDL renderer increment

`EDLFFmpegRenderer` now builds and runs an argv-only FFmpeg video pipeline.
It resolves every opaque asset ID through a trusted workspace resolver using
the snapshot creator's membership, normalizes clips to a bounded output size,
frame rate and H.264/yuv420p format, and can mix up to eight separately resolved
audio-bed tracks before muxing the final MP4. The worker passes its queue-owned
workspace ID into the renderer and the snapshot creator principal ID is carried
in the internal queue payload. The `create_edl_render_worker` factory wires
the resolver, renderer and lease-fenced artifact store together.

The renderer is deliberately fail-closed. It supports video clips, black
segments for explicit gaps, and title cards when a trusted font is configured.
It rejects overlaps and transitions until their semantics are implemented.
When ffprobe is configured, it validates source duration and mixes available
source audio; separately resolved trusted audio beds can be mixed as well.

The CI renderer tests use a fake subprocess executable and generated fixture
bytes. They prove argv construction, audio-mix/mux orchestration, cancellation
before process launch and worker wiring; they do not prove that a real FFmpeg
binary can decode the supplied media or produce a playable MP4.


## Timeline gaps, title cards and source audio

The EDL renderer now emits explicit black video segments for timeline gaps,
and title clips become centered drawtext cards on a black background. Title
rendering is fail-closed unless the worker is configured with a trusted local
font file via \`title_font_path\`. Text is passed as an escaped FFmpeg filter
value with expansion disabled; it is never interpreted as a filter expression.

When a pinned local ffprobe binary is configured via \`ffprobe_path\`, the
renderer detects the first audio stream on each source asset and adds that
clip's source-trimmed audio at its timeline offset. These tracks are mixed with
any separately resolved trusted audio beds, subject to the combined eight-track
limit. Silent clips are omitted from the source-audio mix. Source audio remains
optional when ffprobe is not configured.

Overlapping clips and transitions remain unsupported and are rejected by the
renderer. Trailing timeline duration cannot be inferred from the current EDL
schema because it has no explicit project-duration field. The tests use fake
FFmpeg/ffprobe processes; a pinned real-media render is still an external
runtime validation gate.


## Authenticated media and render API

The FastAPI application now wires the workspace asset registry, immutable EDL
snapshot store and private render artifact store to the shared application
SQLite database. The following workspace-scoped endpoints are available:

- \`POST /api/workspaces/{workspace_id}/assets\`: accepts a bounded raw request
  body and \`X-File-Name\`; streams it to private storage and returns a quarantined
  asset record. The upload endpoint never marks an asset clean.
- \`GET /api/workspaces/{workspace_id}/assets/{asset_id}\`: returns metadata
  after reviewer permission and active workspace membership checks.
- \`POST /api/timeline/renders\`: accepts the EDL JSON, requires
  \`X-Nexus-Workspace-Id\` and \`Idempotency-Key\`, validates assets and creates
  an immutable snapshot plus durable render queue job.
- \`GET /api/timeline/renders/{snapshot_id}\`: returns workspace-scoped job
  status and, after artifact adoption, verified artifact metadata and preview URL.
- \`GET /api/timeline/artifacts/{artifact_id}/preview\`: streams the verified
  private MP4 inline after reviewer permission and workspace membership checks.

Uploads remain quarantined until a trusted malware-scanning integration records
a clean result. No user-facing endpoint accepts a caller's assertion that a file
is clean. The scanner integration and production worker process must be deployed
separately; the API queues work but does not synchronously render it. Artifact
preview is only available after the lease-fenced worker has adopted the output.


ClamAV scanning is opt-in via \`NEXUS_MEDIA_SCAN_ENABLED=true\`. The Compose API
container has the ClamAV database mounted read-only. Start the updater profile
(\`docker compose --profile media-scan up -d clamav-updater\`) before enabling
scanning. If ClamAV is unavailable, times out, detects a threat, or cannot finish
within its limits, the asset remains pending and cannot be submitted for render.
The scan retry endpoint preserves the asset ID so operators can retry after
scanner infrastructure is repaired.
