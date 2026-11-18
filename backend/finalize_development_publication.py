"""Finalize engineering jobs only after a verified Draft PR head exists."""
from __future__ import annotations

import json
import os
import sys

from development_jobs import DevelopmentJobStore


def finalize(environ=None, allow_no_publication=False):
    env = os.environ if environ is None else environ
    store = DevelopmentJobStore(env.get("NEXUS_DEVELOPMENT_DB", "data/nexus-development.sqlite3"))
    pending = store.list(statuses=["review_pending"], limit=500)
    if not pending:
        return {"completed_job_ids": [], "pending_job_ids": [], "message": "no review-pending jobs"}

    if allow_no_publication:
        raise RuntimeError(
            f"{len(pending)} validated job(s) remain review_pending but no open Draft PR was found; "
            "the persistent source artifacts were retained for the next run."
        )

    pr_url = env.get("NEXUS_PUBLICATION_PR_URL", "").strip()
    head_sha = env.get("NEXUS_PUBLICATION_HEAD_SHA", "").strip().lower()
    branch_sha = env.get("NEXUS_PUBLICATION_BRANCH_SHA", "").strip().lower()
    raw_files = env.get("NEXUS_PUBLICATION_FILES_JSON", "")
    if not pr_url or not head_sha or not branch_sha or not raw_files:
        raise ValueError("verified Draft PR URL, exact head SHA, branch SHA and changed-file list are required")
    try:
        published_files = json.loads(raw_files)
    except json.JSONDecodeError as error:
        raise ValueError("NEXUS_PUBLICATION_FILES_JSON must be valid JSON") from error
    if not isinstance(published_files, list):
        raise ValueError("NEXUS_PUBLICATION_FILES_JSON must be a JSON array")

    result = store.publish_review(
        pr_url=pr_url,
        pr_head_sha=head_sha,
        expected_head_sha=branch_sha,
        published_files=published_files,
        actor="github-actions",
    )
    if result["pending_job_ids"]:
        raise RuntimeError(
            "Draft PR does not contain every validated file for pending job(s): "
            + ", ".join(result["pending_job_ids"])
        )
    return result


def main():
    try:
        allow_none = "--no-publication" in sys.argv[1:]
        result = finalize(allow_no_publication=allow_none)
    except Exception as error:
        print(f"NEXUS review publication finalization failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
