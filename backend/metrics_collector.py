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
from tiktok_publishing import TikTokPublishStore
from tiktok_oauth import TikTokOAuthStore, TikTokOAuthManager
from tiktok_metrics import TikTokMetricsStore, TikTokMetricsCollector

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
        store.record_metrics_collection("running", source="YouTube Data API v3")
        try:
            result = publisher.refresh_due_metrics(
                limit=BATCH_SIZE, min_age_seconds=MIN_AGE
            )
        except Exception as exc:
            store.record_metrics_collection(
                "failed", error=type(exc).__name__,
                source="YouTube Data API v3"
            )
            raise
        store.record_metrics_collection(
            "succeeded", requested=result["requested"],
            collected=result["collected"], missing=len(result["missing"]),
            source=result.get("source", "YouTube Data API v3")
        )
        logger.info(
            "metrics_collection_completed requested=%s collected=%s missing=%s",
            result["requested"], result["collected"], len(result["missing"])
        )
        return result
    finally:
        store.release_metrics_collector_lease(OWNER_ID)



def run_tiktok_once(store=None, collector=None, publication_store=None, token_manager=None):
    store = store or TikTokMetricsStore(DB)
    publication_store = publication_store or TikTokPublishStore(DB)
    token_manager = token_manager or TikTokOAuthManager(TikTokOAuthStore(DB))
    collector = collector or TikTokMetricsCollector(
        store, publication_store,
        lambda required_scope: token_manager.get_access_token(required_scope=required_scope),
    )
    token = store.acquire_lease(OWNER_ID, lease_seconds=300)
    if token is None:
        logger.info("tiktok_metrics_collection_skipped reason=another_collector_holds_lease")
        return {"skipped": True, "requested": 0, "collected": 0}
    try:
        store.record_collection("running")
        try:
            result = collector.refresh_due_metrics(
                limit=min(20, BATCH_SIZE), min_age_seconds=MIN_AGE
            )
        except Exception as exc:
            store.record_collection("failed", error=type(exc).__name__)
            raise
        store.record_collection(
            "succeeded", requested=result["requested"],
            collected=result["collected"], missing=len(result["missing"]),
            source=result.get("source", "TikTok Display API v2"),
        )
        logger.info("tiktok_metrics_collection_completed requested=%s collected=%s missing=%s",
                    result["requested"], result["collected"], len(result["missing"]))
        return result
    finally:
        store.release_lease(OWNER_ID, token)


def main():
    logger.info(
        "metrics_collector_started interval_seconds=%s min_age_seconds=%s batch_size=%s",
        INTERVAL, MIN_AGE, BATCH_SIZE
    )
    while True:
        try:
            run_once()
            run_tiktok_once()
        except Exception:
            # A provider/auth failure is visible in logs and retried next interval;
            # it never fabricates metrics or blocks production/review jobs.
            logger.exception("metrics_collection_failed")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
