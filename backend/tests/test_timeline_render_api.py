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
        self.scan_calls = []

    def scan_pending_asset(self, workspace_id, asset_id, scanner):
        self.scan_calls.append((workspace_id, asset_id, scanner))
        return {
            "asset_id": asset_id, "workspace_id": workspace_id,
            "scan_status": "clean", "status": "active",
        }

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
        with patch.dict("os.environ", {"NEXUS_MEDIA_SCAN_ENABLED": "false"}), \
             patch.object(api, "require_review_permission", return_value="alice"), \
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
        with patch.dict("os.environ", {"NEXUS_MEDIA_SCAN_ENABLED": "false"}), \
             patch.object(api, "require_review_permission", return_value="alice"), \
             patch.object(api, "resolve_workspace_access", return_value="ws_studio"), \
             patch.object(api, "asset_store", store):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(api.upload_workspace_asset(
                    "ws_studio", make_request(b"x" * 1025),
                    "large.mp4", "review-token",
                ))
        self.assertEqual(raised.exception.status_code, 413)
        self.assertIsNone(store.registered)


    def test_enabled_clamav_scan_promotes_asset_only_after_clean_result(self):
        store = FakeAssetStore()
        with patch.dict("os.environ", {"NEXUS_MEDIA_SCAN_ENABLED": "true"}), \
             patch.object(api, "require_review_permission", return_value="alice"), \
             patch.object(api, "resolve_workspace_access", return_value="ws_studio"), \
             patch.object(api, "asset_store", store), \
             patch.object(api, "ClamAVScanner", return_value=object()):
            result = asyncio.run(api.upload_workspace_asset(
                "ws_studio", make_request(b"clean media"),
                "clean.mp4", "review-token",
            ))
        self.assertTrue(result["renderable"])
        self.assertEqual(result["asset"]["scan_status"], "clean")
        self.assertEqual(len(store.scan_calls), 1)

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


    def test_status_exposes_preview_only_after_artifact_adoption(self):
        class FakeDB:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def execute(self, *args):
                return self
            def fetchone(self):
                return {"artifact_id": "rart_" + "d" * 32}

        class FakeQueue:
            def db(self): return FakeDB()
            def get(self, job_id, workspace_id=None):
                return {"status": "review_pending", "error_code": None,
                        "error_message": None, "created_at": "created",
                        "updated_at": "updated"}

        class FakeSnapshotStore:
            def get(self, workspace_id, principal_id, snapshot_id):
                return {"snapshot_id": snapshot_id, "render_job_id": "job_fixture",
                        "payload_sha256": "c" * 64}
            def review_status(self, workspace_id, principal_id, snapshot_id):
                return {"status": "review_pending", "decision": None}

        class FakeArtifactStore:
            def get(self, artifact_id, workspace_id):
                return {"artifact_id": artifact_id, "byte_size": 1234,
                        "duration_ms": 5000, "video_width": 1080,
                        "video_height": 1920, "audio_streams": 1}

        with patch.object(api, "require_review_permission", return_value="alice"), \
             patch.object(api, "resolve_workspace_access", return_value="ws_studio"), \
             patch.object(api, "timeline_render_store", FakeSnapshotStore()), \
             patch.object(api, "queue", FakeQueue()), \
             patch.object(api, "render_artifact_store", FakeArtifactStore()):
            result = api.get_timeline_render_status(
                "edl_" + "b" * 32, "review-token", "ws_studio"
            )
        self.assertEqual(result["status"], "review_pending")
        self.assertTrue(result["rendered"])
        self.assertEqual(result["artifact"]["duration_ms"], 5000)
        self.assertIn("/preview", result["artifact"]["preview_url"])

    def test_preview_resolves_only_workspace_owned_artifact(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as temp:
            artifact_id = "rart_" + "e" * 32
            media = Path(temp) / (artifact_id + ".mp4")
            media.write_bytes(b"private-preview")
            class FakeArtifactStore:
                artifact_root = Path(temp)
                def get(self, requested_id, workspace_id):
                    self.assertion = (requested_id, workspace_id)
                    return {"storage_key": media.name}
            store = FakeArtifactStore()
            with patch.object(api, "require_review_permission", return_value="alice"), \
                 patch.object(api, "resolve_workspace_access", return_value="ws_studio"), \
                 patch.object(api, "render_artifact_store", store):
                request = Request({
                    "type": "http", "asgi": {"version": "3.0"},
                    "http_version": "1.1", "method": "GET", "scheme": "https",
                    "path": "/preview", "raw_path": b"/preview",
                    "query_string": b"", "headers": [],
                    "server": ("test", 443), "client": ("test", 1234),
                })
                response = api.preview_timeline_artifact(
                    artifact_id, request, "ws_studio", "review-token", None
                )
            self.assertEqual(Path(response.path), media)
            self.assertEqual(store.assertion, (artifact_id, "ws_studio"))
            self.assertEqual(response.media_type, "video/mp4")


    def test_review_decision_uses_authenticated_reviewer_identity(self):
        class FakeSnapshotStore:
            def __init__(self): self.call = None
            def review_decide(self, workspace_id, reviewer_id, snapshot_id, decision, comment):
                self.call = (workspace_id, reviewer_id, snapshot_id, decision, comment)
                return {"decision": decision, "reviewer_id": reviewer_id}
        store = FakeSnapshotStore()
        body = api.TimelineRenderDecisionInput(
            decision="approved", comment="Verified output"
        )
        with (
            patch.object(api, "require_review_permission", return_value="reviewer-1"),
            patch.object(api, "resolve_workspace_access", return_value="ws_studio"),
            patch.object(api, "timeline_render_store", store),
        ):
            result = api.decide_timeline_render(
                "edl_" + "b" * 32, body, "review-token", "ws_studio"
            )
        self.assertEqual(store.call, (
            "ws_studio", "reviewer-1", "edl_" + "b" * 32,
            "approved", "Verified output",
        ))
        self.assertEqual(result["reviewer_id"], "reviewer-1")


    def test_preview_session_sets_short_lived_path_scoped_httponly_cookie(self):
        from fastapi import Response
        artifact_id = "rart_" + "a" * 32
        class FakeArtifactStore:
            def get(self, requested_id, workspace_id):
                self.assertion = (requested_id, workspace_id)
                return {"artifact_id": requested_id}
        store = FakeArtifactStore()
        request = Request({
            "type": "http", "asgi": {"version": "3.0"},
            "http_version": "1.1", "method": "POST", "scheme": "https",
            "path": "/preview-session", "raw_path": b"/preview-session",
            "query_string": b"", "headers": [], "server": ("test", 443),
            "client": ("test", 1234),
        })
        response = Response()
        with (
            patch.object(api, "require_review_permission", return_value="alice"),
            patch.object(api, "resolve_workspace_access", return_value="ws_studio"),
            patch.object(api, "render_artifact_store", store),
        ):
            result = api.create_timeline_preview_session(
                artifact_id, request, response, "review-secret", "ws_studio"
            )
        self.assertEqual(store.assertion, (artifact_id, "ws_studio"))
        self.assertEqual(result["expires_in_seconds"], 120)
        self.assertIn("workspace_id=ws_studio", result["preview_url"])
        cookie = response.headers["set-cookie"].lower()
        self.assertIn("httponly", cookie)
        self.assertIn("secure", cookie)
        self.assertIn("samesite=strict", cookie)
        self.assertIn("max-age=120", cookie)
        self.assertIn(f"/api/timeline/artifacts/{artifact_id}/preview", cookie)

    def test_preview_uses_scoped_cookie_for_native_video_requests(self):
        import tempfile
        from pathlib import Path
        artifact_id = "rart_" + "b" * 32
        with tempfile.TemporaryDirectory() as temp:
            media = Path(temp) / (artifact_id + ".mp4")
            media.write_bytes(b"private-preview")
            class FakeArtifactStore:
                artifact_root = Path(temp)
                def get(self, requested_id, workspace_id):
                    return {"storage_key": media.name}
            store = FakeArtifactStore()
            cookie_name = "nexus_preview_" + artifact_id
            request = Request({
                "type": "http", "asgi": {"version": "3.0"},
                "http_version": "1.1", "method": "GET", "scheme": "https",
                "path": "/preview", "raw_path": b"/preview",
                "query_string": b"workspace_id=ws_studio",
                "headers": [(b"cookie", f"{cookie_name}=review-secret".encode())],
                "server": ("test", 443), "client": ("test", 1234),
            })
            with (
                patch.object(api, "require_review_permission", return_value="alice") as auth,
                patch.object(api, "resolve_workspace_access", return_value="ws_studio"),
                patch.object(api, "render_artifact_store", store),
            ):
                response = api.preview_timeline_artifact(
                    artifact_id, request, "ws_studio", None, None
                )
            auth.assert_called_once_with("review-secret", "review.read")
            self.assertEqual(Path(response.path), media)

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
