import unittest
import json
from workspace_access import WorkspaceAccessConfigurationError, resolve_workspace_membership

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

    def test_path_like_workspace_id_rejected(self):
        with self.assertRaises(WorkspaceAccessConfigurationError):
            resolve_workspace_membership("alice", "../team-a", memberships_json='{"alice":["team-a"]}')

if __name__ == "__main__":
    unittest.main()
