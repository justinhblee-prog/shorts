import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

_TEST_DB = tempfile.TemporaryDirectory()
os.environ.setdefault("NEXUS_DB_PATH", os.path.join(_TEST_DB.name, "app.sqlite3"))

import app as api
from workspace_store import WorkspaceStore


class OperatorWorkspaceApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = WorkspaceStore(os.path.join(self.temp.name, "workspace.sqlite3"))
        self.store.create("Alice private", "alice", "ws_alice")
        self.store.create("Mallory private", "mallory", "ws_mallory")
        self.store_patch = patch.object(api, "workspace_store", self.store)
        self.store_patch.start()

        def principal(token):
            identities = {"alice-token": "alice", "bob-token": "bob", "mallory-token": "mallory"}
            if token not in identities:
                raise HTTPException(401, "Valid review token required")
            return identities[token]

        def permission(token, required):
            if required != "media.manage":
                raise HTTPException(403, "permission denied")
            return principal(token)

        self.auth_access = patch.object(api, "require_review_access", side_effect=principal)
        self.auth_permission = patch.object(api, "require_review_permission", side_effect=permission)
        self.auth_access.start()
        self.auth_permission.start()
        self.client = TestClient(api.app)

    def tearDown(self):
        self.auth_permission.stop()
        self.auth_access.stop()
        self.store_patch.stop()
        self.temp.cleanup()

    def test_create_owner_is_derived_from_authenticated_token(self):
        response = self.client.post(
            "/api/operator/workspaces",
            headers={"X-Review-Token": "alice-token"},
            json={"name": "Owned", "owner_principal_id": "mallory"},
        )
        self.assertEqual(response.status_code, 422)
        response = self.client.post(
            "/api/operator/workspaces",
            headers={"X-Review-Token": "alice-token"},
            json={"name": "Owned"},
        )
        self.assertEqual(response.status_code, 201)
        workspace_id = response.json()["id"]
        self.assertEqual(self.store.require_membership(workspace_id, "alice")["role"], "owner")
        with self.assertRaises(Exception):
            self.store.require_membership(workspace_id, "mallory")

    def test_list_is_scoped_to_authenticated_principal(self):
        alice = self.client.get("/api/operator/workspaces", headers={"X-Review-Token": "alice-token"})
        bob = self.client.get("/api/operator/workspaces", headers={"X-Review-Token": "bob-token"})
        self.assertEqual(alice.status_code, 200)
        self.assertEqual([item["id"] for item in alice.json()["workspaces"]], ["ws_alice"])
        self.assertEqual(bob.status_code, 200)
        self.assertEqual(bob.json()["workspaces"], [])

    def test_only_workspace_admin_can_add_or_revoke_members(self):
        added = self.client.post(
            "/api/operator/workspaces/ws_alice/members",
            headers={"X-Review-Token": "alice-token"},
            json={"principal_id": "bob", "role": "viewer"},
        )
        self.assertEqual(added.status_code, 200)
        denied = self.client.post(
            "/api/operator/workspaces/ws_alice/members",
            headers={"X-Review-Token": "bob-token"},
            json={"principal_id": "mallory", "role": "editor"},
        )
        self.assertEqual(denied.status_code, 403)
        revoked = self.client.delete(
            "/api/operator/workspaces/ws_alice/members/bob",
            headers={"X-Review-Token": "alice-token"},
        )
        self.assertEqual(revoked.status_code, 200)

    def test_unauthenticated_workspace_requests_are_rejected(self):
        response = self.client.get("/api/operator/workspaces")
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
