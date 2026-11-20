"""Dedicated lease-fenced worker for timeline render jobs.

Run: python render_worker.py
This worker claims only timeline_render jobs and never invokes publishing providers.
"""
from __future__ import annotations

import hashlib
import os
import signal
import socket
import threading
from pathlib import Path

from queue_store import JobQueue, LeaseConflict
from render_asset_store import RenderAssetStore, RenderAssetError
from render_output_store import RenderOutputStore, RenderOutputLeaseConflict
from timeline_edl import validate_edl, EDLValidationError
from timeline_renderer import TimelineRenderer, TimelineRenderError, TimelineRenderCancelled
from worker_runtime import parse_worker_runtime_config, resolve_worker_id


DB_PATH = os.getenv("NEXUS_DB_PATH", "data/nexus.sqlite3")
LEASE_SECONDS, IDLE_SECONDS, HEARTBEAT_SECONDS = parse_worker_runtime_config(
    os.getenv("NEXUS_RENDER_LEASE_SECONDS", os.getenv("NEXUS_LEASE_SECONDS", "300")),
    os.getenv("NEXUS_RENDER_IDLE_SECONDS", "2"),
    os.getenv("NEXUS_RENDER_HEARTBEAT_SECONDS", os.getenv("NEXUS_HEARTBEAT_SECONDS", "10")),
)
WORKER_ID = resolve_worker_id(
    os.getenv("NEXUS_RENDER_WORKER_ID"), socket.gethostname() + "-render"
)
JOB_TYPE = "timeline_render"

queue = JobQueue(DB_PATH, LEASE_SECONDS)
asset_store = RenderAssetStore(DB_PATH, os.getenv("NEXUS_MEDIA_DIR", "data/media"))
output_store = RenderOutputStore(DB_PATH, os.getenv("NEXUS_MEDIA_DIR", "data/media"))
renderer = TimelineRenderer(os.getenv("NEXUS_MEDIA_DIR", "data/media"))
stopping = threading.Event()
active_stop_event = None
active_job_id = None
WORKER_GENERATION_TOKEN = None


def handle_shutdown_signal(signum, frame):
    stopping.set()
    if active_stop_event is not None:
        active_stop_event.set()


def heartbeat_loop(job, lost_lease, stop_heartbeat, stop_render):
    while not stop_heartbeat.wait(HEARTBEAT_SECONDS):
        try:
            queue.heartbeat(
                job["id"], WORKER_ID, job["lease_token"],
                WORKER_GENERATION_TOKEN, workspace_id=job["workspace_id"],
            )
        except Exception:
            lost_lease.set()
            stop_render.set()
            return


def _fail_if_owned(job, code, message, retryable):
    try:
        queue.fail(
            job["id"], WORKER_ID, job["lease_token"], code, message, retryable,
            generation_token=WORKER_GENERATION_TOKEN,
            workspace_id=job["workspace_id"],
        )
    except LeaseConflict:
        # A cancelled or superseded lease must never be completed by this worker.
        return False
    return True


def _discard_unadopted_output(result, workspace_id):
    relative_path = result.get("media_path") if isinstance(result, dict) else None
    media_root = getattr(asset_store, "media_root", None)
    if not isinstance(relative_path, str) or media_root is None:
        return
    candidate = Path(media_root) / relative_path
    if candidate.is_symlink():
        return
    try:
        resolved = candidate.resolve(strict=True)
        root = Path(media_root).resolve()
        resolved.relative_to(root)
        namespace = hashlib.sha256(workspace_id.encode("utf-8")).hexdigest()
        workspace_output_root = (root / namespace / "render-outputs").resolve(strict=True)
        workspace_output_root.relative_to(root)
        resolved.relative_to(workspace_output_root)
        resolved.unlink(missing_ok=True)
    except (OSError, ValueError):
        return


def _discard_stale_adoption(job):
    discard = getattr(output_store, "discard_if_stale", None)
    if callable(discard):
        discard(
            job["id"], job["workspace_id"], job["attempt"], job["lease_token"]
        )


def run_once():
    global active_job_id, active_stop_event
    job = queue.claim(
        WORKER_ID, socket.gethostname(), job_type=JOB_TYPE,
        generation_token=WORKER_GENERATION_TOKEN,
    )
    if job is None:
        return False

    lost_lease = threading.Event()
    stop_heartbeat = threading.Event()
    stop_render = threading.Event()
    heartbeat = threading.Thread(
        target=heartbeat_loop,
        args=(job, lost_lease, stop_heartbeat, stop_render),
        daemon=True,
    )
    active_job_id = job["id"]
    active_stop_event = stop_render
    heartbeat.start()
    render_result = None
    output_adopted = False
    try:
        payload = job.get("payload") or {}
        workspace_id = job.get("workspace_id")
        if not workspace_id:
            raise RenderAssetError("Render job has no workspace scope")
        edl = validate_edl(payload.get("edl"))
        if any(clip["type"] != "video" for clip in edl["clips"]):
            raise TimelineRenderError("Title clips are not supported by the render worker")
        video_ids = [clip["asset_id"] for clip in edl["clips"]]
        asset_paths = asset_store.resolve_asset_paths(
            workspace_id, video_ids, expected_asset_type="video"
        )
        audio_asset_id = payload.get("audio_asset_id")
        if audio_asset_id is not None:
            audio_paths = asset_store.resolve_asset_paths(
                workspace_id, [audio_asset_id], expected_asset_type="audio"
            )
            asset_paths.update(audio_paths)
        if lost_lease.is_set() or stop_render.is_set():
            raise TimelineRenderCancelled("Render worker stopped before FFmpeg execution")
        output_dir = asset_store.workspace_render_output_dir(workspace_id)
        result = renderer.render(
            edl, asset_paths, output_dir=output_dir,
            audio_asset_id=audio_asset_id, stop_event=stop_render,
        )
        render_result = result
        if lost_lease.is_set() or stop_render.is_set():
            raise TimelineRenderCancelled("Render lease was lost before output adoption")
        output = output_store.adopt(
            job["id"], workspace_id, WORKER_ID, job["lease_token"],
            job["attempt"], result,
        )
        output_adopted = True
        if lost_lease.is_set() or stop_render.is_set():
            raise TimelineRenderCancelled("Render lease was lost before review handoff")
        queue.finish(
            job["id"], WORKER_ID, job["lease_token"],
            {
                "render_id": output["render_id"],
                "sha256": output["sha256"],
                "size_bytes": output["size_bytes"],
                "duration_seconds": output["duration_seconds"],
                "width": output["width"],
                "height": output["height"],
                "audio_track_present": output["audio_track_present"],
                "review_status": "pending",
            },
            generation_token=WORKER_GENERATION_TOKEN,
            workspace_id=workspace_id,
        )
        print(f"render_review_pending job={job['id']} render={output['render_id']}")
    except TimelineRenderCancelled as exc:
        if output_adopted:
            _discard_stale_adoption(job)
        elif render_result is not None:
            _discard_unadopted_output(render_result, job["workspace_id"])
        if not lost_lease.is_set():
            _fail_if_owned(job, "render_cancelled", str(exc), retryable=True)
        print(f"render_cancelled job={job['id']}")
    except (LeaseConflict, RenderOutputLeaseConflict):
        if output_adopted:
            _discard_stale_adoption(job)
        elif render_result is not None:
            _discard_unadopted_output(render_result, job["workspace_id"])
        lost_lease.set()
        stop_render.set()
        print(f"render_lease_lost job={job['id']}")
    except (RenderAssetError, TimelineRenderError, EDLValidationError) as exc:
        if output_adopted:
            _discard_stale_adoption(job)
        elif render_result is not None:
            _discard_unadopted_output(render_result, job["workspace_id"])
        if not lost_lease.is_set():
            _fail_if_owned(job, "render_validation_failed", str(exc), retryable=False)
        print(f"render_failed job={job['id']} code=render_validation_failed error={type(exc).__name__} reason={str(exc)[:240]}")
    except Exception as exc:
        if output_adopted:
            _discard_stale_adoption(job)
        elif render_result is not None:
            _discard_unadopted_output(render_result, job["workspace_id"])
        if not lost_lease.is_set():
            _fail_if_owned(job, "render_worker_error", "Render worker failed unexpectedly", retryable=False)
        print(f"render_failed job={job['id']} error={type(exc).__name__}")
    finally:
        stop_heartbeat.set()
        stop_render.set() if stopping.is_set() else None
        if heartbeat.is_alive():
            heartbeat.join()
        active_job_id = None
        active_stop_event = None
    return True


def main():
    signal.signal(signal.SIGTERM, handle_shutdown_signal)
    signal.signal(signal.SIGINT, handle_shutdown_signal)
    registration = queue.register_worker(WORKER_ID, socket.gethostname())
    global WORKER_GENERATION_TOKEN
    WORKER_GENERATION_TOKEN = registration["generation_token"]
    print(f"render_worker_started id={WORKER_ID} lease_seconds={LEASE_SECONDS}")
    try:
        while not stopping.is_set():
            if not run_once():
                stopping.wait(IDLE_SECONDS)
    finally:
        if active_stop_event is not None:
            active_stop_event.set()
        if WORKER_GENERATION_TOKEN is not None:
            queue.mark_worker_offline(WORKER_ID, WORKER_GENERATION_TOKEN)
        WORKER_GENERATION_TOKEN = None
        print("render_worker_stopped")


if __name__ == "__main__":
    main()
