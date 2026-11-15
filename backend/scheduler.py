"""Run persistent due-job scheduler: python scheduler.py"""
import os,time
from queue_store import JobQueue
from scheduler_store import ScheduleStore
DB=os.getenv("NEXUS_DB_PATH","data/nexus.sqlite3")
INTERVAL=max(5,int(os.getenv("NEXUS_SCHEDULER_POLL_SECONDS","30")))
queue=JobQueue(DB); schedules=ScheduleStore(DB)
def main():
 print("scheduler_started")
 while True:
  try:
   result=schedules.dispatch_due(queue)
   if result["count"]: print("scheduled_jobs_dispatched",result["count"])
  except Exception as exc:
   print("scheduler_error",type(exc).__name__)
  time.sleep(INTERVAL)
if __name__=="__main__":main()
