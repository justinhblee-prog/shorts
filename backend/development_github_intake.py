"""Read-only GitHub backlog intake for the NEXUS development scheduler.

Only explicitly opted-in issues become executable jobs. Pull requests and Actions
runs are context, never implicit product backlog items. This module performs no
GitHub mutations and accepts an injected client for least-privilege testing.
"""
from __future__ import annotations

from typing import Any, Iterable

JOB_LABELS = frozenset({"development-job", "nexus:development-job"})
DEFAULT_SCOPE = ["backend/"]


def _labels(item: dict[str, Any]) -> set[str]:
    raw = item.get("labels") or []
    result = set()
    for label in raw:
        name = label.get("name") if isinstance(label, dict) else label
        if isinstance(name, str):
            result.add(name.strip().lower())
    return result


def _positive_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def normalize_issue(issue: dict[str, Any]) -> dict[str, Any] | None:
    """Return a job candidate only for open, explicitly labeled issues."""
    if not isinstance(issue, dict) or issue.get("state") != "open":
        return None
    number = _positive_int(issue.get("number"))
    title = issue.get("title")
    if number is None or not isinstance(title, str) or not title.strip():
        return None
    if not (_labels(issue) & JOB_LABELS):
        return None
    repository = issue.get("repository") or ""
    if not isinstance(repository, str) or not repository.strip():
        repository = "unknown/unknown"
    body = issue.get("body")
    body = body.strip() if isinstance(body, str) else ""
    url = issue.get("html_url")
    if not isinstance(url, str) or not url.startswith("https://github.com/"):
        url = f"https://github.com/{repository}/issues/{number}"
    return {
        "source_ref": f"github:issue:{repository}#{number}",
        "title": title.strip()[:240],
        "description": body[:8000],
        "url": url,
        "number": number,
        "repository": repository,
        "priority": 50,
        "scope": list(DEFAULT_SCOPE),
        "acceptance": ["Implement the issue requirements", "Add or update regression tests"],
    }


def summarize_pull_request(pr: dict[str, Any]) -> dict[str, Any] | None:
    """Keep PR state as context; never turn a PR into a new job by itself."""
    if not isinstance(pr, dict):
        return None
    number = _positive_int(pr.get("number"))
    if number is None:
        return None
    state = pr.get("state")
    merged = pr.get("merged") is True
    draft = pr.get("draft") is True
    if merged or state == "closed":
        disposition = "closed"
    elif draft:
        disposition = "draft"
    elif state == "open":
        disposition = "open"
    else:
        disposition = "unknown"
    return {
        "number": number,
        "title": str(pr.get("title") or "")[:240],
        "state": disposition,
        "url": pr.get("html_url") if isinstance(pr.get("html_url"), str) else None,
        "head_sha": ((pr.get("head") or {}).get("sha")
                     if isinstance(pr.get("head"), dict) else None),
    }


def summarize_workflow_run(run: dict[str, Any]) -> dict[str, Any] | None:
    """Expose failed/in-progress CI as evidence context, not executable work."""
    if not isinstance(run, dict):
        return None
    run_id = _positive_int(run.get("id"))
    if run_id is None:
        return None
    status = run.get("status")
    conclusion = run.get("conclusion")
    if status not in {"queued", "in_progress", "completed"}:
        status = "unknown"
    if conclusion not in {None, "success", "failure", "cancelled", "skipped", "timed_out", "action_required"}:
        conclusion = "unknown"
    return {
        "id": run_id,
        "name": str(run.get("name") or "")[:160],
        "status": status,
        "conclusion": conclusion,
        "head_sha": run.get("head_sha") if isinstance(run.get("head_sha"), str) else None,
        "url": run.get("html_url") if isinstance(run.get("html_url"), str) else None,
    }


def sync_labeled_issues(store: Any, issues: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Idempotently import only labeled open issues into the local job store."""
    existing = {
        job.get("source_ref")
        for job in store.list(limit=500)
        if isinstance(job, dict) and job.get("source_ref")
    }
    created, skipped = [], []
    for issue in issues:
        candidate = normalize_issue(issue)
        if candidate is None:
            skipped.append({"reason": "not_an_open_opted_in_issue"})
            continue
        if candidate["source_ref"] in existing:
            skipped.append({"source_ref": candidate["source_ref"], "reason": "duplicate"})
            continue
        job = store.create(
            title=candidate["title"],
            description=candidate["description"],
            priority=candidate["priority"],
            scope=candidate["scope"],
            acceptance=candidate["acceptance"],
            source_ref=candidate["source_ref"],
        )
        existing.add(candidate["source_ref"])
        created.append(job)
    return {"created": created, "skipped": skipped, "created_count": len(created)}


def read_github_snapshot(client: Any, owner: str, repository: str) -> dict[str, list[dict[str, Any]]]:
    """Read a bounded snapshot via an injected GET-only client.

    The client must expose list_issues, list_pull_requests, and list_workflow_runs.
    Each method receives owner, repository, and per_page=100. No write method is used.
    """
    if not isinstance(owner, str) or not owner.strip() or not isinstance(repository, str) or not repository.strip():
        raise ValueError("owner and repository are required")
    raw_issues = client.list_issues(owner, repository, state="open", per_page=100)
    raw_prs = client.list_pull_requests(owner, repository, state="open", per_page=100)
    raw_runs = client.list_workflow_runs(owner, repository, per_page=100)
    return {
        "issues": [item for item in raw_issues if isinstance(item, dict)],
        "pull_requests": [item for item in raw_prs if isinstance(item, dict)],
        "workflow_runs": [item for item in raw_runs if isinstance(item, dict)],
    }


def normalize_snapshot(snapshot: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Normalize all three read-only feeds without conflating their semantics."""
    return {
        "job_candidates": [
            candidate for item in snapshot.get("issues", [])
            if (candidate := normalize_issue(item)) is not None
        ],
        "pull_requests": [
            item for raw in snapshot.get("pull_requests", [])
            if (item := summarize_pull_request(raw)) is not None
        ],
        "workflow_runs": [
            item for raw in snapshot.get("workflow_runs", [])
            if (item := summarize_workflow_run(raw)) is not None
        ],
    }
