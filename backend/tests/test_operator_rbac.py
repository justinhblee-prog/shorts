import json
import unittest
from unittest import mock

from operator_rbac import (
    OperatorRoleConfigurationError, has_permission, permissions_for,
)


class OperatorRoleTests(unittest.TestCase):
    def test_legacy_mode_preserves_existing_operator_permissions(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertTrue(has_permission("legacy-operator", "queue.control"))
            self.assertTrue(has_permission("any-authenticated-operator", "production.create"))
            self.assertFalse(has_permission("any-authenticated-operator", "publish.execute"))

    def test_explicit_role_map_grants_only_declared_permissions(self):
        roles = json.dumps({
            "alice": ["reviewer"],
            "bob": ["publisher"],
            "carol": ["analyst", "finance"],
        })
        self.assertTrue(has_permission("alice", "review.decide", role_map_json=roles))
        self.assertFalse(has_permission("alice", "publish.execute", role_map_json=roles))
        self.assertTrue(has_permission("bob", "publish.execute", role_map_json=roles))
        self.assertFalse(has_permission("bob", "review.decide", role_map_json=roles))
        self.assertTrue(has_permission("carol", "finance.write", role_map_json=roles))
        self.assertTrue(has_permission("carol", "analytics.read", role_map_json=roles))

    def test_unmapped_operator_is_denied_when_explicit_role_map_is_enabled(self):
        roles = json.dumps({"alice": ["reviewer"]})
        self.assertEqual(permissions_for("unmapped", role_map_json=roles), frozenset())
        self.assertFalse(has_permission("unmapped", "review.read", role_map_json=roles))

    def test_admin_role_grants_wildcard(self):
        self.assertTrue(has_permission("root", "any.future.permission",
                                       role_map_json=json.dumps({"root": ["admin"]})))

    def test_malformed_or_empty_role_map_fails_closed(self):
        for raw in ("not-json", "[]", "{}", json.dumps({"alice": []}),
                    json.dumps({"alice": ["unknown"]}),
                    json.dumps({"alice": ["reviewer", "reviewer"]}),
                    json.dumps({"": ["admin"]})):
            with self.subTest(raw=raw):
                with self.assertRaises(OperatorRoleConfigurationError):
                    has_permission("alice", "review.read", role_map_json=raw)

    def test_environment_role_map_is_used(self):
        raw = json.dumps({"alice": ["publisher"]})
        with mock.patch.dict("os.environ", {"NEXUS_REVIEW_ROLE_MAP_JSON": raw}, clear=True):
            self.assertTrue(has_permission("alice", "publish.execute"))
            self.assertFalse(has_permission("alice", "review.decide"))


if __name__ == "__main__":
    unittest.main()
