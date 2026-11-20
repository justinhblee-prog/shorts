"""Real FFmpeg/ffprobe end-to-end smoke for the integrated lease-fenced renderer.

Run inside the isolated timeline-render-worker image:
    python timeline_render_real_media_smoke.py
"""
from __future__ import annotations

import io
import sqlite3
import subprocess
import tempfile
from pathlib import Path

from queue_store import JobQueue
from workspace_store import WorkspaceStore
from workspace_asset_store import WorkspaceAssetStore
from timeline_render_store import TimelineRenderStore
from render_artifact_store import RenderArtifactStore
from timeline_ffmpeg_renderer import TimelineFFmpegRenderer, workspace_asset_resolver
from timeline_render_worker import TimelineRenderWorker


def main():
    ffmpeg = Path("/usr/bin/ffmpeg")
    ffprobe = Path("/usr/bin/ffprobe")
    for binary in (ffmpeg, ffprobe):
        if not binary.is_absolute() or not binary.is_file():
            raise RuntimeError(f"required local render dependency is missing: {binary}")

    with tempfile.TemporaryDirectory(prefix="nexus-real-render-smoke-") as temp:
        root = Path(temp)
        db_path = root / "smoke.sqlite3"
        source = root / "source.mp4"
        subprocess.run([
            str(ffmpeg), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=blue:s=320x568:r=30",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
            "-t", "2.5", "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(source),
        ], check=True, timeout=45, shell=False)

        queue = JobQueue(db_path, lease_seconds=30)
        workspaces = WorkspaceStore(db_path)
        workspaces.create("Render Smoke", "smoke-reviewer", "ws_render_smoke")
        assets = WorkspaceAssetStore(
            db_path, str(root / "private-assets"), workspaces,
            max_asset_bytes=20_000_000,
        )
        with source.open("rb") as stream:
            asset = assets.register_stream(
                "ws_render_smoke", "smoke-reviewer", stream, "source.mp4"
            )
        # The fixture is generated locally; the scan-state transition is only
        # test setup and does not claim to exercise the ClamAV scanner itself.
        assets.mark_scan_result(
            "ws_render_smoke", "smoke-reviewer", asset["asset_id"], True
        )

        store = TimelineRenderStore(db_path, assets, workspaces, queue)
        staging = root / "staging"
        artifacts_root = root / "artifacts"
        artifacts = RenderArtifactStore(
            queue, staging, artifacts_root,
            max_bytes=20_000_000, ffprobe_path=str(ffprobe),
            require_audio=True, max_duration_ms=10_000,
        )
        edl = {
            "schema": "nexus-edit-decision-list",
            "version": 1,
            "timebase": "milliseconds",
            "clips": [{
                "id": "video", "type": "video", "start_ms": 0,
                "end_ms": 2000, "asset_id": asset["asset_id"],
                "source_in_ms": 0, "source_out_ms": 2000,
            }],
            "audio_tracks": [{
                "id": "music", "asset_id": asset["asset_id"],
                "start_ms": 0, "source_in_ms": 0, "source_out_ms": 2000,
                "gain": 0.3, "fade_in_ms": 100, "fade_out_ms": 100,
            }],
        }
        submitted = store.submit(
            "ws_render_smoke", "smoke-reviewer", edl, "real-media-smoke-0001"
        )

        def resolve_snapshot_creator(workspace_id, payload):
            with sqlite3.connect(db_path, timeout=30) as db:
                row = db.execute("""
                    SELECT creator_principal_id,payload_sha256
                    FROM timeline_edl_snapshots
                    WHERE id=? AND workspace_id=?
                """, (payload.get("snapshot_id"), workspace_id)).fetchone()
            if row is None or row[1] != payload.get("snapshot_sha256"):
                raise RuntimeError("job does not match the immutable snapshot")
            return row[0]

        renderer = TimelineFFmpegRenderer(
            staging, workspace_asset_resolver(assets),
            str(ffmpeg), str(ffprobe),
            width=320, height=568, fps=30,
            max_input_bytes=20_000_000, max_output_bytes=20_000_000,
            timeout_seconds=90,
        )
        generation = queue.register_worker("real-media-smoke-worker")["generation_token"]
        worker = TimelineRenderWorker(
            queue, renderer, "real-media-smoke-worker", generation,
            heartbeat_seconds=5, artifact_store=artifacts,
            principal_resolver=resolve_snapshot_creator,
        )
        if not worker.run_once():
            raise RuntimeError("integrated real-media render worker did not complete the queued EDL")
        job = queue.get(submitted["render_job_id"], workspace_id="ws_render_smoke")
        if job["status"] != "review_pending":
            raise RuntimeError(f"render did not hand off for review: {job['status']}")

        with queue.db() as db:
            row = db.execute(
                "SELECT artifact_id FROM render_artifacts WHERE job_id=?",
                (submitted["render_job_id"],),
            ).fetchone()
        if row is None:
            raise RuntimeError("lease-fenced artifact adoption did not create an artifact row")
        artifact = artifacts.get(row["artifact_id"], "ws_render_smoke")
        if not 1900 <= artifact["duration_ms"] <= 2200:
            raise RuntimeError(f"unexpected rendered duration: {artifact['duration_ms']}")
        if artifact["video_width"] != 320 or artifact["video_height"] != 568:
            raise RuntimeError("rendered video dimensions did not match the configured output")
        if artifact["audio_streams"] < 1:
            raise RuntimeError("audio track was not mixed into the rendered MP4")
        pending = store.list_pending_reviews("ws_render_smoke", "smoke-reviewer")
        if len(pending) != 1 or pending[0]["artifact_id"] != row["artifact_id"]:
            raise RuntimeError("adopted output was not exposed in the pending review queue")

        decision = store.review_decide(
            "ws_render_smoke", "smoke-reviewer", submitted["snapshot_id"],
            "approved", "Integrated real FFmpeg/ffprobe smoke passed",
        )
        if decision["artifact_sha256"] != artifact["artifact_sha256"]:
            raise RuntimeError("review decision was not bound to the adopted artifact hash")
        print(
            "integrated_real_media_render_smoke passed "
            f"duration_ms={artifact['duration_ms']} bytes={artifact['byte_size']} "
            f"artifact_id={artifact['artifact_id']}"
        )


if __name__ == "__main__":
    main()
