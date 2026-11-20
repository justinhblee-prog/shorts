"""Real FFmpeg MP4 smoke used only inside the disposable Compose test stack."""
import asyncio
import os
import subprocess
import tempfile
from pathlib import Path

from render_asset_store import RenderAssetStore
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
    db_path = os.getenv("NEXUS_DB_PATH", "/app/data/nexus.sqlite3")
    media_dir = os.getenv("NEXUS_MEDIA_DIR", "/app/data/media")
    workspace_id = "compose-render-smoke"
    store = RenderAssetStore(
        db_path, media_dir, scanner=CleanFixtureScanner(), scan_enabled=True,
        max_video_bytes=128 * 1024 * 1024,
    )
    asset = None
    output = None
    with tempfile.TemporaryDirectory(prefix="nexus-render-smoke-") as temp:
        source = Path(temp) / "source.mp4"
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
        try:
            asset = asyncio.run(store.register_stream(
                workspace_id, "compose-render-smoke", "video/mp4", "fixture.mp4",
                file_chunks(source), declared_length=source.stat().st_size,
            ))
            paths = store.resolve_asset_paths(
                workspace_id, [asset["asset_id"]], expected_asset_type="video"
            )
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
            renderer = TimelineRenderer(
                media_root=media_dir,
                timeout_seconds=60,
                max_cpu_seconds=60,
                max_output_bytes=64 * 1024 * 1024,
                max_asset_bytes=128 * 1024 * 1024,
                max_total_asset_bytes=128 * 1024 * 1024,
            )
            result = renderer.render(
                edl, paths,
                output_dir=store.workspace_render_output_dir(workspace_id),
            )
            output = Path(media_dir) / result["media_path"]
            assert output.is_file()
            assert result["status"] == "rendered_unreviewed"
            assert result["width"] == 1080 and result["height"] == 1920
            assert 0.5 <= result["duration_seconds"] <= 1.5
            print(
                "render_integration_smoke passed "
                f"render_id={result['render_id']} size_bytes={result['size_bytes']} "
                f"sha256={result['sha256']}"
            )
        finally:
            if output is not None:
                output.unlink(missing_ok=True)
            if asset is not None:
                with store.db() as connection:
                    connection.execute(
                        "DELETE FROM render_assets WHERE asset_id=? AND workspace_id=?",
                        (asset["asset_id"], workspace_id),
                    )
                for path in store.resolve_asset_paths.__self__.media_root.glob("never-match"):
                    path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
