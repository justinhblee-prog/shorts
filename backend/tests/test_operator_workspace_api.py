import os
import tempfile
import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

_TEST_DB = tempfile.TemporaryDirectory()
os.environ.setdefault("NEXUS_DB_PATH", os.path.join(_TEST_DB.name, "app.sqlite3"))

import app as api
from workspace_store import WorkspaceStore, WorkspaceDenied
from production_pipeline import ProductionStore
from queue_store import JobQueue


class OperatorWorkspaceApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = WorkspaceStore(os.path.join(self.temp.name, "workspace.sqlite3"))
        self.store.create("Alice private", "alice", "ws_alice")
        self.store.create("Mallory private", "mallory", "ws_mallory")
        self.store_patch = patch.object(api, "workspace_store", self.store)
        self.store_patch.start()

    def tearDown(self):
        self.store_patch.stop()
        self.temp.cleanup()

    def test_create_owner_is_derived_from_authenticated_token(self):
        with patch.object(api, "require_review_permission", return_value="alice"):
            with self.assertRaises(ValidationError):
                api.WorkspaceCreateInput.model_validate({
                    "name": "Owned", "owner_principal_id": "mallory"
                })
            result = api.create_operator_workspace(api.WorkspaceCreateInput(name="Owned"))
        workspace_id = result["id"]
        self.assertEqual(self.store.require_membership(workspace_id, "alice")["role"], "owner")
        with self.assertRaises(WorkspaceDenied):
            self.store.require_membership(workspace_id, "mallory")

    def test_list_is_scoped_to_authenticated_principal(self):
        with patch.object(api, "require_review_permission", return_value="alice"):
            alice = api.list_operator_workspaces()
        with patch.object(api, "require_review_permission", return_value="bob"):
            bob = api.list_operator_workspaces()
        self.assertEqual([item["id"] for item in alice["workspaces"]], ["ws_alice"])
        self.assertEqual(bob["workspaces"], [])

    def test_only_workspace_admin_can_add_or_revoke_members(self):
        with patch.object(api, "require_review_permission", return_value="alice"):
            added = api.add_operator_workspace_member(
                "ws_alice", api.WorkspaceMemberInput(principal_id="bob", role="viewer")
            )
        self.assertEqual(added["status"], "active")
        with patch.object(api, "require_review_permission", return_value="bob"):
            with self.assertRaises(HTTPException) as denied:
                api.add_operator_workspace_member(
                    "ws_alice", api.WorkspaceMemberInput(principal_id="mallory", role="editor")
                )
        self.assertEqual(denied.exception.status_code, 403)
        with patch.object(api, "require_review_permission", return_value="alice"):
            revoked = api.revoke_operator_workspace_member("ws_alice", "bob")
        self.assertEqual(revoked["status"], "revoked")


    def test_member_list_and_audit_visibility_are_role_scoped(self):
        with patch.object(api, "require_review_permission", return_value="alice"):
            api.add_operator_workspace_member(
                "ws_alice", api.WorkspaceMemberInput(principal_id="bob", role="viewer")
            )
            members = api.list_operator_workspace_members("ws_alice")
            events = api.list_operator_workspace_audit("ws_alice")
        self.assertEqual({m["principal_id"] for m in members["members"]}, {"alice", "bob"})
        self.assertGreaterEqual(len(events["events"]), 2)
        with patch.object(api, "require_review_permission", return_value="bob"):
            visible = api.list_operator_workspace_members("ws_alice")
            self.assertEqual(len(visible["members"]), 2)
            with self.assertRaises(HTTPException) as denied:
                api.list_operator_workspace_audit("ws_alice")
        self.assertEqual(denied.exception.status_code, 403)

    def test_sqlite_edl_mode_ignores_legacy_grants_and_denies_cross_workspace(self):
        payload = {
            "schema": "nexus-edit-decision-list", "version": 1, "timebase": "milliseconds",
            "clips": [{"id": "clip-1", "type": "video", "start_ms": 0, "end_ms": 1000,
                       "asset_id": "asset_1", "source_in_ms": 0, "source_out_ms": 1000}],
        }
        with patch.dict(os.environ, {
            "NEXUS_WORKSPACE_AUTH_MODE": "sqlite",
            "NEXUS_OPERATOR_WORKSPACES_JSON": '{"bob":["ws_alice"]}',
        }):
            with patch.object(api, "require_review_permission", return_value="alice"):
                allowed = api.validate_timeline_edl(
                    payload, x_review_token="alice-token", x_nexus_workspace_id="ws_alice"
                )
            with patch.object(api, "require_review_permission", return_value="bob"):
                with self.assertRaises(HTTPException) as denied:
                    api.validate_timeline_edl(
                        payload, x_review_token="bob-token", x_nexus_workspace_id="ws_alice"
                    )
        self.assertTrue(allowed["valid"])
        self.assertEqual(allowed["workspace_id"], "ws_alice")
        self.assertEqual(denied.exception.status_code, 403)

    def test_production_detail_endpoint_enforces_authenticated_workspace_membership(self):
        db_path = os.path.join(self.temp.name, "production.sqlite3")
        queue = JobQueue(db_path)
        store = ProductionStore(db_path)
        brief = {"brand": "Future Leak", "region": "US",
                 "language": "en", "topic": "AI agents"}
        job = queue.enqueue(
            "short_video_production", brief, workspace_id="ws_alice"
        )
        store.create(job["id"], brief)
        production_patch = patch.object(api, "production_store", store)
        production_patch.start()
        try:
            with patch.dict(os.environ, {"NEXUS_WORKSPACE_AUTH_MODE": "sqlite"}):
                with patch.object(api, "require_review_permission", return_value="alice"):
                    with self.assertRaises(HTTPException) as missing_scope:
                        api.get_production_job(job["id"])
                    self.assertEqual(missing_scope.exception.status_code, 403)
                    visible = api.get_production_job(
                        job["id"], x_nexus_workspace_id="ws_alice"
                    )
                    self.assertEqual(visible["workspace_id"], "ws_alice")
                    with self.assertRaises(HTTPException) as missing_provider_scope:
                        api.get_production_provider_attempts(job["id"])
                    self.assertEqual(missing_provider_scope.exception.status_code, 403)
                    with self.assertRaises(HTTPException) as denied:
                        api.get_production_job(
                            job["id"], x_nexus_workspace_id="ws_mallory"
                        )
                    self.assertEqual(denied.exception.status_code, 403)
        finally:
            production_patch.stop()

    def test_queue_event_and_reconciliation_reads_require_workspace_membership(self):
        db_path = os.path.join(self.temp.name, "queue-read.sqlite3")
        queue = JobQueue(db_path)
        job = queue.enqueue(
            "short_video_production",
            {"brand": "Future Leak", "region": "US",
             "language": "en", "topic": "AI agents"},
            workspace_id="ws_alice",
        )
        queue_patch = patch.object(api, "queue", queue)
        queue_patch.start()
        try:
            with patch.dict(os.environ, {"NEXUS_WORKSPACE_AUTH_MODE": "sqlite"}):
                with patch.object(api, "require_review_permission", return_value="alice"):
                    with self.assertRaises(HTTPException) as missing_scope:
                        api.get_events(job["id"])
                    self.assertEqual(missing_scope.exception.status_code, 403)
                    events = api.get_events(
                        job["id"], x_nexus_workspace_id="ws_alice"
                    )
                    self.assertEqual(events["events"][0]["workspace_id"], "ws_alice")
                    with self.assertRaises(HTTPException) as denied:
                        api.get_events(
                            job["id"], x_nexus_workspace_id="ws_mallory"
                        )
                    self.assertEqual(denied.exception.status_code, 403)
        finally:
            queue_patch.stop()

    def test_production_execution_requires_matching_workspace_scope(self):
        db_path = os.path.join(self.temp.name, "execute-scope.sqlite3")
        queue = JobQueue(db_path)
        job = queue.enqueue(
            "short_video_production",
            {"brand": "Future Leak", "region": "US",
             "language": "en", "topic": "AI agents"},
            workspace_id="ws_alice",
        )
        queue_patch = patch.object(api, "queue", queue)
        queue_patch.start()
        try:
            with patch.dict(os.environ, {"NEXUS_WORKSPACE_AUTH_MODE": "sqlite"}):
                with patch.object(api, "require_review_permission", return_value="alice"):
                    with self.assertRaises(HTTPException) as missing_scope:
                        api.execute_production_job(
                            job["id"],
                            api.ProductionExecute(worker_id="worker-a", lease_token="lease-a"),
                        )
                    self.assertEqual(missing_scope.exception.status_code, 403)
                    with self.assertRaises(HTTPException) as wrong_scope:
                        api.execute_production_job(
                            job["id"],
                            api.ProductionExecute(worker_id="worker-a", lease_token="lease-a"),
                            x_nexus_workspace_id="ws_mallory",
                        )
                    self.assertEqual(wrong_scope.exception.status_code, 403)
                    with self.assertRaises(HTTPException) as valid_scope:
                        api.execute_production_job(
                            job["id"],
                            api.ProductionExecute(worker_id="worker-a", lease_token="lease-a"),
                            x_nexus_workspace_id="ws_alice",
                        )
                    # The valid scope reaches lease validation; this queued job
                    # intentionally has no active worker lease yet.
                    self.assertEqual(valid_scope.exception.status_code, 409)
        finally:
            queue_patch.stop()

    def test_media_staging_requires_workspace_scope_for_tenant_job(self):
        class ScopedProductionStore:
            def get(self, job_id, workspace_id=None):
                if workspace_id not in (None, "ws_alice"):
                    return None
                return {
                    "job_id": job_id, "workspace_id": "ws_alice",
                    "status": "rendered",
                    "artifacts": [{
                        "artifact_type": "video",
                        "artifact_url": "https://renderer.example/video.mp4",
                        "metadata": {},
                    }],
                }
            def artifact(self, *args, **kwargs):
                return None
            def stage(self, *args, **kwargs):
                return None

        missing_media_path = Path(self.temp.name) / "not-created.mp4"
        class FakeStager:
            def staged_path(self, job_id, workspace_id=None):
                return missing_media_path
            def stage(self, job_id, url, workspace_id=None):
                return {"media_path": "opaque/video.mp4", "sha256": "a" * 64,
                        "size_bytes": 100, "content_type": "video/mp4"}

        store_patch = patch.object(api, "production_store", ScopedProductionStore())
        stager_patch = patch.object(api, "media_stager", FakeStager())
        store_patch.start()
        stager_patch.start()
        try:
            with patch.dict(os.environ, {"NEXUS_WORKSPACE_AUTH_MODE": "sqlite"}):
                with patch.object(api, "require_review_permission", return_value="alice"):
                    with self.assertRaises(HTTPException) as missing:
                        api.stage_production_media("job-alice")
                    self.assertEqual(missing.exception.status_code, 403)
                    with self.assertRaises(HTTPException) as wrong:
                        api.stage_production_media(
                            "job-alice", x_nexus_workspace_id="ws_mallory"
                        )
                    self.assertEqual(wrong.exception.status_code, 403)
                    allowed = api.stage_production_media(
                        "job-alice", x_nexus_workspace_id="ws_alice"
                    )
                    self.assertEqual(allowed["media_path"], "opaque/video.mp4")
        finally:
            stager_patch.stop()
            store_patch.stop()

    def test_workspace_media_cleanup_fails_closed_without_scoped_upload_store(self):
        class ScopedProductionStore:
            def get(self, job_id, workspace_id=None):
                return {"job_id": job_id, "workspace_id": "ws_alice"}

        store_patch = patch.object(api, "production_store", ScopedProductionStore())
        store_patch.start()
        try:
            with patch.dict(os.environ, {"NEXUS_WORKSPACE_AUTH_MODE": "sqlite"}):
                with patch.object(api, "require_review_permission", return_value="alice"):
                    with self.assertRaises(HTTPException) as denied:
                        api.cleanup_production_media(
                            "job-alice", x_nexus_workspace_id="ws_alice"
                        )
            self.assertEqual(denied.exception.status_code, 409)
        finally:
            store_patch.stop()

    def test_youtube_and_tiktok_publication_reads_require_parent_workspace(self):
        class ScopedProductionStore:
            def get(self, job_id, workspace_id=None):
                if workspace_id != "ws_alice":
                    return None
                return {"job_id": job_id, "workspace_id": "ws_alice"}

        class FakePublicationStore:
            def get(self, job_id):
                return {"job_id": job_id, "status": "uploaded", "events": []}

        patches = [
            patch.object(api, "production_store", ScopedProductionStore()),
            patch.object(api, "youtube_upload_store", FakePublicationStore()),
            patch.object(api, "tiktok_publish_store", FakePublicationStore()),
        ]
        for item in patches:
            item.start()
        try:
            with patch.dict(os.environ, {"NEXUS_WORKSPACE_AUTH_MODE": "sqlite"}):
                with patch.object(api, "require_review_permission", return_value="alice"):
                    for endpoint, job_id in (
                        (api.get_youtube_upload, "job-youtube"),
                        (api.get_tiktok_publication, "job-tiktok"),
                    ):
                        with self.assertRaises(HTTPException) as missing:
                            endpoint(job_id)
                        self.assertEqual(missing.exception.status_code, 404)
                        with self.assertRaises(HTTPException) as wrong:
                            endpoint(job_id, x_nexus_workspace_id="ws_mallory")
                        self.assertEqual(wrong.exception.status_code, 403)
                        result = endpoint(job_id, x_nexus_workspace_id="ws_alice")
                        self.assertEqual(result["job_id"], job_id)
        finally:
            for item in reversed(patches):
                item.stop()

    def test_youtube_analytics_video_reads_require_parent_workspace(self):
        class ScopedProductionStore:
            def get(self, job_id, workspace_id=None):
                if workspace_id != "ws_alice":
                    return None
                return {"job_id": job_id, "workspace_id": "ws_alice"}

        patches = [
            patch.object(api, "production_store", ScopedProductionStore()),
            patch.object(api.youtube_upload_store, "job_for_video", return_value="job-video"),
            patch.object(api.youtube_analytics_store, "get", return_value={"video_id": "video-1"}),
        ]
        for item in patches:
            item.start()
        try:
            with patch.dict(os.environ, {"NEXUS_WORKSPACE_AUTH_MODE": "sqlite"}):
                with patch.object(api, "require_review_permission", return_value="alice"):
                    with self.assertRaises(HTTPException) as missing:
                        api.get_youtube_analytics("video-1")
                    self.assertEqual(missing.exception.status_code, 404)
                    with self.assertRaises(HTTPException) as wrong:
                        api.get_youtube_analytics(
                            "video-1", x_nexus_workspace_id="ws_mallory"
                        )
                    self.assertEqual(wrong.exception.status_code, 403)
                    result = api.get_youtube_analytics(
                        "video-1", x_nexus_workspace_id="ws_alice"
                    )
                    self.assertEqual(result["video_id"], "video-1")
        finally:
            for item in reversed(patches):
                item.stop()

    def test_worker_v1_credentials_fence_claim_and_lease_to_granted_workspace(self):
        db_path = os.path.join(self.temp.name, "worker-auth.sqlite3")
        queue = JobQueue(db_path)
        brief = {"brand": "Future Leak", "region": "US",
                 "language": "en", "topic": "Isolated worker test"}
        allowed = queue.enqueue("short_video_production", brief, workspace_id="ws_alice")
        denied = queue.enqueue("short_video_production", brief, workspace_id="ws_mallory")
        queue_patch = patch.object(api, "queue", queue)
        queue_patch.start()
        token = "worker-secret-for-api-test-32-bytes-minimum"
        config = json.dumps({
            "worker-alpha": {
                "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
                "workspace_ids": ["ws_alice"],
            }
        })
        try:
            with patch.dict(os.environ, {"NEXUS_WORKER_CREDENTIALS_JSON": config}):
                registered = api.register_worker_v1(
                    api.WorkerRegisterInput(hostname="isolated-worker"),
                    authorization="Bearer " + token,
                )
                generation = registered["generation_token"]
                claimed = api.claim_worker_v1(
                    api.WorkerClaimInput(hostname="isolated-worker",
                                         job_type="short_video_production"),
                    authorization="Bearer " + token,
                    x_nexus_worker_generation=generation,
                )
                self.assertEqual(claimed["job"]["id"], allowed["id"])
                self.assertEqual(claimed["workspace_id"], "ws_alice")
                with self.assertRaises(HTTPException) as cross_workspace:
                    api.heartbeat_worker_v1(
                        denied["id"], api.WorkerLeaseInput(lease_token="not-a-lease"),
                        authorization="Bearer " + token,
                        x_nexus_worker_generation=generation,
                    )
                self.assertEqual(cross_workspace.exception.status_code, 404)
                completed = api.complete_worker_v1(
                    allowed["id"],
                    api.WorkerCompleteInput(
                        lease_token=claimed["job"]["lease_token"],
                        result={"production_status": "review_pending"},
                    ),
                    authorization="Bearer " + token,
                    x_nexus_worker_generation=generation,
                )
                self.assertEqual(completed["status"], "review_pending")
                with self.assertRaises(HTTPException) as legacy_disabled:
                    api.claim(
                        api.Claim(worker_id="worker-alpha", hostname="isolated-worker"),
                        x_review_token="legacy-operator-token",
                    )
                self.assertEqual(legacy_disabled.exception.status_code, 410)
        finally:
            queue_patch.stop()

    def test_unauthenticated_workspace_requests_are_rejected(self):
        with patch.object(api, "require_review_permission",
                          side_effect=HTTPException(401, "Valid review token required")):
            with self.assertRaises(HTTPException) as denied:
                api.list_operator_workspaces()
        self.assertEqual(denied.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
