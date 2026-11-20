"""Dedicated local worker for private EDL render jobs.

Run: python timeline_render_worker_main.py
This process consumes only timeline_render jobs and never publishes media.
"""
from __future__ import annotations

import os
import signal
import socket
import threading
from pathlib import Path

from queue_store import JobQueue
from worker_runtime import parse_worker_runtime_config, resolve_worker_id
from workspace_store import WorkspaceStore
from workspace_asset_store import WorkspaceAssetStore
from render_artifact_store import RenderArtifactStore
from timeline_render_worker import create_edl_render_worker


DB_PATH = os.getenv("NEXUS_DB_PATH", "data/nexus.sqlite3")
LEASE_SECONDS, IDLE_SECONDS, HEARTBEAT_SECONDS = parse_worker_runtime_config(
    os.getenv("NEXUS_LEASE_SECONDS", "300"),
    os.getenv("NEXUS_IDLE_SECONDS", "3"),
    os.getenv("NEXUS_HEARTBEAT_SECONDS", "10"),
)
WORKER_ID = resolve_worker_id(
    os.getenv("NEXUS_TIMELINE_WORKER_ID"),
    "timeline-" + socket.gethostname(),
)
FFMPEG_PATH = os.getenv("NEXUS_FFMPEG_PATH", "/usr/bin/ffmpeg")
FFPROBE_PATH = os.getenv("NEXUS_FFPROBE_PATH", "/usr/bin/ffprobe")
PRIVATE_MEDIA_ROOT = os.getenv("NEXUS_PRIVATE_MEDIA_ROOT", "data/private-media")
STAGING_ROOT = os.getenv("NEXUS_RENDER_STAGING_ROOT", "data/render-staging")
ARTIFACT_ROOT = os.getenv("NEXUS_RENDER_ARTIFACT_ROOT", "data/render-artifacts")

queue = JobQueue(DB_PATH, LEASE_SECONDS)
workspace_store = WorkspaceStore(DB_PATH)
asset_store = WorkspaceAssetStore(
    DB_PATH, PRIVATE_MEDIA_ROOT, workspace_store,
    max_asset_bytes=int(os.getenv("NEXUS_MAX_ASSET_BYTES", "500000000")),
)
artifact_store = RenderArtifactStore(
    queue, STAGING_ROOT, ARTIFACT_ROOT,
    max_bytes=int(os.getenv("NEXUS_MAX_RENDER_BYTES", "2000000000")),
    ffprobe_path=FFPROBE_PATH,
    require_audio=os.getenv("NEXUS_RENDER_REQUIRE_AUDIO", "false").lower() == "true",
    max_duration_ms=int(os.getenv("NEXUS_RENDER_MAX_DURATION_MS", "3600000")),
)
stopping = threading.Event()


def handle_shutdown_signal(signum, frame):
    # TimelineRenderWorker observes this event and cancels active FFmpeg work.
    stopping.set()


def main():
    signal.signal(signal.SIGTERM, handle_shutdown_signal)
    signal.signal(signal.SIGINT, handle_shutdown_signal)
    registration = queue.register_worker(WORKER_ID, socket.gethostname())
    generation_token = registration["generation_token"]
    worker = create_edl_render_worker(
        queue, asset_store, WORKER_ID, generation_token,
        Path(STAGING_ROOT).resolve(), FFMPEG_PATH, artifact_store,
        ffprobe_path=FFPROBE_PATH,
        title_font_path=os.getenv("NEXUS_TITLE_FONT_PATH") or None,
        width=int(os.getenv("NEXUS_RENDER_WIDTH", "1080")),
        height=int(os.getenv("NEXUS_RENDER_HEIGHT", "1920")),
        fps=int(os.getenv("NEXUS_RENDER_FPS", "30")),
        max_input_bytes=int(os.getenv("NEXUS_MAX_ASSET_BYTES", "500000000")),
        timeout_seconds=int(os.getenv("NEXUS_RENDER_TIMEOUT_SECONDS", "3600")),
        heartbeat_seconds=HEARTBEAT_SECONDS,
        shutdown_event=stopping,
    )
    print(
        f"timeline_render_worker_started id={WORKER_ID} "
        f"lease_seconds={LEASE_SECONDS} heartbeat_seconds={HEARTBEAT_SECONDS}"
    )
    try:
        while not stopping.is_set():
            if queue.is_paused():
                stopping.wait(IDLE_SECONDS)
                continue
            if not worker.run_once():
                stopping.wait(IDLE_SECONDS)
    finally:
        try:
            queue.mark_worker_offline(WORKER_ID, generation_token)
        finally:
            print(f"timeline_render_worker_stopped id={WORKER_ID}")


if __name__ == "__main__":
    main()
