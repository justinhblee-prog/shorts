"""Credential-backed worker identity for opt-in remote worker APIs.

Credentials are configured as SHA-256 digests only. No plaintext worker secret is
stored in this module or returned by the API. Workspace grants are explicit and
never accept wildcard or legacy NULL namespaces.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import re

_WORKER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_WORKSPACE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_SHA256 = re.compile(r"^[a-fA-F0-9]{64}$")


class WorkerAuthConfigurationError(ValueError):
    """Missing or unsafe worker credential configuration."""


class WorkerAuthenticationError(PermissionError):
    """Worker credential is absent, invalid, or revoked."""


@dataclass(frozen=True)
class WorkerIdentity:
    worker_id: str
    workspace_ids: tuple[str, ...]


def _bearer_token(authorization):
    if not isinstance(authorization, str):
        raise WorkerAuthenticationError("Worker bearer credential is required")
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token or token.strip() != token:
        raise WorkerAuthenticationError("Worker bearer credential is invalid")
    if len(token) < 32 or len(token) > 4096:
        raise WorkerAuthenticationError("Worker bearer credential is invalid")
    return token


def authenticate_worker(authorization, *, credentials_json=None):
    """Authenticate a worker using a SHA-256 digest and explicit workspace grants."""
    if not isinstance(credentials_json, str) or not credentials_json.strip():
        raise WorkerAuthConfigurationError(
            "NEXUS_WORKER_CREDENTIALS_JSON is not configured"
        )
    try:
        credentials = json.loads(credentials_json)
    except (TypeError, ValueError) as exc:
        raise WorkerAuthConfigurationError(
            "Worker credential configuration must be valid JSON"
        ) from exc
    if not isinstance(credentials, dict) or not credentials:
        raise WorkerAuthConfigurationError(
            "Worker credential configuration must be a non-empty object"
        )

    validated = []
    for worker_id, entry in credentials.items():
        if not isinstance(worker_id, str) or not _WORKER_ID.fullmatch(worker_id):
            raise WorkerAuthConfigurationError("Worker IDs must be valid")
        if not isinstance(entry, dict):
            raise WorkerAuthConfigurationError("Each worker entry must be an object")
        digest = entry.get("token_sha256")
        workspace_ids = entry.get("workspace_ids")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise WorkerAuthConfigurationError(
                "Each worker must have a SHA-256 token digest"
            )
        if (
            not isinstance(workspace_ids, list) or not workspace_ids
            or any(not isinstance(item, str) or not _WORKSPACE_ID.fullmatch(item)
                   for item in workspace_ids)
            or len(set(workspace_ids)) != len(workspace_ids)
        ):
            raise WorkerAuthConfigurationError(
                "Each worker must have unique, explicit workspace grants"
            )
        validated.append((worker_id, digest.lower(), tuple(workspace_ids)))

    token = _bearer_token(authorization)
    supplied = hashlib.sha256(token.encode("utf-8")).hexdigest()
    matched = None
    for worker_id, expected, workspace_ids in validated:
        if hmac.compare_digest(supplied, expected):
            matched = WorkerIdentity(worker_id, workspace_ids)
    if matched is None:
        raise WorkerAuthenticationError("Worker credential is invalid or revoked")
    return matched
