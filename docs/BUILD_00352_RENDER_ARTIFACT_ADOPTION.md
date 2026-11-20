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

- A concrete EDL renderer must produce the staged MP4 and call the safe audio
  mix builder with trusted, staged inputs.
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

This renderer is deliberately fail-closed and currently supports only
contiguous, non-overlapping video clips beginning at timeline zero. It rejects
title clips, gaps and overlaps rather than silently producing incorrect timing.
Source-clip audio is currently omitted; audio is supplied only through the
trusted audio-track resolver. Those EDL features need explicit semantics and
separate implementation.

The CI renderer tests use a fake subprocess executable and generated fixture
bytes. They prove argv construction, audio-mix/mux orchestration, cancellation
before process launch and worker wiring; they do not prove that a real FFmpeg
binary can decode the supplied media or produce a playable MP4.
