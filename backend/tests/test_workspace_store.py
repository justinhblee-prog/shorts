import os, sqlite3, tempfile, unittest
from unittest.mock import patch
from workspace_store import WorkspaceStore, WorkspaceDenied, WorkspaceConflict

class WorkspaceStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=WorkspaceStore(os.path.join(self.tmp.name,"nexus.sqlite3"))
        self.store.create("Studio","alice","ws_studio")
    def tearDown(self): self.tmp.cleanup()
    def test_default_database_path_uses_shared_environment_setting(self):
        configured = os.path.join(self.tmp.name, "configured.sqlite3")
        with patch.dict(os.environ, {"NEXUS_DB_PATH": configured}):
            store = WorkspaceStore()
        self.assertEqual(store.db_path, configured)
        self.assertTrue(os.path.exists(configured))
    def test_explicit_database_path_overrides_environment_setting(self):
        configured = os.path.join(self.tmp.name, "configured.sqlite3")
        explicit = os.path.join(self.tmp.name, "explicit.sqlite3")
        with patch.dict(os.environ, {"NEXUS_DB_PATH": configured}):
            store = WorkspaceStore(explicit)
        self.assertEqual(store.db_path, explicit)
    def test_atomic_owner_creation_and_cross_workspace_denial(self):
        self.assertEqual(self.store.require_membership("ws_studio","alice")["role"],"owner")
        with self.assertRaises(WorkspaceDenied): self.store.require_membership("ws_studio","mallory")
    def test_admin_adds_and_revokes_member(self):
        self.store.add_member("ws_studio","alice","bob","editor")
        self.assertEqual(self.store.require_membership("ws_studio","bob")["role"],"editor")
        self.store.revoke_member("ws_studio","alice","bob")
        with self.assertRaises(WorkspaceDenied): self.store.require_membership("ws_studio","bob")
    def test_viewer_cannot_manage_members(self):
        self.store.add_member("ws_studio","alice","viewer","viewer")
        with self.assertRaises(WorkspaceDenied): self.store.add_member("ws_studio","viewer","eve")
    def test_last_owner_cannot_be_revoked(self):
        with self.assertRaises(WorkspaceConflict): self.store.revoke_member("ws_studio","alice","alice")
    def test_admin_cannot_revoke_owner(self):
        self.store.add_member("ws_studio","alice","bob","admin")
        self.store.add_member("ws_studio","alice","carol","viewer")
        with self.assertRaises(WorkspaceDenied): self.store.revoke_member("ws_studio","bob","alice")
    def test_duplicate_membership_and_invalid_role(self):
        self.store.add_member("ws_studio","alice","bob")
        with self.assertRaises(WorkspaceConflict): self.store.add_member("ws_studio","alice","bob","viewer")
        with self.assertRaises(ValueError): self.store.add_member("ws_studio","alice","eve","owner")
    def test_audit_events_are_immutable(self):
        path=self.store.db_path
        with sqlite3.connect(path) as db:
            with self.assertRaises(sqlite3.IntegrityError): db.execute("UPDATE workspace_audit_events SET event_type='tampered'")
            db.rollback()
            with self.assertRaises(sqlite3.IntegrityError): db.execute("DELETE FROM workspace_audit_events")
    def test_input_validation(self):
        for name, owner in (("", "alice"), ("x"*121,"alice"), ("Studio"," ")):
            with self.assertRaises(ValueError): self.store.create(name,owner)

if __name__ == "__main__": unittest.main()
