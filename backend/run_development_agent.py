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
from seed_development_jobs import seed_development_jobs


def _normalize_approved_scopes(scopes, repo_root):
    """Mark existing directory scopes explicitly before they enter the durable store."""
    root = Path(repo_root).resolve()
    normalized = {}
    for source_ref, paths in scopes.items():
        if not isinstance(paths, list):
            normalized[source_ref] = paths
            continue
        entries = []
        for raw in paths:
            if not isinstance(raw, str) or not raw.strip():
                entries.append(raw)
                continue
            candidate = Path(raw.strip())
            if candidate.is_absolute() or ".." in candidate.parts:
                entries.append(raw)
                continue
            resolved = (root / candidate).resolve()
            try:
                resolved.relative_to(root)
            except ValueError:
                entries.append(raw)
                continue
            path = candidate.as_posix()
            if resolved.is_dir():
                path = path.rstrip("/") + "/"
            entries.append(path)
        normalized[source_ref] = entries
    return normalized


def _json_env(name, default, environ=None):
    source = os.environ if environ is None else environ
    try:
        value = json.loads(source.get(name, default))
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
        _json_env("NEXUS_APPROVED_SCOPES", "{}", env), repo_root,
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
    )
    result = service.run_cycle()
    result["seeded_job_count"] = len(seeded)
    result["database_summary"] = store.summary()
    return result


def main():
    try:
        result = run_once()
    except Exception as error:
        print(f"NEXUS development cycle failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
