"""Lease-fenced consumer for immutable timeline render jobs.

The renderer is injected by the deployment. The worker never treats queue
completion as proof of publication; successful renders enter review_pending.
"""
from __future__ import annotations

import threading

from ffmpeg_edl_renderer import EDLFFmpegRenderer


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
        try:
            render_payload = dict(job["payload"])
            # The queue owns workspace identity; expose it to the trusted
            # asset resolver without changing the immutable stored payload.
            render_payload["workspace_id"] = job["workspace_id"]
            result = self.renderer(render_payload, stop_event=lost)
            if lost.is_set():
                raise RuntimeError("timeline render lease was lost")
            if self.artifact_store is not None:
                if not isinstance(result, dict) or "staged_path" not in result:
                    raise RuntimeError("renderer must return staged_path when artifact adoption is enabled")
                self.artifact_store.adopt(
                    job["id"], self.worker_id, job["lease_token"],
                    self.generation_token, job["workspace_id"],
                    job["payload"]["snapshot_id"],
                    job["payload"]["snapshot_sha256"], result["staged_path"],
                )
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


def create_edl_render_worker(queue, asset_store, worker_id, generation_token,
                             staging_root, ffmpeg_path, artifact_store, *,
                             audio_tracks_resolver=None, ffprobe_path=None, title_font_path=None, width=1080, height=1920,
                             fps=30, max_input_bytes=2_000_000_000,
                             timeout_seconds=3600, heartbeat_seconds=10):
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
    )
