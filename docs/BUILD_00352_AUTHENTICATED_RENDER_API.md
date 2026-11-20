# BUILD-00352 Authenticated private media and render APIs

## Authentication and workspace scope

Every endpoint requires the X-Review-Token header and an explicit operator permission. The API derives the principal from the token; callers cannot choose an owner or reviewer identity.

- Upload, rescan, asset metadata, render submission and render status require media.manage.
- Pending artifact listing and download require review.read.
- Every route resolves the requested workspace against the authenticated principal, then the asset/snapshot store independently checks SQLite workspace membership.
- Set NEXUS_WORKSPACE_AUTH_MODE=sqlite for workspace memberships created by the workspace API. Legacy configuration-based workspace scopes remain available for existing deployments.

## Endpoints

| Method and path | Purpose |
|---|---|
| POST /api/operator/workspaces/{workspace_id}/assets?filename=clip.mp4 | Stream a bounded raw binary media upload into private workspace storage |
| POST /api/operator/workspaces/{workspace_id}/assets/{asset_id}/scan | Retry malware and source-media probing for a pending asset |
| GET /api/operator/workspaces/{workspace_id}/assets/{asset_id} | Read asset quarantine and verified media metadata |
| POST /api/operator/workspaces/{workspace_id}/renders | Validate assets, persist immutable EDL snapshot and atomically enqueue render job |
| GET /api/operator/workspaces/{workspace_id}/renders/{snapshot_id} | Read durable render job status without exposing worker lease tokens |
| GET /api/operator/workspaces/{workspace_id}/render-artifacts | List review-pending artifacts for a workspace |
| GET /api/operator/workspaces/{workspace_id}/render-artifacts/{artifact_id}/download | Download a checksum-verified private MP4 for reviewer inspection |

Uploads use a raw request body, not multipart form data. Supported suffixes are MP4/MOV/M4V/WebM/MKV and MP3/WAV/M4A/AAC/FLAC/OGG. The API enforces Content-Length and streamed-byte limits and uses a spooled temporary file; caller-supplied paths and URLs are never accepted.

## Quarantine and source verification

New assets start with scan_status=pending. The API never exposes an endpoint that lets an operator mark an asset clean.

When NEXUS_MEDIA_SCAN_ENABLED=true, the upload or rescan request:
1. Re-hashes the private staged file and checks its registered server-side SHA-256.
2. Runs ClamAV without a shell using the configured scanner timeout and byte limit.
3. Runs bounded local ffprobe with the file/pipe protocol whitelist, duration, stream-count, dimension, sample-rate, channel-count and byte-size limits.
4. Re-hashes the file again after both scanners complete.
5. Stores the verified duration and audio/video stream metadata with the clean state.

If ClamAV or ffprobe is unavailable, the asset remains pending and cannot be rendered. Malware or invalid media is marked rejected. Enable the ClamAV signature updater with:

```bash
# Set NEXUS_MEDIA_SCAN_ENABLED=true in .env, then:
docker compose --profile media-scan up -d clamav-updater
```

The render submission store rejects pending/rejected assets, wrong stream types and source trims beyond the probed source duration. The media API has a separate five-request-per-minute default limit.

## Review and publishing boundary

The artifact endpoints expose only artifacts in review_pending and reverify their stored SHA-256 and byte size before download. This increment does not add an approve/publish action. The rendered MP4 remains private; publishing to YouTube/TikTok is not performed by these routes.

## Remaining deployment gates

- The optional render-worker Compose profile must be enabled explicitly.
- Pin and verify FFmpeg/ffprobe and ClamAV binaries/signature databases in the target environment.
- Apply hard container CPU, memory, disk, process-count and network isolation.
- Run representative real video/audio media through the pinned toolchain.
- Configure retention cleanup and production filesystem permissions.
