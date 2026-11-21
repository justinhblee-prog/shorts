"""Dedicated optional worker for lease-fenced timeline_render jobs.

Enable with the Compose render profile after private media roots and trusted
FFmpeg/ffprobe binaries have been configured on the target host.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import signal
import socket
import threading
import time

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
RECONCILE_INTERVAL_SECONDS = _integer_env(
    "NEXUS_RENDER_RECONCILE_INTERVAL_SECONDS", 300, 60, 86_400
)
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


def reconcile_artifacts(artifact_store, logger=None):
    """Reconcile only crash-left staging and unindexed generated artifacts.

    Indexed artifacts are intentionally never deleted: retention policy and
    disk quotas require an explicit operator decision before that is safe.
    """
    log = logger or logging.getLogger("nexus.timeline_render_worker")
    staging = artifact_store.reconcile_orphaned_staging(grace_seconds=7200)
    artifacts = artifact_store.reconcile_orphaned_files(grace_seconds=7200)
    removed = (
        staging["removed_files"] + staging["removed_directories"] + artifacts["removed"]
    )
    log.info(
        "render_artifact_reconciliation_completed removed_staging_files=%s "
        "removed_staging_directories=%s removed_artifacts=%s removed_bytes=%s",
        staging["removed_files"], staging["removed_directories"],
        artifacts["removed"], staging["removed_bytes"] + artifacts["removed_bytes"],
    )
    return {"staging": staging, "artifacts": artifacts, "removed": removed}


def build_worker():
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
    logging.basicConfig(
        level=os.getenv("NEXUS_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
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
        logging.getLogger("nexus.timeline_render_worker").info(
            "timeline_render_worker_started id=%s lease_seconds=%s "
            "heartbeat_seconds=%s reconciliation_interval_seconds=%s",
            WORKER_ID, LEASE_SECONDS, HEARTBEAT_SECONDS, RECONCILE_INTERVAL_SECONDS,
        )
        next_reconciliation = 0.0
        logger = logging.getLogger("nexus.timeline_render_worker")
        while not stopping.is_set():
            now = time.monotonic()
            if now >= next_reconciliation:
                try:
                    reconcile_artifacts(artifact_store, logger)
                except Exception:
                    # Cleanup failure must be visible but must not take the render
                    # worker offline; retry at the next bounded interval.
                    logger.exception("render_artifact_reconciliation_failed")
                next_reconciliation = time.monotonic() + RECONCILE_INTERVAL_SECONDS
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
