"""Bind validated development jobs to an exact open Draft pull request.

This module performs read-only GitHub API requests. It never creates, updates,
approves, merges, or closes a pull request.
"""
from __future__ import annotations

import json
import os
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from development_jobs import DevelopmentJobStore


class GitHubReviewArtifactClient:
    API_ROOT = "https://api.github.com"

    def __init__(self, token: str, timeout: int = 15):
        if not isinstance(token, str) or not token.strip():
            raise ValueError("GitHub token is required")
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 60:
            raise ValueError("timeout must be between 1 and 60 seconds")
        self._token = token.strip()
        self._timeout = timeout

    def _get(self, url: str):
        if not isinstance(url, str) or not url.startswith(self.API_ROOT + "/"):
            raise ValueError("refusing a non-GitHub API URL")
        request = Request(url, headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "nexus-development-review-publisher",
        }, method="GET")
        try:
            with urlopen(request, timeout=self._timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
                link = response.headers.get("Link", "")
        except (HTTPError, URLError, TimeoutError, ValueError) as error:
            raise RuntimeError(f"GitHub review-artifact read failed: {type(error).__name__}") from error
        return payload, link

    def get_pull_request(self, owner: str, repository: str, number: int):
        payload, _ = self._get(
            f"{self.API_ROOT}/repos/{owner}/{repository}/pulls/{number}"
        )
        if not isinstance(payload, dict):
            raise RuntimeError("GitHub returned an invalid pull-request object")
        return payload

    def list_pull_request_files(self, owner: str, repository: str, number: int):
        url = (
            f"{self.API_ROOT}/repos/{owner}/{repository}/pulls/{number}/files"
            "?per_page=100"
        )
        results = []
        while url:
            payload, link = self._get(url)
            if not isinstance(payload, list):
                raise RuntimeError("GitHub returned an invalid pull-request file list")
            results.extend(item for item in payload if isinstance(item, dict))
            next_url = None
            for part in link.split(","):
                if 'rel="next"' in part:
                    candidate = part[part.find("<") + 1:part.find(">")]
                    if candidate.startswith(self.API_ROOT + "/"):
                        next_url = candidate
                    break
            url = next_url
        return results


def _parse_review_url(review_url: str, expected_repository: str):
    parsed = urlparse(review_url)
    if (parsed.scheme != "https" or parsed.netloc.lower() != "github.com"
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("review URL must be a canonical GitHub pull-request URL")
    match = re.fullmatch(
        r"/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/pull/([1-9][0-9]*)",
        parsed.path,
    )
    if not match:
        raise ValueError("review URL must identify a GitHub pull request")
    owner, repository, number = match.groups()
    if f"{owner}/{repository}".lower() != expected_repository.lower():
        raise ValueError("review URL repository does not match GITHUB_REPOSITORY")
    return owner, repository, int(number)


def publish_pending_reviews(
    store,
    client,
    repository: str,
    review_url: str,
    expected_head_sha: str,
    expected_head_ref: str,
    expected_base_ref: str,
):
    """Publish review evidence only after exact PR identity and files are verified."""
    if not isinstance(repository, str) or not re.fullmatch(
        r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository
    ):
        raise ValueError("GITHUB_REPOSITORY must be owner/repository")
    if not isinstance(expected_head_sha, str) or not re.fullmatch(
        r"[0-9a-fA-F]{40}", expected_head_sha
    ):
        raise ValueError("expected pull-request head must be a full commit SHA")
    if not isinstance(expected_head_ref, str) or not expected_head_ref.strip():
        raise ValueError("expected pull-request head branch is required")
    if not isinstance(expected_base_ref, str) or not expected_base_ref.strip():
        raise ValueError("expected pull-request base branch is required")

    pending = store.list(statuses=["review_pending"], limit=500)
    if not pending:
        return {"published_count": 0, "pending_count": 0, "skipped": []}

    owner, repo_name, number = _parse_review_url(review_url, repository)
    pr = client.get_pull_request(owner, repo_name, number)
    head = pr.get("head") if isinstance(pr.get("head"), dict) else {}
    base = pr.get("base") if isinstance(pr.get("base"), dict) else {}
    if pr.get("state") != "open" or pr.get("merged_at") is not None:
        raise RuntimeError("review pull request is not open and unmerged")
    if pr.get("draft") is not True:
        raise RuntimeError("review pull request is not Draft")
    if head.get("sha", "").lower() != expected_head_sha.lower():
        raise RuntimeError("pull-request API head SHA does not match the action output")
    if head.get("ref") != expected_head_ref:
        raise RuntimeError("pull-request head branch does not match the configured automation branch")
    if base.get("ref") != expected_base_ref:
        raise RuntimeError("pull-request base branch does not match the repository default branch")

    raw_files = client.list_pull_request_files(owner, repo_name, number)
    review_files = {
        item.get("filename") for item in raw_files
        if isinstance(item.get("filename"), str) and item.get("filename")
    }
    published = []
    skipped = []
    for job in pending:
        changed_files = job.get("changed_files") or []
        missing = sorted(set(changed_files) - review_files)
        if not changed_files or missing:
            skipped.append({
                "job_id": job["id"],
                "reason": "review PR does not contain every validated job change",
                "missing_files": missing[:20],
            })
            continue
        completed = store.publish_review_artifact(
            job["id"], review_url, expected_head_sha, sorted(review_files),
            is_draft=pr.get("draft") is True,
            is_open=pr.get("state") == "open" and pr.get("merged_at") is None,
        )
        published.append({
            "job_id": completed["id"],
            "status": completed["status"],
            "review_url": completed["review_url"],
            "review_head_sha": completed["review_head_sha"],
        })
    return {
        "published_count": len(published),
        "pending_count": len(pending) - len(published),
        "published": published,
        "skipped": skipped,
    }


def main():
    env = os.environ
    required = (
        "GITHUB_TOKEN", "GITHUB_REPOSITORY", "NEXUS_DEVELOPMENT_DB",
        "NEXUS_REVIEW_PR_URL", "NEXUS_REVIEW_HEAD_SHA",
        "NEXUS_REVIEW_HEAD_REF", "NEXUS_REVIEW_BASE_REF",
    )
    missing = [name for name in required if not env.get(name, "").strip()]
    if missing:
        print("NEXUS review publication is missing required environment values: "
              + ", ".join(missing), file=sys.stderr)
        return 1
    try:
        store = DevelopmentJobStore(env["NEXUS_DEVELOPMENT_DB"])
        client = GitHubReviewArtifactClient(env["GITHUB_TOKEN"])
        result = publish_pending_reviews(
            store=store,
            client=client,
            repository=env["GITHUB_REPOSITORY"],
            review_url=env["NEXUS_REVIEW_PR_URL"],
            expected_head_sha=env["NEXUS_REVIEW_HEAD_SHA"],
            expected_head_ref=env["NEXUS_REVIEW_HEAD_REF"],
            expected_base_ref=env["NEXUS_REVIEW_BASE_REF"],
        )
    except Exception as error:
        print(f"NEXUS review publication failed: {type(error).__name__}: {error}",
              file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
