"""Fail-closed operator-to-workspace membership resolution."""
from __future__ import annotations
import json
import re

_WORKSPACE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

class WorkspaceAccessConfigurationError(ValueError):
    """Unsafe or missing workspace membership configuration."""

def resolve_workspace_membership(operator_id, workspace_id, *, memberships_json=None):
    """Resolve explicit membership; never trust request-body identity or wildcard grants."""
    if not isinstance(operator_id, str) or not operator_id.strip():
        raise WorkspaceAccessConfigurationError("authenticated operator identity is required")
    if not isinstance(workspace_id, str) or not _WORKSPACE_ID.fullmatch(workspace_id):
        raise WorkspaceAccessConfigurationError("a valid workspace ID is required")
    if not isinstance(memberships_json, str) or not memberships_json.strip():
        raise WorkspaceAccessConfigurationError("workspace membership configuration is required")
    try:
        mapping = json.loads(memberships_json)
    except (TypeError, ValueError) as exc:
        raise WorkspaceAccessConfigurationError("workspace membership configuration must be JSON") from exc
    if not isinstance(mapping, dict) or not mapping:
        raise WorkspaceAccessConfigurationError("workspace membership configuration must be a non-empty object")
    for principal, workspaces in mapping.items():
        if (not isinstance(principal, str) or not principal.strip()
                or principal != principal.strip() or len(principal) > 128):
            raise WorkspaceAccessConfigurationError("workspace principal IDs must be valid")
        if (not isinstance(workspaces, list) or not workspaces
                or any(not isinstance(item, str) or not _WORKSPACE_ID.fullmatch(item) for item in workspaces)
                or len(set(workspaces)) != len(workspaces)):
            raise WorkspaceAccessConfigurationError("each principal must have unique valid workspace IDs")
    if workspace_id not in mapping.get(operator_id, []):
        raise PermissionError("operator is not a member of the requested workspace")
    return workspace_id

def resolve_workspace_access(principal_id, workspace_id, *, mode="legacy_config",
                             memberships_json=None, store=None):
    """Resolve operator workspace access using an explicit, fail-closed mode."""
    if mode == "legacy_config":
        return resolve_workspace_membership(
            principal_id, workspace_id, memberships_json=memberships_json
        )
    if mode == "sqlite":
        if store is None:
            raise WorkspaceAccessConfigurationError(
                "durable workspace registry is unavailable"
            )
        try:
            store.require_membership(workspace_id, principal_id)
        except ValueError as exc:
            raise WorkspaceAccessConfigurationError(str(exc)) from exc
        except Exception as exc:
            from workspace_store import WorkspaceDenied
            if isinstance(exc, WorkspaceDenied):
                raise PermissionError("operator is not an active workspace member") from exc
            raise
        return workspace_id
    raise WorkspaceAccessConfigurationError(
        "NEXUS_WORKSPACE_AUTH_MODE must be legacy_config or sqlite"
    )
