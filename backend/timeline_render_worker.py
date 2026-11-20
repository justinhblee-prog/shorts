"""Lease-fenced consumer for immutable timeline render jobs.

The renderer is injected by the deployment. The worker never treats queue
completion as proof of publication; successful renders enter review_pending.
"""
from __future__ import annotations

import inspect
import threading


class TimelineRenderWorker:
    def __init__(self, queue, renderer, worker_id, generation_token,
                 heartbeat_seconds=10, artifact_store=None):
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

    def run_once(self):
        job = self.queue.claim(
            self.worker_id, job_type="timeline_render",
            generation_token=self.generation_token,
        )
        if job is None:
            return False

        lost = threading.Event()
        stop = threading.Event()

        def beat():
            while not stop.wait(self.heartbeat_seconds):
                try:
                    self.queue.heartbeat(
                        job["id"], self.worker_id, job["lease_token"],
                        self.generation_token, workspace_id=job["workspace_id"],
                    )
                except Exception:
                    lost.set()
                    return

        heartbeat = threading.Thread(target=beat, daemon=True)
        heartbeat.start()
        staged_path = None
        adopted = False
        try:
            try:
                parameters = inspect.signature(self.renderer).parameters
                accepts_kwargs = any(
                    item.kind == inspect.Parameter.VAR_KEYWORD
                    for item in parameters.values()
                )
                context = {
                    "workspace_id": job["workspace_id"],
                    "principal_id": job["payload"].get("creator_principal_id"),
                }
                context = {
                    key: value for key, value in context.items()
                    if accepts_kwargs or key in parameters
                }
            except (TypeError, ValueError):
                context = {}
            result = self.renderer(
                job["payload"], stop_event=lost, **context
            )
            if isinstance(result, dict):
                staged_path = result.get("staged_path")
            if lost.is_set():
                raise RuntimeError("timeline render lease was lost")
            if self.artifact_store is not None:
                if not isinstance(result, dict) or not staged_path:
                    raise RuntimeError("renderer must return staged_path when artifact adoption is enabled")
                self.artifact_store.adopt(
                    job["id"], self.worker_id, job["lease_token"],
                    self.generation_token, job["workspace_id"],
                    job["payload"]["snapshot_id"],
                    job["payload"]["snapshot_sha256"], staged_path,
                )
                adopted = True
            else:
                self.queue.finish(
                    job["id"], self.worker_id, job["lease_token"],
                    {"render_result": result, "snapshot_id": job["payload"]["snapshot_id"],
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
            if not lost.is_set():
                try:
                    self.queue.fail(
                        job["id"], self.worker_id, job["lease_token"],
                        "timeline_render_failed", str(exc), True,
                        generation_token=self.generation_token,
                        workspace_id=job["workspace_id"],
                    )
                except Exception:
                    pass
            return False
        finally:
            stop.set()
            heartbeat.join(timeout=max(1.0, self.heartbeat_seconds + 1.0))
