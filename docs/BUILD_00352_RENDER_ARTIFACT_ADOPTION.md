# BUILD-00352 — Lease-fenced render artifact adoption

## Scope

The render worker can now be configured with a `RenderArtifactStore`. When
enabled, the renderer must return a `staged_path` inside a private staging
root. The store adopts only a regular, non-symlink `.mp4`, `.m4a`, or
`.aac` file whose size is within the configured byte limit.

## Atomic snapshot-to-queue submission

The render submission path now creates the immutable EDL snapshot and its
`timeline_render` queue row inside one `BEGIN IMMEDIATE` SQLite transaction.
The queue store accepts a caller-owned connection and never commits that
transaction itself. The idempotency lookup is serialized under the same write
lock, so concurrent retries return the same snapshot and job. If snapshot
insertion fails, the queue row and its enqueue event roll back with it; a worker
cannot claim a job whose snapshot was not committed.

Regression tests inject a snapshot-insert failure and assert that both the
snapshot and queue remain empty, then verify that an idempotent replay returns
the same snapshot/job pair. This behavior was ported from PR #435 into the
selected integrated implementation in PR #436.

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

- Validate representative customer media on the target worker runtime, including unusual codecs, variable frame rates and long-duration inputs.
- Run crash/restart and lease-loss fault injection against the target persistent filesystem.
- Configure production ClamAV database freshness and verify fail-closed scan behavior before enabling uploads.
- Schedule and monitor artifact orphan reconciliation and retention cleanup in the production worker service.
- Run an end-to-end API upload → malware scan → render queue → worker adoption → review preview test with production-like authentication and storage.
- Production load, disk quota, network egress policy and resource measurements remain deployment gates.

Unit tests intentionally use fake FFmpeg/ffprobe processes for fast deterministic validation. The Compose integration workflow separately executes the pinned image binaries against generated real media and validates the resulting MP4 with ffprobe.

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
SQLite database. The following workspace-scoped endpoints are available. Timeline outputs awaiting
review are also included under `timeline_renders` in `GET /api/review/pending`.

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


## Dedicated render worker service

A separate \`timeline-render-worker\` process now consumes only
\`timeline_render\` jobs. It uses the configured local FFmpeg/ffprobe binaries,
workspace-authorized clean assets, and the lease-fenced artifact store. SIGTERM
cancels an active FFmpeg render and returns the job to the retryable queue state
rather than leaving a long-running render active until lease expiry.

Compose applies a read-only container root filesystem, a bounded 512 MiB
\`/tmp\`, dropped Linux capabilities, \`no-new-privileges\`, a 4 GiB memory cap,
2 CPU limit, 128-process limit, and a 90-second shutdown grace period. The
worker shares the existing \`nexus_data\` volume so private source assets,
staging files, adopted artifacts and SQLite state remain inside the current
backup-covered data tree. Source assets are accessed through the hash-verified
read path; the container-level data volume remains writable for SQLite and
render output.

The container image installs a local DejaVu font for deterministic title cards.
The Compose CI smoke now verifies the worker's configured memory, CPU, PID,
read-only-root, capability-drop and no-new-privileges settings, then executes
a real FFmpeg/ffprobe fixture render. Production workload sizing and host-level
resource enforcement still require deployment validation.


Timeline review decisions are stored separately from production-run decisions,
are append-only, and are unique per immutable EDL snapshot. A decision can only
be recorded while the corresponding queue job is \`review_pending\` and a
lease-fenced artifact row exists for the exact snapshot hash. The review record
captures the adopted artifact hash, preventing a later artifact replacement
from changing what was approved.


The Compose smoke workflow now runs \`timeline_render_real_media_smoke.py\`
inside the isolated render-worker image. It generates a short local color+audio
source clip, renders a title card plus timeline gap and video segment with the
real FFmpeg binary, validates the MP4 with ffprobe, checks audio/video streams,
adopts the artifact under a live worker lease, and records a reviewer decision
bound to the final artifact checksum. The workflow result is the validation
gate; a source-level test or fake subprocess is not treated as equivalent.


Latest verified Compose run #44754249046 on commit
da945b470093323671da92a6b3fba39f476bfc44 passed the worker security-limit
assertions, generated-fixture real FFmpeg render, ffprobe stream validation,
lease-fenced artifact adoption, pending review, artifact-hash-bound approval
and encrypted backup/restore checks. The CPU limit assertion accepts Docker's
supported CpuQuota or NanoCpus representation; it does not weaken the required
two-CPU cap. This proves the pinned image toolchain works on the CI fixture,
not that all customer media or production hosts are compatible.


## FFmpeg/ffprobe binary pinning

The container image now writes SHA-256 digests for its installed
\`/usr/bin/ffmpeg\` and \`/usr/bin/ffprobe\` binaries to
\`/usr/share/nexus-media-binaries.sha256\` during image build. The dedicated
render worker verifies both exact configured paths and hashes before registering
its worker generation or claiming jobs. A missing, malformed, unlisted, symlinked
or modified binary fails startup closed. Production deployments should also pin
the built container image by immutable digest so the image-baked manifest itself
cannot change unnoticed during rollout.


The same Compose run built the image and started the worker only after its
image-baked FFmpeg/ffprobe checksum manifest was verified. It then passed the
render/review and encrypted backup/restore smoke. The independent backend,
Playwright Chromium browser smoke and Korean font fallback checks also passed
in backend run #44754249154.


## Authenticated Compose API-to-worker E2E

The Compose smoke now provisions ephemeral, least-lived CI-only reviewer
credentials and enables SQLite workspace membership. It creates two separate
workspaces through authenticated HTTP requests, uploads a generated MP4 through
the private asset API, confirms the upload remains quarantined, and verifies
that a different principal cannot upload into that workspace. The harness then
records a trusted clean attestation for that generated fixture only; this step
does not exercise or claim ClamAV scanning.

The render is submitted through the authenticated API with an idempotency key.
The smoke verifies replay returns the same snapshot/job, then waits for the
separate Compose `timeline-render-worker` service to claim the job, render the
MP4 with the pinned FFmpeg/ffprobe binaries, and adopt the artifact. It checks
workspace isolation and unauthenticated denial, records an artifact-bound
review decision through the API, creates a short-lived preview session, and
downloads the private MP4 using the scoped cookie. This covers the real
container-to-container API/worker handoff, rather than only calling stores
directly inside a test process.

The CI test credentials and fixture workspace are ephemeral and are not
production credentials. ClamAV signature freshness, actual malware scanning,
representative customer media, and target-host compatibility remain separate
production gates. The authenticated API-to-worker E2E passed in Compose run #44798390154 and backend run #44798390156 on commit `e9f1c124dc545a348dd40c3bd08ae559927878a8`. That earlier run used an explicit trusted test-fixture scan attestation. The subsequent ClamAV-backed revision is being verified separately; its current workflow must pass before claiming real ClamAV integration.


### Latest authenticated E2E verification

- Compose run #44798390154: successful on commit
  `e9f1c124dc545a348dd40c3bd08ae559927878a8`. All steps passed, including
  authenticated API-to-worker E2E and encrypted backup/restore.
- Backend run #44798390156: successful on the same commit, including
  `scripts/validate.sh`, Korean font fallback and Playwright Chromium smoke.
- The E2E uses two ephemeral admin principals and two isolated SQLite
  workspaces. It verifies denied cross-workspace upload, denied cross-workspace
  render status, unauthenticated status denial, upload quarantine, idempotent
  submission, actual render by the separate Compose worker, artifact-bound
  approval, and cookie-authenticated private MP4 preview.
- The new ClamAV-backed revision no longer writes a clean attestation directly.
  It starts freshclam, verifies a usable signature database, scans the generated
  MP4 through the API, and checks EICAR rejection. Its CI result is pending.
  Production signature freshness monitoring and operations remain separate.
