import unittest
import json
from workspace_access import WorkspaceAccessConfigurationError, resolve_workspace_membership, resolve_workspace_access
from workspace_store import WorkspaceStore

class WorkspaceAccessTests(unittest.TestCase):
    def test_explicit_membership(self):
        raw = json.dumps({"alice": ["team-a", "team-b"]})
        self.assertEqual(resolve_workspace_membership("alice", "team-a", memberships_json=raw), "team-a")

    def test_cross_workspace_and_unknown_operator_denied(self):
        raw = json.dumps({"alice": ["team-a"], "bob": ["team-b"]})
        for principal, workspace in (("alice", "team-b"), ("mallory", "team-a")):
            with self.subTest(principal=principal), self.assertRaises(PermissionError):
                resolve_workspace_membership(principal, workspace, memberships_json=raw)

    def test_missing_or_empty_configuration_fails_closed(self):
        for raw, workspace in (("", "team-a"), (None, "team-a"), ("{}", "team-a"),
                               ('{"alice":["team-a"]}', None)):
            with self.subTest(raw=raw, workspace=workspace), self.assertRaises(WorkspaceAccessConfigurationError):
                resolve_workspace_membership("alice", workspace, memberships_json=raw)

    def test_wildcard_and_malformed_membership_rejected(self):
        for raw in ('{"alice":["*"]}', '{"alice":"team-a"}',
                    '{"alice":["team-a","team-a"]}', '{" alice":["team-a"]}'):
            with self.subTest(raw=raw), self.assertRaises(WorkspaceAccessConfigurationError):
                resolve_workspace_membership("alice", "team-a", memberships_json=raw)


    def test_sqlite_mode_uses_durable_membership_without_legacy_fallback(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as directory:
            store = WorkspaceStore(os.path.join(directory, "db.sqlite3"))
            store.create("Studio", "alice", "ws_studio")
            self.assertEqual(resolve_workspace_access("alice", "ws_studio", mode="sqlite", store=store), "ws_studio")
            with self.assertRaises(PermissionError):
                resolve_workspace_access("mallory", "ws_studio", mode="sqlite",
                    memberships_json='{"mallory":["ws_studio"]}', store=store)

    def test_sqlite_mode_fails_closed_when_store_missing_or_membership_revoked(self):
        with self.assertRaises(WorkspaceAccessConfigurationError):
            resolve_workspace_access("alice", "ws_studio", mode="sqlite")
        import tempfile, os
        with tempfile.TemporaryDirectory() as directory:
            store = WorkspaceStore(os.path.join(directory, "db.sqlite3"))
            store.create("Studio", "alice", "ws_studio")
            store.revoke_member("ws_studio", "alice", "alice")
            with self.assertRaises(PermissionError):
                resolve_workspace_access("alice", "ws_studio", mode="sqlite", store=store)

    def test_unknown_workspace_auth_mode_fails_closed(self):
        with self.assertRaises(WorkspaceAccessConfigurationError):
            resolve_workspace_access("alice", "ws_studio", mode="automatic")

    def test_path_like_workspace_id_rejected(self):
        with self.assertRaises(WorkspaceAccessConfigurationError):
            resolve_workspace_membership("alice", "../team-a", memberships_json='{"alice":["team-a"]}')

if __name__ == "__main__":
    unittest.main()
