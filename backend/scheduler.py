"""Run the persistent, single-leader scheduler: python scheduler.py."""
import logging
import os
import socket
import time
import uuid

from queue_store import JobQueue
from scheduler_store import ScheduleStore
from scheduler_runtime_config import load_scheduler_config

DB = os.getenv("NEXUS_DB_PATH", "data/nexus.sqlite3")
INTERVAL, LEASE_SECONDS = load_scheduler_config(os.environ)
OWNER_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4()}"
queue = JobQueue(DB)
schedules = ScheduleStore(DB)

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
            except Exception:
                logger.exception("scheduler_iteration_failed")
                token = None
            time.sleep(INTERVAL)
    finally:
        if token:
            schedules.release_scheduler_lease(OWNER_ID, token)


if __name__ == "__main__":
    main()
