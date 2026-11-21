import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException

import app as app_module
from artifact_retention_inventory import RetentionInventoryError


class RetentionInventoryApiTests(unittest.TestCase):
    def test_inventory_requires_operations_permission_and_workspace_scope(self):
        with (
            patch.object(app_module, "require_review_permission", return_value="alice") as auth,
            patch.object(app_module, "resolve_operator_workspace_scope", return_value="ws-a"),
            patch.object(app_module.retention_inventory, "list_workspace", return_value={
                "workspace_id": "ws-a", "read_only": True,
                "destructive_action_performed": False, "candidates": [],
            }) as inventory,
            patch.dict(os.environ, {"NEXUS_RETENTION_POLICY_JSON": '{"policy_version":"p1"}'}),
        ):
            result = app_module.get_workspace_retention_inventory("ws-a", 25, "token")
        auth.assert_called_once_with("token", "operations.read")
        inventory.assert_called_once()
        args, kwargs = inventory.call_args
        self.assertEqual(args[0:3], ("ws-a", "alice", {"policy_version": "p1"}))
        self.assertEqual(kwargs["limit"], 25)
        self.assertTrue(result["read_only"])
        self.assertFalse(result["destructive_action_performed"])

    def test_inventory_rejects_missing_workspace_scope(self):
        with (
            patch.object(app_module, "require_review_permission", return_value="alice"),
            patch.object(app_module, "resolve_operator_workspace_scope", return_value=None),
            patch.object(app_module.retention_inventory, "list_workspace") as inventory,
        ):
            with self.assertRaises(HTTPException) as error:
                app_module.get_workspace_retention_inventory("ws-a", 10, "token")
        self.assertEqual(error.exception.status_code, 403)
        inventory.assert_not_called()

    def test_invalid_policy_configuration_fails_closed(self):
        with (
            patch.object(app_module, "require_review_permission", return_value="alice"),
            patch.object(app_module, "resolve_operator_workspace_scope", return_value="ws-a"),
            patch.object(app_module.retention_inventory, "list_workspace") as inventory,
            patch.dict(os.environ, {"NEXUS_RETENTION_POLICY_JSON": "{bad-json"}),
        ):
            with self.assertRaises(HTTPException) as error:
                app_module.get_workspace_retention_inventory("ws-a", 10, "token")
        self.assertEqual(error.exception.status_code, 503)
        inventory.assert_not_called()

    def test_inventory_storage_failure_is_sanitized(self):
        with (
            patch.object(app_module, "require_review_permission", return_value="alice"),
            patch.object(app_module, "resolve_operator_workspace_scope", return_value="ws-a"),
            patch.object(
                app_module.retention_inventory, "list_workspace",
                side_effect=RetentionInventoryError("sensitive database path"),
            ),
            patch.dict(os.environ, {"NEXUS_RETENTION_POLICY_JSON": "{}"}),
        ):
            with self.assertRaises(HTTPException) as error:
                app_module.get_workspace_retention_inventory("ws-a", 10, "token")
        self.assertEqual(error.exception.status_code, 503)
        self.assertEqual(error.exception.detail, "Read-only retention inventory is unavailable")
        self.assertNotIn("sensitive", error.exception.detail)


if __name__ == "__main__":
    unittest.main()
