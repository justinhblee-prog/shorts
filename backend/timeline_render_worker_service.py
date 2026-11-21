"""Dedicated optional worker for lease-fenced timeline_render jobs.

Enable with the Compose render profile after private media roots and trusted
FFmpeg/ffprobe binaries have been configured on the target host.
"""
from __future__ import annotations

import os
import sqlite3
import signal
import socket
import threading
import time

from media_binary_pin import verify_binary_manifest
from queue_store import JobQueue
from render_artifact_store import RenderArtifactStore
from timeline_ffmpeg_renderer import TimelineFFmpegRenderer, workspace_asset_resolver
from timeline_render_worker import TimelineRenderWorker
from worker_runtime import parse_worker_runtime_config
from workspace_asset_store import WorkspaceAssetStore
from workspace_store import WorkspaceStore


DB_PATH = os.getenv("NEXUS_DB_PATH", "/app/data/nexus.sqlite3")
PRIVATE_ROOT = os.getenv("NEXUS_PRIVATE_MEDIA_ROOT", "/app/data/private-media")
STAGING_ROOT = os.getenv("NEXUS_RENDER_STAGING_ROOT", "/app/data/render-staging")
ARTIFACT_ROOT = os.getenv("NEXUS_RENDER_ARTIFACT_ROOT", "/app/data/render-artifacts")
FFMPEG_PATH = os.getenv("NEXUS_FFMPEG_PATH", "/usr/bin/ffmpeg")
FFPROBE_PATH = os.getenv("NEXUS_FFPROBE_PATH", "/usr/bin/ffprobe")


def verify_media_binaries():
    """Fail closed unless the configured FFmpeg tools match the image manifest."""
    manifest_path = os.getenv(
        "NEXUS_MEDIA_BINARY_MANIFEST", "/usr/share/nexus-media-binaries.sha256"
    )
    verified = verify_binary_manifest((FFMPEG_PATH, FFPROBE_PATH), manifest_path)
    print(
        "media_binary_manifest_verified "
        f"ffmpeg_sha256={verified[FFMPEG_PATH]} ffprobe_sha256={verified[FFPROBE_PATH]}"
    )
    return verified
FONT_PATH = os.getenv("NEXUS_TITLE_FONT_PATH", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")


def _integer_env(name, default, minimum, maximum):
    raw = os.getenv(name, str(default))
    if not raw.isdecimal():
        raise ValueError(f"{name} must be a decimal integer")
    value = int(raw)
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


LEASE_SECONDS, IDLE_SECONDS, HEARTBEAT_SECONDS = parse_worker_runtime_config(
    os.getenv("NEXUS_RENDER_LEASE_SECONDS", "300"),
    os.getenv("NEXUS_RENDER_IDLE_SECONDS", "3"),
    os.getenv("NEXUS_RENDER_HEARTBEAT_SECONDS", "10"),
)
WIDTH = _integer_env("NEXUS_RENDER_WIDTH", 1080, 16, 8192)
HEIGHT = _integer_env("NEXUS_RENDER_HEIGHT", 1920, 16, 8192)
FPS = _integer_env("NEXUS_RENDER_FPS", 30, 1, 60)
MAX_INPUT_BYTES = _integer_env("NEXUS_RENDER_MAX_INPUT_BYTES", 2_000_000_000, 1, 10_000_000_000)
MAX_OUTPUT_BYTES = _integer_env("NEXUS_RENDER_MAX_OUTPUT_BYTES", 2_000_000_000, 1, 10_000_000_000)
TIMEOUT_SECONDS = _integer_env("NEXUS_RENDER_TIMEOUT_SECONDS", 900, 1, 3600)
WORKER_ID = os.getenv("NEXUS_RENDER_WORKER_ID", "").strip() or (
    "nexus-render-" + socket.gethostname()
)
if len(WORKER_ID) > 128:
    raise ValueError("NEXUS_RENDER_WORKER_ID must be at most 128 characters")


def _resolve_snapshot_creator(workspace_id, payload):
    snapshot_id = payload.get("snapshot_id")
    snapshot_sha256 = payload.get("snapshot_sha256")
    if not isinstance(snapshot_id, str) or not isinstance(snapshot_sha256, str):
        raise RuntimeError("render job is missing its snapshot identity")
    with sqlite3.connect(DB_PATH, timeout=30) as db:
        row = db.execute("""
            SELECT creator_principal_id,payload_sha256
            FROM timeline_edl_snapshots
            WHERE id=? AND workspace_id=?
        """, (snapshot_id, workspace_id)).fetchone()
    if row is None or row[1] != snapshot_sha256:
        raise RuntimeError("render job does not match a workspace-owned immutable snapshot")
    return row[0]


def build_worker():
    # Verify before opening the durable queue or registering a worker generation.
    verify_media_binaries()
    queue = JobQueue(DB_PATH, LEASE_SECONDS)
    workspaces = WorkspaceStore(DB_PATH)
    assets = WorkspaceAssetStore(DB_PATH, PRIVATE_ROOT, workspaces)
    artifact_store = RenderArtifactStore(
        queue, STAGING_ROOT, ARTIFACT_ROOT,
        max_bytes=MAX_OUTPUT_BYTES, ffprobe_path=FFPROBE_PATH,
        require_audio=False, max_duration_ms=3_600_000,
    )
    renderer = TimelineFFmpegRenderer(
        STAGING_ROOT, workspace_asset_resolver(assets),
        FFMPEG_PATH, FFPROBE_PATH,
        width=WIDTH, height=HEIGHT, fps=FPS,
        max_input_bytes=MAX_INPUT_BYTES,
        max_output_bytes=MAX_OUTPUT_BYTES,
        timeout_seconds=TIMEOUT_SECONDS,
        font_path=FONT_PATH,
    )
    stopping = threading.Event()
    worker = TimelineRenderWorker(
        queue, renderer, WORKER_ID, "pending-registration",
        heartbeat_seconds=HEARTBEAT_SECONDS,
        artifact_store=artifact_store,
        shutdown_event=stopping,
        principal_resolver=_resolve_snapshot_creator,
    )
    return queue, worker, stopping, artifact_store


def main():
    queue, worker, stopping, artifact_store = build_worker()
    generation = None

    def handle_shutdown(signum, frame):
        stopping.set()

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)
    try:
        registration = queue.register_worker(WORKER_ID, socket.gethostname())
        generation = registration["generation_token"]
        worker.generation_token = generation
        print(
            f"timeline_render_worker_started id={WORKER_ID} "
            f"lease_seconds={LEASE_SECONDS} heartbeat_seconds={HEARTBEAT_SECONDS}"
        )
        last_cleanup = 0.0
        while not stopping.is_set():
            if time.monotonic() - last_cleanup >= 300:
                artifact_store.reconcile_orphaned_files(grace_seconds=7200)
                artifact_store.reconcile_orphaned_staging(grace_seconds=7200)
                last_cleanup = time.monotonic()
            if queue.is_paused():
                stopping.wait(IDLE_SECONDS)
                continue
            if not worker.run_once():
                stopping.wait(IDLE_SECONDS)
    finally:
        stopping.set()
        if generation is not None:
            queue.mark_worker_offline(WORKER_ID, generation)
        print("timeline_render_worker_stopped")


if __name__ == "__main__":
    main()
