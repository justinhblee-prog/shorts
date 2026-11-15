"""Run persistent due-job scheduler: python scheduler.py"""
import os,time,logging
from queue_store import JobQueue
from scheduler_store import ScheduleStore
DB=os.getenv("NEXUS_DB_PATH","data/nexus.sqlite3")
INTERVAL=max(5,int(os.getenv("NEXUS_SCHEDULER_POLL_SECONDS","30")))
queue=JobQueue(DB); schedules=ScheduleStore(DB)
logging.basicConfig(
 level=os.getenv("NEXUS_LOG_LEVEL","INFO").upper(),
 format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger=logging.getLogger("nexus.scheduler")
def main():
 logger.info("scheduler_started interval_seconds=%s", INTERVAL)
 while True:
  try:
   result=schedules.dispatch_due(queue)
   if result["count"]:
    logger.info("scheduled_jobs_dispatched count=%s pending=%s",
                result["count"], result["pending"])
   elif result.get("paused"):
    logger.warning("scheduled_dispatch_held queue_paused pending=%s", result["pending"])
  except Exception:
   logger.exception("scheduler_iteration_failed")
  time.sleep(INTERVAL)
if __name__=="__main__":main()
