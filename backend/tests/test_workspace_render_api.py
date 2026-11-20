import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

import app as app_module


class WorkspaceRenderApiTests(unittest.TestCase):
    def request(self, body=b"media", content_type="application/octet-stream"):
        sent = False

        async def receive():
            nonlocal sent
            if not sent:
                sent = True
                return {
                    "type": "http.request",
                    "body": body,
                    "more_body": False,
                }
            return {"type": "http.disconnect"}

        return Request({
            "type": "http", "method": "POST",
            "path": "/api/operator/workspaces/ws_studio/assets",
            "headers": [
                (b"content-type", content_type.encode("ascii")),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("testclient", 12345),
            "scheme": "http",
        }, receive)

    def test_upload_stream_is_bounded_and_returns_quarantine_state(self):
        request = self.request(b"video-fixture")
        captured = {}

        def register(workspace_id, principal_id, stream, filename):
            captured["bytes"] = stream.read()
            captured["args"] = (workspace_id, principal_id, filename)
            return {
                "asset_id": "asset_" + "a" * 32,
                "original_name": filename,
                "size_bytes": len(captured["bytes"]),
                "sha256": "b" * 64,
            }

        with (
            patch.object(app_module, "require_review_permission", return_value="alice"),
            patch.object(app_module, "resolve_operator_workspace_scope", return_value="ws_studio"),
            patch.object(app_module.workspace_asset_store, "max_asset_bytes", 100),
            patch.object(app_module.workspace_asset_store, "register_stream", side_effect=register),
            patch.object(app_module, "_scan_workspace_asset", return_value={
                "scan_status": "pending", "scanner_status": "disabled",
                "media_metadata": None,
            }),
        ):
            result = asyncio.run(app_module.upload_workspace_asset(
                "ws_studio", request, "clip.mp4", "operator-token"
            ))
        self.assertEqual(captured["bytes"], b"video-fixture")
        self.assertEqual(captured["args"], ("ws_studio", "alice", "clip.mp4"))
        self.assertEqual(result["scan_status"], "pending")
        self.assertFalse(result["renderable"])

    def test_upload_rejects_oversized_body_and_unsupported_media(self):
        request = self.request(b"four")
        with (
            patch.object(app_module, "require_review_permission", return_value="alice"),
            patch.object(app_module, "resolve_operator_workspace_scope", return_value="ws_studio"),
            patch.object(app_module.workspace_asset_store, "max_asset_bytes", 3),
            patch.object(app_module.workspace_asset_store, "register_stream") as register,
        ):
            with self.assertRaises(HTTPException) as oversized:
                asyncio.run(app_module.upload_workspace_asset(
                    "ws_studio", request, "clip.mp4", "operator-token"
                ))
            self.assertEqual(oversized.exception.status_code, 413)
            register.assert_not_called()

        with (
            patch.object(app_module, "require_review_permission", return_value="alice"),
            patch.object(app_module, "resolve_operator_workspace_scope", return_value="ws_studio"),
        ):
            with self.assertRaises(HTTPException) as unsupported:
                asyncio.run(app_module.upload_workspace_asset(
                    "ws_studio", self.request(), "payload.exe", "operator-token"
                ))
            self.assertEqual(unsupported.exception.status_code, 415)

    def test_scan_helper_fails_closed_and_only_cleans_after_both_checks(self):
        probe = {
            "duration_ms": 12000, "byte_size": 10,
            "has_video": True, "has_audio": True,
            "video_streams": [{"codec": "h264", "width": 640, "height": 360}],
            "audio_streams": [{"codec": "aac", "sample_rate": 48000, "channels": 2}],
        }
        verified = {"scan_status": "clean", "media_metadata": probe}
        with (
            patch.object(app_module.media_stager, "scan_enabled", True),
            patch.object(app_module.workspace_asset_store, "path_for_scan", return_value=Path("/tmp/source.mp4")),
            patch.object(app_module, "ClamAVScanner") as scanner_cls,
            patch.object(app_module, "_configured_ffprobe_binary", return_value=Path("/usr/bin/ffprobe")),
            patch.object(app_module, "probe_source_media", return_value=probe),
            patch.object(app_module.workspace_asset_store, "mark_scan_result", return_value=verified) as mark,
        ):
            scanner_cls.return_value.scan.return_value = None
            result = app_module._scan_workspace_asset("ws_studio", "alice", "asset_" + "a" * 32)
        self.assertEqual(result["scan_status"], "clean")
        mark.assert_called_once()
        self.assertTrue(mark.call_args.kwargs["scanner_verified"])

        with (
            patch.object(app_module.media_stager, "scan_enabled", True),
            patch.object(app_module.workspace_asset_store, "path_for_scan", return_value=Path("/tmp/source.mp4")),
            patch.object(app_module, "ClamAVScanner") as scanner_cls,
            patch.object(app_module.workspace_asset_store, "mark_scan_result") as mark,
        ):
            from media_scanner import MediaScanError
            scanner_cls.return_value.scan.side_effect = MediaScanError("scanner unavailable")
            result = app_module._scan_workspace_asset("ws_studio", "alice", "asset_" + "a" * 32)
        self.assertEqual(result["scan_status"], "pending")
        mark.assert_not_called()

    def test_render_submission_and_status_routes_do_not_expose_lease_secrets(self):
        body = app_module.TimelineRenderSubmitInput(
            edl={"schema": "nexus-edit-decision-list", "version": 1,
                 "timebase": "milliseconds", "clips": []},
            idempotency_key="render-key-0001",
        )
        with (
            patch.object(app_module, "require_review_permission", return_value="alice"),
            patch.object(app_module, "resolve_operator_workspace_scope", return_value="ws_studio"),
            patch.object(app_module.timeline_render_store, "submit", return_value={
                "id": "edl_" + "a" * 32, "render_job_id": "job-1",
                "payload_sha256": "b" * 64, "replayed": False,
            }) as submit,
        ):
            result = app_module.submit_workspace_render("ws_studio", body, "operator-token")
        self.assertEqual(result["render_job_id"], "job-1")
        submit.assert_called_once()

        with (
            patch.object(app_module, "require_review_permission", return_value="alice"),
            patch.object(app_module, "resolve_operator_workspace_scope", return_value="ws_studio"),
            patch.object(app_module.timeline_render_store, "get", return_value={
                "id": "edl_" + "a" * 32, "render_job_id": "job-1",
                "payload_sha256": "b" * 64,
            }),
            patch.object(app_module.queue, "get", return_value={
                "status": "review_pending", "attempt": 1, "max_attempts": 3,
                "created_at": "created", "updated_at": "updated",
                "completed_at": "done", "lease_token": "never-return-this",
            }),
        ):
            status = app_module.get_workspace_render(
                "ws_studio", "edl_" + "a" * 32, "operator-token"
            )
        self.assertEqual(status["status"], "review_pending")
        self.assertNotIn("lease_token", status)

    def test_review_artifact_list_and_download_are_workspace_scoped(self):
        with (
            patch.object(app_module, "require_review_permission", return_value="reviewer"),
            patch.object(app_module, "resolve_operator_workspace_scope", return_value="ws_studio"),
            patch.object(app_module.render_artifact_store, "list_pending", return_value=[
                {"artifact_id": "rart_" + "a" * 32, "status": "review_pending"}
            ]),
        ):
            listing = app_module.list_workspace_render_artifacts("ws_studio", 10, "token")
        self.assertEqual(len(listing["items"]), 1)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "artifact.mp4"
            artifact.write_bytes(b"verified-video")
            with (
                patch.object(app_module, "require_review_permission", return_value="reviewer"),
                patch.object(app_module, "resolve_operator_workspace_scope", return_value="ws_studio"),
                patch.object(app_module.render_artifact_store, "get", return_value={
                    "status": "review_pending", "media_suffix": ".mp4",
                    "storage_key": "artifact.mp4",
                }),
                patch.object(app_module.render_artifact_store, "artifact_root", root),
            ):
                response = app_module.download_workspace_render_artifact(
                    "ws_studio", "rart_" + "a" * 32, "token"
                )
            self.assertEqual(Path(response.path), artifact)
            self.assertEqual(response.media_type, "video/mp4")


if __name__ == "__main__":
    unittest.main()
