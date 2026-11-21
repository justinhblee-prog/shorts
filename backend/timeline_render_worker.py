"""Lease-fenced consumer for immutable timeline render jobs.

The renderer is injected by the deployment. The worker never treats queue
completion as proof of publication; successful renders enter review_pending.
"""
from __future__ import annotations

import inspect
import threading

from ffmpeg_edl_renderer import EDLFFmpegRenderer


class TimelineRenderWorker:
    def __init__(self, queue, renderer, worker_id, generation_token,
                 heartbeat_seconds=10, artifact_store=None, shutdown_event=None,
                 principal_resolver=None):
        if not callable(renderer):
            raise TypeError("renderer callback is required")
        if not worker_id or not generation_token:
            raise ValueError("worker identity and generation token are required")
        if isinstance(heartbeat_seconds, bool) or not isinstance(heartbeat_seconds, (int, float)) or heartbeat_seconds <= 0:
            raise ValueError("heartbeat_seconds must be positive")
        self.queue = queue
        self.renderer = renderer
        self.worker_id = worker_id
        self.generation_token = generation_token
        self.heartbeat_seconds = heartbeat_seconds
        self.artifact_store = artifact_store
        self.shutdown_event = shutdown_event
        self.principal_resolver = principal_resolver

    def run_once(self):
        if self.shutdown_event is not None and self.shutdown_event.is_set():
            return False
        job = self.queue.claim(
            self.worker_id, job_type="timeline_render",
            generation_token=self.generation_token,
        )
        if job is None:
            return False

        lease_lost = threading.Event()
        cancel_render = threading.Event()
        stop = threading.Event()

        def beat():
            while not stop.wait(self.heartbeat_seconds):
                try:
                    self.queue.heartbeat(
                        job["id"], self.worker_id, job["lease_token"],
                        self.generation_token, workspace_id=job["workspace_id"],
                    )
                except Exception:
                    lease_lost.set()
                    cancel_render.set()
                    return

        def cancel_for_shutdown():
            if self.shutdown_event is None:
                return
            while not stop.wait(0.1):
                if self.shutdown_event.is_set():
                    cancel_render.set()
                    return

        heartbeat = threading.Thread(target=beat, daemon=True)
        shutdown_watch = threading.Thread(target=cancel_for_shutdown, daemon=True)
        heartbeat.start()
        shutdown_watch.start()
        staged_path = None
        adopted = False
        try:
            payload = job["payload"]
            principal_id = payload.get("creator_principal_id")
            if self.principal_resolver is not None:
                resolved = self.principal_resolver(job["workspace_id"], payload)
                if principal_id is not None and principal_id != resolved:
                    raise RuntimeError("render job creator does not match immutable snapshot owner")
                principal_id = resolved

            render_payload = dict(payload)
            render_payload["workspace_id"] = job["workspace_id"]
            try:
                parameters = inspect.signature(self.renderer).parameters
                accepts_kwargs = any(
                    item.kind == inspect.Parameter.VAR_KEYWORD
                    for item in parameters.values()
                )
                context = {"workspace_id": job["workspace_id"], "principal_id": principal_id}
                context = {
                    key: value for key, value in context.items()
                    if accepts_kwargs or key in parameters
                }
            except (TypeError, ValueError):
                context = {}
            result = self.renderer(render_payload, stop_event=cancel_render, **context)
            if isinstance(result, dict):
                staged_path = result.get("staged_path")
            if lease_lost.is_set() or (cancel_render.is_set() and not (self.shutdown_event is not None and self.shutdown_event.is_set())):
                raise RuntimeError("timeline render lease was lost")
            if self.shutdown_event is not None and self.shutdown_event.is_set():
                raise RuntimeError("timeline render cancelled for graceful worker shutdown")
            if self.artifact_store is not None:
                if not isinstance(result, dict) or not staged_path:
                    raise RuntimeError("renderer must return staged_path when artifact adoption is enabled")
                self.artifact_store.adopt(
                    job["id"], self.worker_id, job["lease_token"],
                    self.generation_token, job["workspace_id"],
                    payload["snapshot_id"], payload["snapshot_sha256"], staged_path,
                )
                adopted = True
            else:
                self.queue.finish(
                    job["id"], self.worker_id, job["lease_token"],
                    {"render_result": result, "snapshot_id": payload["snapshot_id"],
                     "review_required": True},
                    generation_token=self.generation_token,
                    workspace_id=job["workspace_id"],
                )
            return True
        except Exception as exc:
            if staged_path and self.artifact_store is not None and not adopted:
                try:
                    self.artifact_store.discard_staged(staged_path)
                except Exception:
                    pass
            if not lease_lost.is_set():
                try:
                    shutting_down = self.shutdown_event is not None and self.shutdown_event.is_set()
                    self.queue.fail(
                        job["id"], self.worker_id, job["lease_token"],
                        "timeline_worker_shutdown" if shutting_down else "timeline_render_failed",
                        "Worker shutdown requested; render will be retried" if shutting_down else str(exc),
                        True, generation_token=self.generation_token,
                        workspace_id=job["workspace_id"],
                    )
                except Exception:
                    pass
            return False
        finally:
            stop.set()
            heartbeat.join(timeout=max(1.0, self.heartbeat_seconds + 1.0))
            shutdown_watch.join(timeout=1.0)

def create_edl_render_worker(queue, asset_store, worker_id, generation_token,
                             staging_root, ffmpeg_path, artifact_store, *,
                             audio_tracks_resolver=None, ffprobe_path=None, title_font_path=None, width=1080, height=1920,
                             fps=30, max_input_bytes=2_000_000_000,
                             timeout_seconds=3600, heartbeat_seconds=10,
                             shutdown_event=None):
    """Wire the EDL renderer, workspace asset authorization and artifact adoption."""
    if artifact_store is None:
        raise ValueError("artifact_store is required for lease-fenced output adoption")

    def resolve_asset(workspace_id, principal_id, asset_id):
        return asset_store.resolve_clean_asset_path(
            workspace_id, principal_id, asset_id
        )

    renderer = EDLFFmpegRenderer(
        staging_root, ffmpeg_path, resolve_asset,
        audio_tracks_resolver=audio_tracks_resolver, ffprobe_path=ffprobe_path,
        title_font_path=title_font_path, width=width, height=height, fps=fps,
        max_input_bytes=max_input_bytes, timeout_seconds=timeout_seconds,
    )
    return TimelineRenderWorker(
        queue, renderer, worker_id, generation_token,
        heartbeat_seconds=heartbeat_seconds, artifact_store=artifact_store,
        shutdown_event=shutdown_event,
    )
