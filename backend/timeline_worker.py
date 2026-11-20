"""Dedicated durable worker for EDL-to-MP4 timeline render jobs.

Run inside the restricted timeline-worker container:
    python timeline_worker.py

This process never uploads or publishes outputs. Completed artifacts remain
private and enter review_pending through lease-fenced artifact adoption.
"""
from __future__ import annotations

import os
import signal
import socket
import threading
import time

from queue_store import JobQueue
from render_artifact_store import RenderArtifactStore
from timeline_ffmpeg_renderer import TimelineFFmpegRenderer
from timeline_render_worker import TimelineRenderWorker
from worker_runtime import parse_worker_runtime_config, resolve_worker_id
from workspace_asset_store import WorkspaceAssetStore


def _env_int(name, default, minimum, maximum):
    value = os.getenv(name, str(default))
    if not value.isdecimal():
        raise ValueError(f"{name} must be an unsigned decimal integer")
    parsed = int(value)
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return parsed


DB_PATH = os.getenv("NEXUS_DB_PATH", "/app/data/nexus.sqlite3")
PRIVATE_MEDIA_ROOT = os.getenv("NEXUS_PRIVATE_MEDIA_ROOT", "/app/data/private-media")
STAGING_ROOT = os.getenv("NEXUS_RENDER_STAGING_ROOT", "/app/data/render-staging")
ARTIFACT_ROOT = os.getenv("NEXUS_RENDER_ARTIFACT_ROOT", "/app/data/render-artifacts")
FFMPEG_PATH = os.getenv("NEXUS_FFMPEG_PATH", "/usr/bin/ffmpeg")
FFPROBE_PATH = os.getenv("NEXUS_FFPROBE_PATH", "/usr/bin/ffprobe")
FONT_PATH = os.getenv("NEXUS_RENDER_FONT_PATH", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
LEASE_SECONDS, IDLE_SECONDS, HEARTBEAT_SECONDS = parse_worker_runtime_config(
    os.getenv("NEXUS_LEASE_SECONDS", "300"),
    os.getenv("NEXUS_IDLE_SECONDS", "3"),
    os.getenv("NEXUS_HEARTBEAT_SECONDS", "10"),
)
RENDER_TIMEOUT_SECONDS = _env_int("NEXUS_RENDER_TIMEOUT_SECONDS", 900, 1, 3600)
MAX_OUTPUT_BYTES = _env_int("NEXUS_RENDER_MAX_OUTPUT_BYTES", 536870912, 1024, 2147483648)
MAX_INPUT_BYTES = _env_int("NEXUS_RENDER_MAX_INPUT_BYTES", 2147483648, 1, 2147483648)

WORKER_ID = resolve_worker_id(os.getenv("NEXUS_TIMELINE_WORKER_ID"), socket.gethostname())
queue = JobQueue(DB_PATH, LEASE_SECONDS)
assets = WorkspaceAssetStore(DB_PATH, PRIVATE_MEDIA_ROOT)
artifact_store = RenderArtifactStore(
    queue, STAGING_ROOT, ARTIFACT_ROOT,
    max_bytes=MAX_OUTPUT_BYTES,
    ffprobe_path=FFPROBE_PATH,
    require_audio=False,
)
renderer = TimelineFFmpegRenderer(
    assets, STAGING_ROOT, FFMPEG_PATH, FFPROBE_PATH,
    font_path=FONT_PATH,
    timeout_seconds=RENDER_TIMEOUT_SECONDS,
    max_output_bytes=MAX_OUTPUT_BYTES,
    max_input_bytes=MAX_INPUT_BYTES,
)
stopping = threading.Event()
generation_token = None
worker = None


def handle_shutdown(signum, frame):
    stopping.set()


def main():
    global generation_token, worker
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)
    registration = queue.register_worker(WORKER_ID, socket.gethostname())
    generation_token = registration["generation_token"]
    worker = TimelineRenderWorker(
        queue, renderer, WORKER_ID, generation_token,
        heartbeat_seconds=HEARTBEAT_SECONDS,
        artifact_store=artifact_store,
        shutdown_event=stopping,
    )
    print(
        f"timeline_worker_started id={WORKER_ID} lease_seconds={LEASE_SECONDS} "
        f"heartbeat_seconds={HEARTBEAT_SECONDS}"
    )
    try:
        while not stopping.is_set():
            if queue.is_paused():
                stopping.wait(IDLE_SECONDS)
                continue
            if not worker.run_once():
                stopping.wait(IDLE_SECONDS)
    finally:
        stopping.set()
        queue.mark_worker_offline(WORKER_ID, generation_token)
        print(f"timeline_worker_stopped id={WORKER_ID}")


if __name__ == "__main__":
    main()
