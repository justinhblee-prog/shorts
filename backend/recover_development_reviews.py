"""Read-only recovery of orphaned NEXUS development review-pending jobs.

The command only verifies an existing stable automation Draft PR and records
its exact review evidence. It never requeues, creates, updates, approves,
merges, closes, or deploys a pull request.
"""
from __future__ import annotations

import json
import os
import sys

from development_jobs import DevelopmentJobStore
from publish_development_reviews import GitHubReviewArtifactClient, recover_pending_reviews


def main(environ=None):
    env = os.environ if environ is None else environ
    required = (
        "GITHUB_TOKEN", "GITHUB_REPOSITORY", "NEXUS_DEVELOPMENT_DB",
        "NEXUS_REVIEW_HEAD_REF", "NEXUS_REVIEW_BASE_REF",
    )
    missing = [key for key in required if not env.get(key, "").strip()]
    if missing:
        print("NEXUS review recovery is missing required environment values: "
              + ", ".join(missing), file=sys.stderr)
        return 1
    try:
        store = DevelopmentJobStore(env["NEXUS_DEVELOPMENT_DB"])
        client = GitHubReviewArtifactClient(env["GITHUB_TOKEN"])
        result = recover_pending_reviews(
            store=store,
            client=client,
            repository=env["GITHUB_REPOSITORY"],
            expected_head_ref=env["NEXUS_REVIEW_HEAD_REF"],
            expected_base_ref=env["NEXUS_REVIEW_BASE_REF"],
        )
    except Exception as error:
        print(f"NEXUS review recovery failed: {type(error).__name__}: {error}",
              file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # A no-match or ambiguous result is a safe, actionable outcome, not a
    # successful recovery. Keep the workflow visibly non-green for operators.
    return 0 if result["pending_count"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
