"""CLI entry point for read-only GitHub development backlog synchronization.

Required environment:
  GITHUB_TOKEN              read-only token for Issues, Pull requests, Actions
  GITHUB_REPOSITORY_OWNER   repository owner
  GITHUB_REPOSITORY_NAME    repository name

Optional:
  NEXUS_DEVELOPMENT_DB      SQLite path (default: data/nexus-development.sqlite3)
  NEXUS_APPROVED_SCOPES     JSON object mapping issue source_ref to path arrays

No GitHub write API is used. Issues without an explicit approved scope are skipped.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from development_github_intake import GitHubReadOnlyClient, sync_github_backlog
from development_jobs import DevelopmentJobStore


def run_from_environment(environ=None):
    env = os.environ if environ is None else environ
    token = env.get("GITHUB_TOKEN", "")
    owner = env.get("GITHUB_REPOSITORY_OWNER", "")
    repository = env.get("GITHUB_REPOSITORY_NAME", "")
    if not token.strip() or not owner.strip() or not repository.strip():
        raise ValueError("GITHUB_TOKEN, GITHUB_REPOSITORY_OWNER and GITHUB_REPOSITORY_NAME are required")

    raw_scopes = env.get("NEXUS_APPROVED_SCOPES", "{}")
    try:
        approved_scopes = json.loads(raw_scopes)
    except json.JSONDecodeError as error:
        raise ValueError("NEXUS_APPROVED_SCOPES must be valid JSON") from error
    if not isinstance(approved_scopes, dict):
        raise ValueError("NEXUS_APPROVED_SCOPES must be a JSON object")

    db_path = env.get("NEXUS_DEVELOPMENT_DB", "data/nexus-development.sqlite3")
    store = DevelopmentJobStore(db_path)
    client = GitHubReadOnlyClient(token)
    return sync_github_backlog(
        store, client, owner.strip(), repository.strip(),
        approved_scopes=approved_scopes,
    )


def main():
    try:
        result = run_from_environment()
    except Exception as error:
        print(f"backlog sync failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
