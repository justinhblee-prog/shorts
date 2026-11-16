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
            self.assertTrue(has_permission("any-authenticated-operator", "publish.execute"))

    def test_per_operator_credentials_require_explicit_role_map(self):
        with mock.patch.dict(
            "os.environ",
            {"NEXUS_REVIEW_CREDENTIALS_JSON": json.dumps({"alice": ["not-a-token"]})},
            clear=True,
        ):
            with self.assertRaises(OperatorRoleConfigurationError):
                permissions_for("alice")

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

    def test_read_permissions_are_separated_by_role(self):
        roles = json.dumps({
            "producer": ["producer"],
            "reviewer": ["reviewer"],
            "publisher": ["publisher"],
            "analyst": ["analyst"],
            "operator": ["operator"],
        })
        self.assertTrue(has_permission("producer", "production.read", role_map_json=roles))
        self.assertTrue(has_permission("producer", "trends.read", role_map_json=roles))
        self.assertTrue(has_permission("reviewer", "review.read", role_map_json=roles))
        self.assertFalse(has_permission("reviewer", "operations.read", role_map_json=roles))
        self.assertTrue(has_permission("publisher", "publishing.read", role_map_json=roles))
        self.assertTrue(has_permission("analyst", "recommendations.read", role_map_json=roles))
        self.assertTrue(has_permission("operator", "queue.read", role_map_json=roles))
        self.assertFalse(has_permission("operator", "review.read", role_map_json=roles))

    def test_worker_and_opportunity_roles_are_separated(self):
        roles = json.dumps({
            "worker-service": ["worker"],
            "analyst": ["analyst"],
            "producer": ["producer"],
        })
        self.assertTrue(has_permission("worker-service", "worker.execute", role_map_json=roles))
        self.assertFalse(has_permission("worker-service", "queue.control", role_map_json=roles))
        self.assertTrue(has_permission("analyst", "opportunities.manage", role_map_json=roles))
        self.assertFalse(has_permission("analyst", "review.decide", role_map_json=roles))
        self.assertFalse(has_permission("producer", "publish.execute", role_map_json=roles))


    def test_individual_credentials_require_an_explicit_role_map(self):
        with mock.patch.dict(
            "os.environ",
            {"NEXUS_REVIEW_CREDENTIALS_JSON": '{"alice":"' + ("a" * 48) + '"}',
             "NEXUS_REVIEW_ROLE_MAP_JSON": ""},
            clear=True,
        ):
            with self.assertRaisesRegex(
                OperatorRoleConfigurationError, "required when per-operator credentials"
            ):
                has_permission("alice", "review.read")

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
