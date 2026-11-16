import os,tempfile,unittest
from concurrent.futures import ThreadPoolExecutor
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

 def test_only_one_scheduler_owner_can_hold_live_lease(self):
  now=datetime(2026,11,15,tzinfo=timezone.utc)
  first=self.s.acquire_scheduler_lease("scheduler-a",90,now)
  second=self.s.acquire_scheduler_lease("scheduler-b",90,now+timedelta(seconds=10))
  self.assertIsNotNone(first)
  self.assertIsNone(second)
  self.assertTrue(self.s.scheduler_lease_is_valid("scheduler-a",first,now))
  self.assertFalse(self.s.scheduler_lease_is_valid("scheduler-b","missing",now))

 def test_concurrent_scheduler_startup_elects_exactly_one_leader(self):
  now=datetime.now(timezone.utc)
  stores=[ScheduleStore(self.db),ScheduleStore(self.db)]
  with ThreadPoolExecutor(max_workers=2) as pool:
   tokens=list(pool.map(lambda args: args[0].acquire_scheduler_lease(
    args[1],90,now),[(stores[0],"scheduler-a"),(stores[1],"scheduler-b")]))
  self.assertEqual(sum(token is not None for token in tokens),1)

 def test_expired_scheduler_lease_can_be_taken_over_and_fences_old_owner(self):
  now=datetime(2026,11,15,tzinfo=timezone.utc)
  old=self.s.acquire_scheduler_lease("scheduler-a",15,now)
  takeover_at=now+timedelta(seconds=16)
  new=self.s.acquire_scheduler_lease("scheduler-b",30,takeover_at)
  self.assertIsNotNone(new)
  self.assertNotEqual(old,new)
  self.assertFalse(self.s.renew_scheduler_lease("scheduler-a",old,30,takeover_at))
  self.assertFalse(self.s.release_scheduler_lease("scheduler-a",old))
  self.assertTrue(self.s.scheduler_lease_is_valid("scheduler-b",new,takeover_at))

 def test_dispatch_requires_current_scheduler_fencing_token(self):
  now=datetime(2026,11,15,tzinfo=timezone.utc)
  item=self.s.create("hourly",3600,{"brand":"B","region":"US","language":"English","topic":"x"},now.isoformat())
  result=self.s.dispatch_due(self.q,now,lease_owner="stale",lease_token="bad")
  self.assertTrue(result["lease_lost"])
  self.assertEqual(self.s.get(item["id"])["next_run_at"],now.isoformat())
  self.assertEqual(self.s.pending_dispatches(),[])

 def test_stale_dispatcher_cannot_finalize_outbox_after_takeover(self):
  now=datetime.now(timezone.utc)
  self.s.create("hourly",3600,{"brand":"B","region":"US","language":"English","topic":"x"},now.isoformat())
  old=self.s.acquire_scheduler_lease("scheduler-a",90,now)
  store=self.s
  queue=self.q

  class TakeoverQueue:
   def is_paused(self):
    return False
   def enqueue(self,*args,**kwargs):
    with store.db() as db:
     db.execute("UPDATE scheduler_leader_lease SET expires_at=? WHERE id=1",
                ("2000-01-01T00:00:00+00:00",))
    new=store.acquire_scheduler_lease("scheduler-b",90)
    self.assert_token=new
    return queue.enqueue(*args,**kwargs)

  takeover_queue=TakeoverQueue()
  first=store.dispatch_due(takeover_queue,now,lease_owner="scheduler-a",
                           lease_token=old,lease_seconds=90)
  self.assertTrue(first["lease_lost"])
  self.assertEqual(store.outbox_status()["counts"].get("pending"),1)
  second=store.dispatch_due(queue,datetime.now(timezone.utc),
                            lease_owner="scheduler-b",lease_token=takeover_queue.assert_token,
                            lease_seconds=90)
  self.assertEqual(second["count"],1)
  with queue.db() as db:
   count=db.execute("SELECT COUNT(*) FROM pipeline_jobs WHERE idempotency_key LIKE 'schedule:%'").fetchone()[0]
  self.assertEqual(count,1)

 def test_dispatch_runs_only_under_acquired_scheduler_lease(self):
  now=datetime.now(timezone.utc)
  self.s.create("hourly",3600,{"brand":"B","region":"US","language":"English","topic":"x"},now.isoformat())
  token=self.s.acquire_scheduler_lease("scheduler-a",90,now)
  self.assertIsNotNone(token)
  self.assertTrue(self.s.scheduler_lease_is_valid("scheduler-a",token,now))
  result=self.s.dispatch_due(self.q,now,lease_owner="scheduler-a",
                             lease_token=token,lease_seconds=90)
  self.assertEqual(result["count"],1,
                   msg=f"result={result!r} outbox={self.s.outbox_status()!r}")
  self.assertFalse(result.get("lease_lost",False))
if __name__=="__main__":unittest.main()
