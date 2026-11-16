"""Periodic, quota-conscious YouTube counter collection.

Run: python metrics_collector.py
Uses one videos.list request for up to 50 due videos per interval.
This collects Data API counters only; it does not claim audience-retention analytics.
"""
import logging
import os
import socket
import threading
import time
import uuid

from youtube_publishing import YouTubeUploadStore, YouTubePublisher
from tiktok_publishing import TikTokPublishStore
from tiktok_oauth import TikTokOAuthStore, TikTokOAuthManager
from tiktok_metrics import TikTokMetricsStore, TikTokMetricsCollector
from youtube_analytics import YouTubeAnalyticsStore, YouTubeAnalyticsCollector
from youtube_oauth import YouTubeOAuthStore, YouTubeOAuthManager

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





def run_youtube_analytics_once(store=None, collector=None, token_manager=None):
    store = store or YouTubeAnalyticsStore(DB)
    if collector is None:
        # Use the same encrypted OAuth token store as the API/manual refresh
        # path. The legacy YOUTUBE_REFRESH_TOKEN environment fallback is not
        # required when the operator has completed OAuth in the dashboard.
        token_manager = token_manager or YouTubeOAuthManager(YouTubeOAuthStore(DB))
        collector = YouTubeAnalyticsCollector(
            store, token_provider=token_manager.get_refresh_token
        )

    lease_seconds = max(30, int(os.getenv("YOUTUBE_ANALYTICS_LEASE_SECONDS", "900")))
    token = store.acquire_lease(OWNER_ID, lease_seconds=lease_seconds)
    if token is None:
        logger.info("youtube_analytics_collection_skipped reason=another_collector_holds_lease")
        return {"skipped": True, "requested": 0, "collected": 0, "failed": []}

    heartbeat_stop = threading.Event()
    lease_lost = threading.Event()
    heartbeat_interval = max(5, lease_seconds // 3)
    def renew_lease_loop():
        while not heartbeat_stop.wait(heartbeat_interval):
            try:
                if not store.renew_lease(OWNER_ID, lease_seconds=lease_seconds):
                    lease_lost.set()
                    logger.error("youtube_analytics_collection_lease_lost")
                    return
            except Exception:
                lease_lost.set()
                logger.exception("youtube_analytics_collection_lease_renewal_failed")
                return

    heartbeat = threading.Thread(
        target=renew_lease_loop,
        name="youtube-analytics-lease-heartbeat",
        daemon=True,
    )
    heartbeat.start()
    try:
        store.record_collection("running")
        result = collector.refresh_due_metrics(
            limit=min(20, BATCH_SIZE),
            min_age_seconds=max(300, int(os.getenv(
                "YOUTUBE_ANALYTICS_MIN_AGE_SECONDS", "86400"
            ))),
        )
        if lease_lost.is_set():
            raise RuntimeError(
                "YouTube Analytics collector lost its lease; batch outcome requires inspection"
            )
        failures = result.get("failed") or []
        failed_count = len(failures)
        if failed_count and result.get("collected", 0):
            collection_status = "partial"
        elif failed_count:
            collection_status = "failed"
        else:
            collection_status = "succeeded"
        failure_summary = (
            str(failed_count) + " video collection(s) failed"
            if failed_count else None
        )
        store.record_collection(
            collection_status,
            requested=result.get("requested", 0),
            collected=result.get("collected", 0),
            failed=failed_count,
            error=failure_summary,
            source=result.get("source", "YouTube Analytics API v2"),
        )
        logger.info(
            "youtube_analytics_collection_completed status=%s requested=%s collected=%s failed=%s",
            collection_status, result["requested"], result["collected"], failed_count,
        )
        return result
    except Exception as exc:
        store.record_collection(
            "failed", error=type(exc).__name__,
            source="YouTube Analytics API v2",
        )
        logger.exception("youtube_analytics_collection_failed")
        raise
    finally:
        heartbeat_stop.set()
        heartbeat.join(timeout=5)
        store.release_lease(OWNER_ID)


def run_tiktok_once(store=None, collector=None, publication_store=None, token_manager=None):
    store=store or TikTokMetricsStore(DB)
    publication_store=publication_store or TikTokPublishStore(DB)
    token_manager=token_manager or TikTokOAuthManager(TikTokOAuthStore(DB))
    collector=collector or TikTokMetricsCollector(
        store,publication_store,
        lambda required_scope: token_manager.get_access_token(required_scope=required_scope),
    )
    token=store.acquire_lease(OWNER_ID,lease_seconds=300)
    if token is None:
        logger.info("tiktok_metrics_collection_skipped reason=another_collector_holds_lease")
        return {"skipped":True,"requested":0,"collected":0}
    try:
        store.record_collection("running")
        try:
            result=collector.refresh_due_metrics(limit=min(20,BATCH_SIZE),min_age_seconds=MIN_AGE)
        except Exception as exc:
            store.record_collection("failed",error=type(exc).__name__)
            raise
        store.record_collection(
            "succeeded",requested=result["requested"],collected=result["collected"],
            missing=len(result["missing"]),source=result.get("source","TikTok Display API v2"),
        )
        logger.info("tiktok_metrics_collection_completed requested=%s collected=%s missing=%s",
                    result["requested"],result["collected"],len(result["missing"]))
        return result
    finally:
        store.release_lease(OWNER_ID,token)

def main():
    logger.info(
        "metrics_collector_started interval_seconds=%s min_age_seconds=%s batch_size=%s",
        INTERVAL, MIN_AGE, BATCH_SIZE
    )
    while True:
        for provider_name,collector_run in (("youtube",run_once),("youtube_analytics",run_youtube_analytics_once),("tiktok",run_tiktok_once)):
            try:
                collector_run()
            except Exception:
                # Provider failures are isolated; one platform outage does not
                # suppress the other platform's metrics collection.
                logger.exception("%s_metrics_collection_failed",provider_name)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
