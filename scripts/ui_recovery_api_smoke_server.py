#!/usr/bin/env python3
"""Seed a disposable FastAPI database with a quarantined development job for browser recovery smoke."""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()

    temp_root = Path(tempfile.mkdtemp(prefix="nexus-recovery-browser-smoke-"))
    os.environ["NEXUS_DB_PATH"] = str(temp_root / "nexus.sqlite3")
    os.environ["NEXUS_REVIEW_TOKEN"] = "nexus-recovery-browser-smoke-token-2026-11-20-32chars"
    os.environ["NEXUS_REVIEW_CREDENTIALS_JSON"] = ""
    os.environ["NEXUS_REVIEW_ROLE_MAP_JSON"] = ""
    os.environ["NEXUS_MEDIA_ROOT"] = str(temp_root / "media")
    os.environ["NEXUS_UPLOAD_DIR"] = str(temp_root / "uploads")
    os.environ["PORT"] = str(args.port)
    sys.path.insert(0, str(BACKEND))

    import app  # noqa: E402

    parent = app.development_job_store.create(
        "Browser smoke UI dependency",
        description="Completed upstream job for the multi-flow dependency board",
        scope=["frontend/app.js"],
        job_id="browser-smoke-ui-parent",
    )
    job = app.development_job_store.create(
        "Browser smoke quarantined job",
        description="Disposable fixture for the audited recovery browser flow",
        scope=["backend/app.py"],
        acceptance=["Recovery is recorded with operator attribution"],
        max_attempts=1,
        job_id="browser-smoke-quarantine-001",
    )
    app.development_job_store.add_dependency(job["id"], parent["id"])

    # Persist one fixture for every remaining workstream classification.
    workstream_fixtures = [
        ("automation", [".github/workflows/backend-tests.yml"]),
        ("qa", ["backend/tests/test_frontend.py"]),
        ("docs", ["docs/MULTI_FLOW_EXECUTION.md"]),
        ("integration", ["frontend/app.js", "backend/app.py"]),
        ("unclassified", []),
    ]
    for lane, scope in workstream_fixtures:
        app.development_job_store.create(
            f"Browser smoke {lane.upper()} workstream",
            description=f"Persisted scope fixture for {lane} lane classification",
            scope=scope,
            job_id=f"browser-smoke-{lane}-fixture",
        )
    parent_claim = app.development_job_store.claim_ready("recovery-smoke-worker")
    if not parent_claim or parent_claim["id"] != parent["id"]:
        raise RuntimeError("Failed to claim the seeded upstream dependency")
    app.development_job_store.mark_review_pending(
        parent["id"], "recovery-smoke-worker", parent_claim["lease_token"],
        ["frontend/app.js"], True, "ci://browser-smoke/workstream-dependency",
    )
    app.development_job_store.publish_review_artifact(
        parent["id"], "https://github.com/example/nexus/pull/1", "a" * 40,
        ["frontend/app.js"], is_draft=True, is_open=True,
    )
    claim = app.development_job_store.claim_ready("recovery-smoke-worker")
    if not claim or claim["id"] != job["id"]:
        raise RuntimeError("Failed to claim the seeded development job after its dependency completed")
    quarantined = app.development_job_store.fail(
        job["id"],
        "recovery-smoke-worker",
        claim["lease_token"],
        "Permanent validation failure for browser smoke",
        retryable=False,
    )
    if quarantined["status"] != "quarantined":
        raise RuntimeError("Seeded development job did not enter quarantine")

    print("Recovery browser fixture seeded: browser-smoke-quarantine-001", flush=True)
    import uvicorn  # noqa: E402

    uvicorn.run(app.app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
