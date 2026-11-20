"""Authenticated API -> shared worker -> FFmpeg artifact -> review E2E smoke.

Runs inside the Compose timeline-render-worker container against the live API
service and shared Compose volume. The API scans both a generated clean MP4 and
the standard EICAR anti-malware test fixture using the current ClamAV database.
"""
from __future__ import annotations

import http.cookiejar
import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


API = os.getenv("NEXUS_E2E_API_URL", "http://api:8502").rstrip("/")
DB = os.getenv("NEXUS_DB_PATH", "/app/data/nexus.sqlite3")
PRIVATE_ROOT = os.getenv(
    "NEXUS_PRIVATE_MEDIA_ROOT", "/app/data/media/private-assets"
)
TOKEN_MAP = json.loads(os.environ["NEXUS_REVIEW_CREDENTIALS_JSON"])
ROLE_MAP = json.loads(os.environ["NEXUS_REVIEW_ROLE_MAP_JSON"])
TOKEN = TOKEN_MAP["smoke-reviewer"]
OTHER_TOKEN = TOKEN_MAP["other-smoke-reviewer"]
PRINCIPAL = "smoke-reviewer"
OTHER_PRINCIPAL = "other-smoke-reviewer"


def request(method, path, *, token=None, workspace=None, body=None,
            headers=None, opener=None, expected=200):
    merged = {"Accept": "application/json"}
    if token:
        merged["X-Review-Token"] = token
    if workspace:
        merged["X-Nexus-Workspace-Id"] = workspace
    if headers:
        merged.update(headers)
    data = body
    if isinstance(body, (dict, list)):
        data = json.dumps(body, separators=(",", ":")).encode()
        merged["Content-Type"] = "application/json"
    req = urllib.request.Request(API + path, data=data, headers=merged, method=method)
    client = opener or urllib.request.build_opener()
    try:
        with client.open(req, timeout=15) as response:
            raw = response.read()
            status = response.status
            content_type = response.headers.get("Content-Type", "")
            result = json.loads(raw) if "json" in content_type and raw else raw
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            result = json.loads(raw)
        except (ValueError, TypeError):
            result = raw.decode("utf-8", "replace")
        status = exc.code
    if status != expected:
        raise AssertionError(
            f"{method} {path}: expected HTTP {expected}, got {status}: {result}"
        )
    return result


def wait_for_render(snapshot_id, workspace_id):
    deadline = time.monotonic() + 240
    last = None
    while time.monotonic() < deadline:
        last = request(
            "GET", f"/api/timeline/renders/{snapshot_id}",
            token=TOKEN, workspace=workspace_id,
        )
        state = last.get("status")
        if state == "review_pending" and last.get("rendered"):
            return last
        if state in {"failed", "failed_retriable", "dead_letter"}:
            raise AssertionError(f"render worker failed: {last}")
        time.sleep(2)
    raise TimeoutError(f"render worker did not finish within 240s: {last}")


def main():
    with tempfile.TemporaryDirectory(prefix="nexus-api-e2e-") as temp:
        source = Path(temp) / "api-e2e-source.mp4"
        subprocess.run([
            "/usr/bin/ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
            "-y", "-f", "lavfi", "-i", "color=c=teal:s=320x568:r=30",
            "-f", "lavfi", "-i", "sine=frequency=523:sample_rate=44100",
            "-t", "2.5", "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(source),
        ], check=True, timeout=45, shell=False)
        payload = source.read_bytes()

        # Both workspaces are created through authenticated HTTP APIs.
        workspace = request(
            "POST", "/api/operator/workspaces", token=TOKEN,
            body={"name": "API E2E render workspace"}, expected=201,
        )
        workspace_id = workspace["id"]
        other_workspace = request(
            "POST", "/api/operator/workspaces", token=OTHER_TOKEN,
            body={"name": "API E2E isolation workspace"}, expected=201,
        )
        other_workspace_id = other_workspace["id"]

        uploaded = request(
            "POST", f"/api/workspaces/{workspace_id}/assets",
            token=TOKEN, body=payload, expected=201,
            headers={"X-File-Name": "api-e2e-source.mp4",
                     "Content-Type": "application/octet-stream"},
        )
        asset = uploaded["asset"]
        asset_id = asset["asset_id"]
        assert uploaded["scan_required"] is False
        assert uploaded["renderable"] is True
        assert uploaded["scan_engine"] == "clamav"
        assert asset["scan_status"] == "clean"

        # The standard EICAR test string must be detected by the live database.
        eicar = (
            b"X5O!P%@AP[4\\\\PZX54(P^)7CC)7}$"
            b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
        )
        infected = request(
            "POST", f"/api/workspaces/{workspace_id}/assets",
            token=TOKEN, body=eicar, expected=201,
            headers={"X-File-Name": "eicar-test.txt",
                     "Content-Type": "application/octet-stream"},
        )
        assert infected["scan_required"] is True
        assert infected["renderable"] is False
        assert infected["scan_error"] == "scan_not_cleared"
        assert infected["asset"]["scan_status"] == "pending"

        # A separate principal cannot upload into this workspace.
        request(
            "POST", f"/api/workspaces/{workspace_id}/assets",
            token=OTHER_TOKEN, body=payload, expected=403,
            headers={"X-File-Name": "unauthorized.mp4",
                     "Content-Type": "application/octet-stream"},
        )

        edl = {
            "schema": "nexus-edit-decision-list",
            "version": 1,
            "timebase": "milliseconds",
            "clips": [
                {"id": "title", "type": "title", "start_ms": 0,
                 "end_ms": 500, "text": "Authenticated API E2E"},
                {"id": "video", "type": "video", "start_ms": 500,
                 "end_ms": 2500, "asset_id": asset_id,
                 "source_in_ms": 0, "source_out_ms": 2000},
            ],
        }
        idempotency = "api-e2e-render-20261121-001"

        submitted = request(
            "POST", "/api/timeline/renders", token=TOKEN,
            workspace=workspace_id, body=edl,
            headers={"Idempotency-Key": idempotency}, expected=202,
        )
        replay = request(
            "POST", "/api/timeline/renders", token=TOKEN,
            workspace=workspace_id, body=edl,
            headers={"Idempotency-Key": idempotency}, expected=202,
        )
        assert submitted["snapshot_id"] == replay["snapshot_id"]
        assert submitted["render_job_id"] == replay["render_job_id"]
        assert replay["replayed"] is True

        # The separately running Compose timeline-render-worker must claim this
        # API-created job, execute the pinned FFmpeg binaries and adopt the MP4.
        status = wait_for_render(submitted["snapshot_id"], workspace_id)
        artifact = status["artifact"]
        assert artifact["byte_size"] > 0
        assert artifact["duration_ms"] >= 2400
        assert artifact["video_width"] == 320
        assert artifact["video_height"] == 568
        assert artifact["audio_streams"] >= 1
        assert status["review"]["status"] == "review_pending"

        # Workspace scope prevents a different authenticated principal from
        # learning whether this snapshot exists.
        request(
            "GET", f"/api/timeline/renders/{submitted['snapshot_id']}",
            token=OTHER_TOKEN, workspace=other_workspace_id, expected=404,
        )
        request(
            "GET", f"/api/timeline/renders/{submitted['snapshot_id']}",
            workspace=workspace_id, expected=401,
        )

        decision = request(
            "POST", f"/api/timeline/renders/{submitted['snapshot_id']}/decision",
            token=TOKEN, workspace=workspace_id,
            body={"decision": "approved",
                  "comment": "Authenticated API/worker E2E fixture passed"},
        )
        assert decision["decision"] == "approved"
        assert decision["reviewer_id"] == PRINCIPAL

        # Exercise the short-lived, path-scoped preview cookie, then fetch the
        # actual private MP4 over HTTP without resending the auth header.
        jar = http.cookiejar.CookieJar()
        browser = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(jar)
        )
        session = request(
            "POST",
            f"/api/timeline/artifacts/{artifact['artifact_id']}/preview-session",
            token=TOKEN, workspace=workspace_id, body=b"", opener=browser,
        )
        assert session["expires_in_seconds"] == 120
        preview_url = API + session["preview_url"]
        with browser.open(preview_url, timeout=15) as response:
            preview = response.read()
            assert response.status == 200
            assert response.headers.get_content_type() == "video/mp4"
            assert response.headers.get("Cache-Control") == "private, no-store"
        assert len(preview) > 1024
        assert preview[4:8] == b"ftyp"

        print(
            "authenticated_timeline_render_api_e2e passed "
            f"workspace={workspace_id} snapshot={submitted['snapshot_id']} "
            f"artifact={artifact['artifact_id']} bytes={len(preview)} "
            "worker=compose-service review=approved preview=private"
        )


if __name__ == "__main__":
    main()
