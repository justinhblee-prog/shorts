"""Run the persistent, single-leader scheduler: python scheduler.py."""
import logging
import os
import socket
import time
import uuid

from queue_store import JobQueue
from scheduler_store import ScheduleStore
from tiktok_publishing import TikTokPublishStore, TikTokPublisher
from tiktok_oauth import TikTokOAuthStore, TikTokOAuthManager

DB = os.getenv("NEXUS_DB_PATH", "data/nexus.sqlite3")
INTERVAL = max(5, int(os.getenv("NEXUS_SCHEDULER_POLL_SECONDS", "30")))
LEASE_SECONDS = max(15, int(os.getenv("NEXUS_SCHEDULER_LEASE_SECONDS", "90")))
OWNER_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4()}"
queue = JobQueue(DB)
schedules = ScheduleStore(DB)
tiktok_store = TikTokPublishStore(DB)
tiktok_oauth_store = TikTokOAuthStore(DB)
tiktok_oauth_manager = TikTokOAuthManager(tiktok_oauth_store)
tiktok_publisher = TikTokPublisher(
    tiktok_store, token_provider=tiktok_oauth_manager.get_access_token
)

logging.basicConfig(
    level=os.getenv("NEXUS_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("nexus.scheduler")


def main():
    logger.info("scheduler_started interval_seconds=%s lease_seconds=%s owner=%s",
                INTERVAL, LEASE_SECONDS, OWNER_ID)
    token = None
    try:
        while True:
            try:
                token = schedules.acquire_scheduler_lease(
                    OWNER_ID, lease_seconds=LEASE_SECONDS
                )
                if token is None:
                    logger.info("scheduler_standby another_instance_holds_lease")
                else:
                    result = schedules.dispatch_due(
                        queue, lease_owner=OWNER_ID, lease_token=token,
                        lease_seconds=LEASE_SECONDS,
                    )
                    if result.get("lease_lost"):
                        logger.warning("scheduler_leadership_lost")
                        token = None
                    elif result["count"]:
                        logger.info("scheduled_jobs_dispatched count=%s pending=%s",
                                    result["count"], result["pending"])
                    elif result.get("paused"):
                        logger.warning("scheduled_dispatch_held queue_paused pending=%s",
                                       result["pending"])
                    if os.getenv("TIKTOK_ACCESS_TOKEN") or tiktok_oauth_manager.status().get("connected"):
                        try:
                            poll = tiktok_publisher.refresh_due_statuses(
                                limit=2, min_age_seconds=60
                            )
                            if poll.get("checked"):
                                logger.info(
                                    "tiktok_status_poll_completed checked=%s updated=%s errors=%s",
                                    poll["checked"], poll["updated"], len(poll["errors"])
                                )
                        except Exception:
                            logger.exception("tiktok_status_poll_failed")
            except Exception:
                logger.exception("scheduler_iteration_failed")
                token = None
            time.sleep(INTERVAL)
    finally:
        if token:
            schedules.release_scheduler_lease(OWNER_ID, token)


if __name__ == "__main__":
    main()
