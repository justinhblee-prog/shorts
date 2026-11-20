import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

_TEST_DB = tempfile.TemporaryDirectory()
os.environ.setdefault("NEXUS_DB_PATH", os.path.join(_TEST_DB.name, "app.sqlite3"))

import app as api
from workspace_store import WorkspaceStore, WorkspaceDenied


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

    def test_unauthenticated_workspace_requests_are_rejected(self):
        with patch.object(api, "require_review_permission",
                          side_effect=HTTPException(401, "Valid review token required")):
            with self.assertRaises(HTTPException) as denied:
                api.list_operator_workspaces()
        self.assertEqual(denied.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
