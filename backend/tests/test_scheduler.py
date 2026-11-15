import os,tempfile,unittest
from datetime import datetime,timezone,timedelta
from scheduler_store import ScheduleStore
from queue_store import JobQueue
class SchedulerTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.db=os.path.join(self.tmp.name,"x.db")
  self.s=ScheduleStore(self.db); self.q=JobQueue(self.db)
 def tearDown(self): self.tmp.cleanup()
 def test_due_dispatch_and_idempotent_recovery(self):
  now=datetime(2026,11,15,tzinfo=timezone.utc)
  item=self.s.create("hourly",3600,{"brand":"Brain Glitch","region":"US",
    "language":"English","topic":"Sleep"},now.isoformat())
  r=self.s.dispatch_due(self.q,now)
  self.assertEqual(r["count"],1)
  self.assertEqual(r["dispatched"][0]["job"]["job_type"],"short_video_production")
  self.assertEqual(self.s.dispatch_due(self.q,now)["count"],0)
  self.assertIsNotNone(self.s.get(item["id"])["last_enqueued_at"])
 def test_missed_intervals_skip_to_future(self):
  start=datetime(2026,11,15,tzinfo=timezone.utc)
  self.s.create("daily",86400,{"brand":"B","region":"US","language":"English","topic":"x"},start.isoformat())
  now=start+timedelta(days=4,hours=2)
  self.s.dispatch_due(self.q,now)
  due=datetime.fromisoformat(self.s.list()[0]["next_run_at"])
  self.assertGreater(due,now)
 def test_minimum_interval(self):
  with self.assertRaises(ValueError):
   self.s.create("too frequent",60,{"brand":"B","region":"US","language":"English","topic":"x"})
if __name__=="__main__":unittest.main()
