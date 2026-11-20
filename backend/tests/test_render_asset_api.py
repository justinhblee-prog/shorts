import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from starlette.requests import Request

import app as app_module
from timeline_edl import SCHEMA


class RenderAssetApiTests(unittest.TestCase):
    def request(self, content_type="video/mp4", body=b"0000ftypisomfixture"):
        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}
        return Request({
            "type": "http",
            "method": "POST",
            "path": "/api/render/assets",
            "headers": [
                (b"content-type", content_type.encode("ascii")),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
            "query_string": b"",
        }, receive)

    def test_upload_requires_explicit_authenticated_workspace(self):
        request = self.request()
        with (
            patch.object(app_module, "require_review_permission", return_value="operator-a"),
            patch.object(app_module, "resolve_operator_workspace_scope", return_value=None),
            patch.object(app_module.render_asset_store, "register_stream", new_callable=AsyncMock) as register,
        ):
            with self.assertRaises(HTTPException) as denied:
                asyncio.run(app_module.upload_render_asset(
                    request, x_asset_name="clip.mp4",
                    x_review_token="token", x_nexus_workspace_id=None,
                ))
        self.assertEqual(denied.exception.status_code, 403)
        register.assert_not_awaited()

    def test_upload_uses_token_identity_and_resolved_workspace(self):
        request = self.request()
        expected = {"asset_id": "a" * 32, "render_ready": True}
        with (
            patch.object(app_module, "require_review_permission", return_value="operator-a") as auth,
            patch.object(app_module, "resolve_operator_workspace_scope", return_value="workspace-a") as scope,
            patch.object(app_module.render_asset_store, "register_stream",
                         new_callable=AsyncMock, return_value=expected) as register,
        ):
            result = asyncio.run(app_module.upload_render_asset(
                request, x_asset_name="clip.mp4",
                x_review_token="token", x_nexus_workspace_id="workspace-a",
            ))
        self.assertEqual(result, expected)
        auth.assert_called_once_with("token", "media.manage")
        scope.assert_called_once_with("operator-a", "workspace-a")
        args = register.await_args.args
        self.assertEqual(args[:3], ("workspace-a", "operator-a", "video/mp4"))
        self.assertEqual(args[3], "clip.mp4")
        self.assertEqual(args[5], str(len(b"0000ftypisomfixture")))

    def test_edl_validation_resolves_asset_ids_in_authenticated_workspace(self):
        edl = {
            "schema": SCHEMA, "version": 1, "timebase": "milliseconds",
            "clips": [{
                "id": "clip-1", "type": "video", "start_ms": 0, "end_ms": 1000,
                "asset_id": "a" * 32, "source_in_ms": 0, "source_out_ms": 1000,
            }],
        }
        with (
            patch.object(app_module, "require_review_permission", return_value="operator-a"),
            patch.object(app_module, "resolve_operator_workspace_scope", return_value="workspace-a"),
            patch.object(app_module.render_asset_store, "resolve_asset_paths",
                         return_value={"a" * 32: "/private/internal/path"}),
        ) as resolve:
            result = app_module.validate_render_edl(
                edl, x_review_token="token", x_nexus_workspace_id="workspace-a"
            )
        self.assertEqual(result["status"], "validated")
        self.assertFalse(result["render_enabled"])
        resolve.assert_called_once_with("workspace-a", ["a" * 32])

    def test_edl_validation_does_not_leak_internal_paths(self):
        edl = {
            "schema": SCHEMA, "version": 1, "timebase": "milliseconds",
            "clips": [{
                "id": "clip-1", "type": "video", "start_ms": 0, "end_ms": 1000,
                "asset_id": "a" * 32, "source_in_ms": 0, "source_out_ms": 1000,
            }],
        }
        with (
            patch.object(app_module, "require_review_permission", return_value="operator-a"),
            patch.object(app_module, "resolve_operator_workspace_scope", return_value="workspace-a"),
            patch.object(app_module.render_asset_store, "resolve_asset_paths",
                         return_value={"a" * 32: "/private/internal/path"}),
        ):
            result = app_module.validate_render_edl(
                edl, x_review_token="token", x_nexus_workspace_id="workspace-a"
            )
        self.assertNotIn("/private/internal/path", str(result))


if __name__ == "__main__":
    unittest.main()
