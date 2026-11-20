"""Real FFmpeg + durable queue integration smoke in a disposable database."""
import asyncio
import tempfile
import subprocess
from pathlib import Path

import render_worker
from queue_store import JobQueue
from render_asset_store import RenderAssetStore
from render_output_store import RenderOutputStore
from timeline_edl import SCHEMA
from timeline_renderer import TimelineRenderer


class CleanFixtureScanner:
    def scan(self, path):
        return {"status": "clean", "engine": "compose-smoke-fixture"}


async def file_chunks(path):
    with Path(path).open("rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            yield block


def main():
    with tempfile.TemporaryDirectory(prefix="nexus-render-worker-smoke-") as temp:
        root = Path(temp)
        db_path = root / "nexus.sqlite3"
        media_dir = root / "media"
        queue = JobQueue(db_path, lease_seconds=60)
        asset_store = RenderAssetStore(
            db_path, media_dir, scanner=CleanFixtureScanner(), scan_enabled=True,
            max_video_bytes=128 * 1024 * 1024,
        )
        output_store = RenderOutputStore(db_path, media_dir)
        worker_id = "compose-render-smoke-worker"
        generation = queue.register_worker(worker_id, "compose-smoke")["generation_token"]
        renderer = TimelineRenderer(
            media_root=media_dir,
            timeout_seconds=60,
            max_cpu_seconds=60,
            max_output_bytes=64 * 1024 * 1024,
            max_asset_bytes=128 * 1024 * 1024,
            max_total_asset_bytes=128 * 1024 * 1024,
        )

        source = root / "source.mp4"
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "testsrc2=duration=1:size=320x240:rate=30",
                "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", "-f", "mp4", str(source),
            ],
            check=True, shell=False, timeout=30,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        asset = asyncio.run(asset_store.register_stream(
            "compose-render-smoke", "compose-render-smoke", "video/mp4", "fixture.mp4",
            file_chunks(source), declared_length=source.stat().st_size,
        ))
        edl = {
            "schema": SCHEMA,
            "version": 1,
            "timebase": "milliseconds",
            "clips": [{
                "id": "fixture-clip",
                "type": "video",
                "start_ms": 0,
                "end_ms": 1000,
                "asset_id": asset["asset_id"],
                "source_in_ms": 0,
                "source_out_ms": 1000,
            }],
        }
        job = queue.enqueue(
            "timeline_render",
            {"edl": edl, "audio_asset_id": None},
            channel_name="render",
            max_attempts=1,
            workspace_id="compose-render-smoke",
        )

        # Exercise the same worker entrypoint used by the long-running Compose service.
        render_worker.queue = queue
        render_worker.asset_store = asset_store
        render_worker.output_store = output_store
        render_worker.renderer = renderer
        render_worker.WORKER_ID = worker_id
        render_worker.WORKER_GENERATION_TOKEN = generation
        render_worker.HEARTBEAT_SECONDS = 3600
        render_worker.stopping.clear()
        assert render_worker.run_once() is True

        completed = queue.get(job["id"], workspace_id="compose-render-smoke")
        assert completed["status"] == "review_pending", (
            completed["status"], completed.get("error_code"), completed.get("error_message")
        )
        output = output_store.get_reviewable(job["id"], "compose-render-smoke")
        assert output["path"].is_file()
        assert output["review_status"] == "pending"
        assert output["width"] == 1080 and output["height"] == 1920
        assert 0.5 <= output["duration_seconds"] <= 1.5
        print(
            "render_integration_smoke passed "
            f"job_id={job['id']} render_id={output['render_id']} "
            f"size_bytes={output['size_bytes']} sha256={output['sha256']}"
        )


if __name__ == "__main__":
    main()
