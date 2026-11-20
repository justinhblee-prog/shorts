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

## Concrete EDL renderer

`TimelineFFmpegRenderer` implements the EDL v1 video/title/audio path.
It resolves only clean workspace assets, copies them into a per-job private
working directory, probes each source and rejects source trims beyond the real
media duration. Video clips are composed onto a 1080x1920 portrait canvas;
title text is passed through UTF-8 text files with drawtext expansion disabled.
Audio clips use the existing bounded audio-mix builder, including source in-points,
timeline delay, gain, fades and limiter. Both FFmpeg stages run with argv-only
execution, no shell, bounded wall time/output bytes and lease-loss cancellation.
The final MP4 is ffprobe-validated for H.264, 1080x1920 portrait dimensions,
duration, size and audio presence before it is returned to the lease-fenced
artifact store for checksum-backed adoption. FFmpeg and ffprobe inputs are
restricted to local file/pipe protocols.

The render job now carries its originating workspace and principal context so
the asset store re-checks membership and clean scan status when opening media.
A failed or lease-lost handoff removes the staged MP4. Worker startup also
reconciles stale staging files/work directories and unindexed artifact files
after conservative grace periods. EDL v1 now supports up to eight explicit
audio clips with bounded gain, source trims and fades.

The dedicated Compose service runs with no network, a read-only root
filesystem, a bounded temporary filesystem, dropped Linux capabilities,
no-new-privileges, and configured CPU, memory and process-count limits. The
staging/artifact volume is shared with the API data volume; its disk quota still
requires host-level enforcement.

## Remaining production gates

- Pin FFmpeg/ffprobe versions and validate codec/filter availability on target
  platforms; the current image installs the distribution packages.
- Run real-media integration and crash/lease-loss tests on the target runtime.
- Connect an actual malware scanner to the asset quarantine transition.
- Add authenticated upload/render/review APIs and retention cleanup.
- CI tests execute a fake FFmpeg/ffprobe toolchain against generated fixtures;
  the actual pinned binaries, representative real-media renders and production
  filesystem isolation still require target-runtime validation.
