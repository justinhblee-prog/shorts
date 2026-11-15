"""Periodic, quota-conscious YouTube counter collection.

Run: python metrics_collector.py
Uses one videos.list request for up to 50 due videos per interval.
This collects Data API counters only; it does not claim audience-retention analytics.
"""
import logging
import os
import socket
import time
import uuid

from youtube_publishing import YouTubeUploadStore, YouTubePublisher

DB = os.getenv("NEXUS_DB_PATH", "data/nexus.sqlite3")
INTERVAL = max(300, int(os.getenv("NEXUS_METRICS_COLLECTION_INTERVAL_SECONDS", "21600")))
MIN_AGE = max(300, int(os.getenv("NEXUS_METRICS_MIN_AGE_SECONDS", str(INTERVAL))))
BATCH_SIZE = max(1, min(50, int(os.getenv("NEXUS_METRICS_BATCH_SIZE", "50"))))
OWNER_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4()}"

logging.basicConfig(
    level=os.getenv("NEXUS_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("nexus.metrics_collector")


def run_once(store=None, publisher=None):
    store = store or YouTubeUploadStore(DB)
    publisher = publisher or YouTubePublisher(store)
    token = store.acquire_metrics_collector_lease(OWNER_ID, lease_seconds=300)
    if token is None:
        logger.info("metrics_collection_skipped reason=another_collector_holds_lease")
        return {"skipped": True, "requested": 0, "collected": 0}
    try:
        result = publisher.refresh_due_metrics(
            limit=BATCH_SIZE, min_age_seconds=MIN_AGE
        )
        logger.info(
            "metrics_collection_completed requested=%s collected=%s missing=%s",
            result["requested"], result["collected"], len(result["missing"])
        )
        return result
    finally:
        store.release_metrics_collector_lease(OWNER_ID)


def main():
    logger.info(
        "metrics_collector_started interval_seconds=%s min_age_seconds=%s batch_size=%s",
        INTERVAL, MIN_AGE, BATCH_SIZE
    )
    while True:
        try:
            run_once()
        except Exception:
            # A provider/auth failure is visible in logs and retried next interval;
            # it never fabricates metrics or blocks production/review jobs.
            logger.exception("metrics_collection_failed")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
