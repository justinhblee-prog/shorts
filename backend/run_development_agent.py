"""Run one bounded NEXUS development-agent cycle on a trusted self-hosted runner.

This command seeds the durable dependency graph, performs read-only GitHub
backlog intake, and lets the fenced worker execute eligible jobs using the
configured local Aider/Ollama model. It never merges or deploys.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from development_agent_executor import AiderDevelopmentExecutor
from development_backlog_service import DevelopmentBacklogService
from development_github_intake import GitHubReadOnlyClient
from development_jobs import DevelopmentJobStore
from development_security import redact_sensitive_text
from seed_development_jobs import seed_development_jobs


def _normalize_approved_scopes(scopes, repo_root, repository=None):
    """Validate bounded, repository-bound approvals and canonicalize safe paths."""
    import re
    from pathlib import PurePosixPath, PureWindowsPath

    if not isinstance(scopes, dict) or len(scopes) > 500:
        raise ValueError("approved scopes must be an object with at most 500 issue entries")
    root = Path(repo_root).resolve()
    normalized = {}
    source_pattern = re.compile(r"^github:issue:([A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?)/([A-Za-z0-9](?:[A-Za-z0-9._-]{0,98}[A-Za-z0-9])?)#([1-9][0-9]*)$")
    for source_ref, paths in scopes.items():
        if not isinstance(source_ref, str) or len(source_ref) > 300:
            raise ValueError("approved scope keys must be bounded GitHub issue references")
        match = source_pattern.fullmatch(source_ref)
        if not match or (repository and f"{match.group(1)}/{match.group(2)}".casefold() != repository.casefold()):
            raise ValueError("approved scope key must identify an issue in the configured repository")
        if not isinstance(paths, list) or not paths or len(paths) > 100:
            raise ValueError("each approved issue must declare 1 to 100 paths")
        entries = []
        for raw in paths:
            if not isinstance(raw, str) or not raw.strip() or len(raw) > 512 or "\x00" in raw:
                raise ValueError("approved scope paths must be non-empty strings of at most 512 characters")
            portable = raw.strip().replace("\\", "/")
            posix = PurePosixPath(portable)
            windows = PureWindowsPath(raw.strip())
            if not posix.parts or posix.as_posix() in {".", ""} or posix.is_absolute() or windows.is_absolute() or windows.drive or ".." in posix.parts:
                raise ValueError("approved scope paths must be repository-relative and traversal-free")
            candidate = Path(*posix.parts)
            resolved = (root / candidate).resolve()
            try:
                resolved.relative_to(root)
            except ValueError as error:
                raise ValueError("approved scope path resolves outside the repository") from error
            path = resolved.relative_to(root).as_posix()
            if resolved.is_dir():
                path = path.rstrip("/") + "/"
            if path in entries:
                raise ValueError("approved scope paths must not contain duplicates")
            entries.append(path)
        normalized[source_ref] = entries
    return normalized


def _json_env(name, default, environ=None):
    source = os.environ if environ is None else environ
    raw = source.get(name, default)
    if not isinstance(raw, str) or len(raw) > 65536:
        raise ValueError(f"{name} must be a JSON object no larger than 64 KiB")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"{name} must contain valid JSON") from error
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    return value


def run_once(environ=None):
    env = os.environ if environ is None else environ
    token = env.get("GITHUB_TOKEN", "").strip()
    repository = env.get("GITHUB_REPOSITORY", "").strip()
    if not token or "/" not in repository:
        raise ValueError("GITHUB_TOKEN and GITHUB_REPOSITORY=owner/repo are required")
    owner, name = repository.split("/", 1)
    if not owner or not name:
        raise ValueError("GITHUB_REPOSITORY must be owner/repo")

    # Validate configuration before opening the database or making network calls.
    repo_root = env.get("GITHUB_WORKSPACE", os.getcwd())
    approved_scopes = _normalize_approved_scopes(
        _json_env("NEXUS_APPROVED_SCOPES", "{}", env), repo_root, repository,
    )
    db_path = env.get("NEXUS_DEVELOPMENT_DB", "data/nexus-development.sqlite3")
    store = DevelopmentJobStore(db_path)
    seeded = seed_development_jobs(store)
    github = GitHubReadOnlyClient(token)
    executor = AiderDevelopmentExecutor(
        repo_root=repo_root,
        model=env.get("NEXUS_DEV_AGENT_MODEL", "ollama_chat/qwen2.5-coder:7b"),
        timeout_seconds=int(env.get("NEXUS_DEV_AGENT_TIMEOUT", "2700")),
    )
    service = DevelopmentBacklogService(
        store=store,
        github_client=github,
        owner=owner,
        repository=name,
        executor=executor,
        worker_id=env.get("RUNNER_NAME", "nexus-local-agent"),
        approved_scopes=approved_scopes,
        poll_seconds=2,
        idle_seconds=int(env.get("NEXUS_AGENT_IDLE_SECONDS", "5")),
        require_execution_verifier=True,
    )
    result = service.run_cycle()
    result["seeded_job_count"] = len(seeded)
    result["database_summary"] = store.summary()
    return result


def main():
    try:
        result = run_once()
    except Exception as error:
        detail = redact_sensitive_text(f"{type(error).__name__}: {error}", limit=4000)
        print(f"NEXUS development cycle failed: {detail}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
