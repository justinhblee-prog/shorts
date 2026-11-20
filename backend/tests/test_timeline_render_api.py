import asyncio
import io
import unittest
from unittest.mock import patch

from fastapi import HTTPException, Request

import app as api


class FakeAssetStore:
    max_asset_bytes = 1024

    def __init__(self):
        self.registered = None

    def register_stream(self, workspace_id, principal_id, stream, original_name):
        payload = stream.read()
        self.registered = (workspace_id, principal_id, payload, original_name)
        return {
            "asset_id": "asset_" + "a" * 32,
            "workspace_id": workspace_id,
            "owner_principal_id": principal_id,
            "original_name": original_name,
            "size_bytes": len(payload),
            "scan_status": "pending",
            "status": "active",
        }


class FakeTimelineStore:
    def __init__(self):
        self.call = None

    def submit(self, workspace_id, principal_id, payload, idempotency_key):
        self.call = (workspace_id, principal_id, payload, idempotency_key)
        return {
            "snapshot_id": "edl_" + "b" * 32,
            "workspace_id": workspace_id,
            "render_job_id": "job_fixture",
            "payload_sha256": "c" * 64,
            "status": "queued",
            "replayed": False,
        }


def make_request(body):
    events = [{"type": "http.request", "body": body, "more_body": False}]

    async def receive():
        if events:
            return events.pop(0)
        return {"type": "http.disconnect"}

    return Request({
        "type": "http", "asgi": {"version": "3.0"},
        "http_version": "1.1", "method": "POST",
        "scheme": "http", "path": "/upload", "raw_path": b"/upload",
        "query_string": b"", "headers": [], "server": ("test", 80),
        "client": ("test", 1234),
    }, receive)


class TimelineRenderApiTests(unittest.TestCase):
    def test_upload_streams_private_asset_into_quarantine(self):
        store = FakeAssetStore()
        with patch.object(api, "require_review_permission", return_value="alice"), \
             patch.object(api, "resolve_workspace_access", return_value="ws_studio"), \
             patch.object(api, "asset_store", store):
            result = asyncio.run(api.upload_workspace_asset(
                "ws_studio", make_request(b"private media"),
                "sample.mp4", "review-token",
            ))
        self.assertTrue(result["scan_required"])
        self.assertFalse(result["renderable"])
        self.assertEqual(result["asset"]["scan_status"], "pending")
        self.assertEqual(store.registered, (
            "ws_studio", "alice", b"private media", "sample.mp4"
        ))

    def test_upload_rejects_oversized_stream_before_registration(self):
        store = FakeAssetStore()
        with patch.object(api, "require_review_permission", return_value="alice"), \
             patch.object(api, "resolve_workspace_access", return_value="ws_studio"), \
             patch.object(api, "asset_store", store):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(api.upload_workspace_asset(
                    "ws_studio", make_request(b"x" * 1025),
                    "large.mp4", "review-token",
                ))
        self.assertEqual(raised.exception.status_code, 413)
        self.assertIsNone(store.registered)

    def test_render_submission_is_workspace_scoped_and_idempotent(self):
        store = FakeTimelineStore()
        payload = {"schema": "fixture", "clips": []}
        with patch.object(api, "require_review_permission", return_value="alice"), \
             patch.object(api, "resolve_workspace_access", return_value="ws_studio"), \
             patch.object(api, "timeline_render_store", store):
            result = api.submit_timeline_render(
                payload, "render-attempt-0001", "review-token", "ws_studio"
            )
        self.assertEqual(store.call, (
            "ws_studio", "alice", payload, "render-attempt-0001"
        ))
        self.assertEqual(result["status"], "queued")
        self.assertFalse(result["rendered"])
        self.assertEqual(result["status_url"], f"/api/timeline/renders/{result['snapshot_id']}")

    def test_render_submission_denies_non_member_before_queueing(self):
        store = FakeTimelineStore()
        with patch.object(api, "require_review_permission", return_value="mallory"), \
             patch.object(api, "resolve_workspace_access", side_effect=PermissionError), \
             patch.object(api, "timeline_render_store", store):
            with self.assertRaises(HTTPException) as raised:
                api.submit_timeline_render(
                    {"schema": "fixture"}, "render-attempt-0002",
                    "review-token", "ws_studio",
                )
        self.assertEqual(raised.exception.status_code, 403)
        self.assertIsNone(store.call)


if __name__ == "__main__":
    unittest.main()
