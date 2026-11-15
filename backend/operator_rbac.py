"""Fail-closed role-based authorization for authenticated operator tokens."""
from __future__ import annotations

import json
import os

ROLE_PERMISSIONS = {
    "admin": {"*"},
    "producer": {
        "production.create", "production.execute", "trends.collect",
        "schedules.manage", "queue.enqueue", "media.manage", "trends.read",
        "intelligence.read", "recommendations.read", "production.read",
    },
    "reviewer": {"review.read", "review.decide", "review.evidence", "production.read"},
    "publisher": {"publish.execute", "publish.reconcile", "publish.manage", "publishing.read"},
    "analyst": {"analytics.read", "finance.read", "trends.read", "intelligence.read",
        "recommendations.read", "publishing.read"},
    "operator": {
        "operations.read", "queue.control", "queue.enqueue", "production.create",
        "production.execute", "trends.collect", "schedules.manage", "brand.manage",
        "media.manage", "recommendations.manage", "queue.read", "publishing.read",
        "trends.read", "intelligence.read", "recommendations.read", "production.read",
    },
    "finance": {"finance.read", "finance.write"},
}


class OperatorRoleConfigurationError(ValueError):
    """Raised when role configuration is malformed or unsafe."""


def _load_role_map(raw: str) -> dict[str, frozenset[str]]:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise OperatorRoleConfigurationError(
            "NEXUS_REVIEW_ROLE_MAP_JSON must be a JSON object"
        ) from exc
    if not isinstance(value, dict) or not value:
        raise OperatorRoleConfigurationError(
            "NEXUS_REVIEW_ROLE_MAP_JSON must contain at least one operator"
        )
    result = {}
    for operator_id, roles in value.items():
        if (not isinstance(operator_id, str) or not operator_id.strip()
                or len(operator_id) > 128
                or any(ord(ch) < 32 or ord(ch) == 127 for ch in operator_id)):
            raise OperatorRoleConfigurationError("Role-map operator IDs must be printable")
        if not isinstance(roles, list) or not roles or any(
            not isinstance(role, str) or role not in ROLE_PERMISSIONS for role in roles
        ):
            raise OperatorRoleConfigurationError(
                f"Operator {operator_id!r} has an empty or unknown role assignment"
            )
        if len(set(roles)) != len(roles):
            raise OperatorRoleConfigurationError(
                f"Operator {operator_id!r} has duplicate role assignments"
            )
        result[operator_id] = frozenset(roles)
    return result


def permissions_for(operator_id: str, *, role_map_json: str | None = None) -> frozenset[str]:
    """Resolve explicit role grants; legacy mode retains the operator role."""
    raw = os.getenv("NEXUS_REVIEW_ROLE_MAP_JSON", "") if role_map_json is None else role_map_json
    raw = raw or ""
    if not isinstance(raw, str):
        raise OperatorRoleConfigurationError("NEXUS_REVIEW_ROLE_MAP_JSON must be a JSON string")
    if not raw.strip():
        return frozenset({"*"})
    role_map = _load_role_map(raw)
    roles = role_map.get(operator_id)
    if roles is None:
        return frozenset()
    return frozenset(
        permission
        for role in roles
        for permission in ROLE_PERMISSIONS[role]
    )


def has_permission(operator_id: str, permission: str, *,
                   role_map_json: str | None = None) -> bool:
    if not isinstance(permission, str) or not permission.strip():
        raise ValueError("permission must be a non-empty string")
    permissions = permissions_for(operator_id, role_map_json=role_map_json)
    return "*" in permissions or permission in permissions
