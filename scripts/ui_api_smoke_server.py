#!/usr/bin/env python3
"""Seed a disposable SQLite database and serve the real FastAPI app for browser smoke tests."""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    temp_root = Path(tempfile.mkdtemp(prefix="nexus-ui-api-smoke-"))
    db_path = temp_root / "nexus.sqlite3"
    os.environ["NEXUS_DB_PATH"] = str(db_path)
    os.environ["NEXUS_REVIEW_TOKEN"] = "nexus-ui-browser-smoke-token-2026-11-19-32chars"
    os.environ["NEXUS_REVIEW_CREDENTIALS_JSON"] = ""
    os.environ["NEXUS_REVIEW_ROLE_MAP_JSON"] = ""
    os.environ["NEXUS_MEDIA_ROOT"] = str(temp_root / "media")
    os.environ["NEXUS_UPLOAD_DIR"] = str(temp_root / "uploads")
    os.environ["PORT"] = str(args.port)
    sys.path.insert(0, str(BACKEND))

    import app  # noqa: E402 - environment and DB path must be set first

    today = date.today()
    start_date = (today - timedelta(days=1)).isoformat()
    end_date = today.isoformat()
    for index in range(501):
        app.youtube_analytics_store.save(
            video_id="browser-yt-%03d" % (index + 1),
            start_date=start_date,
            end_date=end_date,
            metrics={
                "views": 1000 + index,
                "engagedViews": 200 + index,
                "estimatedMinutesWatched": 50.0 + index,
                "averageViewDuration": 30.0,
                "averageViewPercentage": 42.0,
            },
            retention=[],
            analytics_status="available",
            retention_status="no_data",
        )

    job_id = "browser-smoke-tiktok-publication"
    attempt_id = "browser-smoke-tiktok-attempt"
    app.tiktok_publish_store.begin(
        job_id, "Browser smoke fixture", False, "browser-smoke",
        attempt_id, False, False,
    )
    app.tiktok_publish_store.mark_status(
        job_id, attempt_id, "PUBLISH_COMPLETE", video_ids=["browser-tt-001"],
    )
    app.tiktok_metrics_store.save_snapshot(job_id, {
        "id": "browser-tt-001",
        "view_count": 765,
        "like_count": 45,
        "comment_count": 6,
        "share_count": 3,
    })

    print("UI API smoke fixture seeded: 501 YouTube and 1 TikTok snapshots", flush=True)
    import uvicorn  # noqa: E402

    uvicorn.run(app.app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
