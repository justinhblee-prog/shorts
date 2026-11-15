import sys, tempfile, unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from queue_store import JobQueue, LeaseConflict, IdempotencyConflict

class QueueTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.q=JobQueue(Path(self.tmp.name)/"test.db",10)
 def tearDown(self): self.tmp.cleanup()
 def create_production_run(self, job_id, status="queued"):
  with self.q.db() as c:
   c.execute("""CREATE TABLE IF NOT EXISTS production_runs (
    job_id TEXT PRIMARY KEY, status TEXT NOT NULL, current_stage TEXT,
    error TEXT, updated_at TEXT)""")
   c.execute("""INSERT INTO production_runs(job_id,status,current_stage,error,updated_at)
    VALUES(?,?,?,?,?)""",(job_id,status,status,None,"2026-01-01T00:00:00+00:00"))
 def test_idempotency(self):
  a=self.q.enqueue("script",{"topic":"x"},idempotency_key="once")
  b=self.q.enqueue("script",{"topic":"x"},idempotency_key="once")
  self.assertEqual(a["id"],b["id"]); self.assertEqual(self.q.stats()["total"],1)
  with self.assertRaises(IdempotencyConflict):
   self.q.enqueue("script",{"topic":"y"},idempotency_key="once")
  with self.assertRaises(IdempotencyConflict):
   self.q.enqueue("render",{"topic":"x"},idempotency_key="once")
 def test_exclusive_claim_and_fenced_completion(self):
  j=self.q.enqueue("render",{}); a=self.q.claim("worker-a")
  self.assertEqual(a["id"],j["id"]); self.assertIsNone(self.q.claim("worker-b"))
  self.assertEqual(self.q.finish(j["id"],"worker-a",a["lease_token"])["status"],"review_pending")
  with self.assertRaises(LeaseConflict): self.q.finish(j["id"],"worker-a",a["lease_token"])
 def test_concurrent_claims_are_unique(self):
  jobs=[self.q.enqueue("render",{"n":i}) for i in range(8)]
  with ThreadPoolExecutor(max_workers=8) as pool:
   claimed=list(pool.map(lambda n:self.q.claim("worker-"+str(n)),range(8)))
  ids=[j["id"] for j in claimed if j]
  self.assertEqual(len(ids),8)
  self.assertEqual(len(set(ids)),8)
 def test_expired_lease_fences_old_worker_after_reclaim(self):
  j=self.q.enqueue("render",{}); old=self.q.claim("worker-old")
  with self.q.db() as c:
   c.execute("UPDATE pipeline_jobs SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",(j["id"],))
  new=self.q.claim("worker-new")
  self.assertEqual(new["id"],j["id"])
  with self.assertRaises(LeaseConflict):
   self.q.finish(j["id"],"worker-old",old["lease_token"])
 def test_cancel_revokes_worker_lease(self):
  j=self.q.enqueue("render",{}); a=self.q.claim("worker-a")
  cancelled=self.q.cancel(j["id"],"operator stop")
  self.assertEqual(cancelled["status"],"cancelled")
  with self.assertRaises(LeaseConflict): self.q.finish(j["id"],"worker-a",a["lease_token"])
 def test_recover_expired_lease(self):
  j=self.q.enqueue("render",{}); a=self.q.claim("worker-a")
  with self.q.db() as c:
   c.execute("UPDATE pipeline_jobs SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",(j["id"],))
  result=self.q.recover()
  self.assertEqual(result["requeued"],1)
  self.assertEqual(self.q.get(j["id"])["status"],"queued")
 def test_retry_state_and_event_log(self):
  j=self.q.enqueue("research",{}); a=self.q.claim("worker-a")
  failed=self.q.fail(j["id"],"worker-a",a["lease_token"],"network","temporary",True)
  self.assertEqual(failed["status"],"failed_retriable")
  retried=self.q.claim("worker-b")
  self.assertEqual(retried["id"],j["id"])
  self.assertEqual(retried["attempt"],2)
  self.assertEqual([e["event_type"] for e in self.q.events(j["id"])],["enqueued","claimed","failed","claimed"])
 def test_paused_queue_refuses_claim_until_resume(self):
  self.q.enqueue("short_video_production", {"topic": "held"})
  self.q.pause("operator investigation")
  self.assertIsNone(self.q.claim("worker-a"))
  self.q.resume()
  self.assertIsNotNone(self.q.claim("worker-a"))
 def test_production_pause_does_not_block_other_queue_types(self):
  self.q.enqueue("render", {"topic":"other"})
  self.q.pause("production only")
  claimed=self.q.claim("worker-other",job_type="render")
  self.assertEqual(claimed["job_type"],"render")
 def test_pause_revokes_every_in_flight_lease(self):
  job=self.q.enqueue("short_video_production", {"topic":"active"})
  claimed=self.q.claim("worker-active")
  self.assertEqual(claimed["id"],job["id"])
  self.q.pause("another worker failed", "job-other")
  stopped=self.q.get(job["id"])
  self.assertEqual(stopped["status"],"failed_terminal")
  self.assertEqual(stopped["error_code"],"worker_paused")
  self.assertIsNone(stopped["lease_token"])
  with self.assertRaises(LeaseConflict):
   self.q.finish(job["id"],"worker-active",claimed["lease_token"])
  self.assertEqual(self.q.events(job["id"])[-1]["event_type"],"worker_pause")
 def test_expired_production_lease_is_terminal_and_pauses_queue(self):
  job=self.q.enqueue("short_video_production", {"topic":"ambiguous"})
  claimed=self.q.claim("worker-lost")
  with self.q.db() as c:
   c.execute("UPDATE pipeline_jobs SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",(job["id"],))
  self.assertIsNone(self.q.claim("worker-recovery",job_type="short_video_production"))
  recovered=self.q.get(job["id"])
  self.assertEqual(recovered["status"],"failed_terminal")
  self.assertEqual(recovered["error_code"],"production_lease_expired_ambiguous")
  self.assertTrue(self.q.is_paused())
  with self.assertRaises(LeaseConflict):
   self.q.finish(job["id"],"worker-lost",claimed["lease_token"])
 def test_recover_does_not_requeue_ambiguous_production_lease(self):
  job=self.q.enqueue("short_video_production", {"topic":"ambiguous"})
  self.q.claim("worker-crashed")
  with self.q.db() as c:
   c.execute("UPDATE pipeline_jobs SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",(job["id"],))
  result=self.q.recover()
  self.assertEqual(result["requeued"],0)
  self.assertEqual(self.q.get(job["id"])["status"],"failed_terminal")
  self.assertTrue(self.q.is_paused())
 def test_operator_pause_and_resume_are_audited(self):
  self.q.pause("operator requested stop",actor="admin-7")
  events=self.q.worker_control_events()
  self.assertEqual(events[0]["event_type"],"paused")
  self.assertEqual(events[0]["actor"],"admin-7")
  with self.assertRaises(ValueError):
   self.q.resume(actor="admin-7",note="")
  self.q.resume(actor="admin-7",note="Reviewed queue and provider state")
  self.assertEqual(self.q.worker_control_events()[0]["event_type"],"resumed")
 def test_idle_worker_presence_refresh_and_stale_offline_detection(self):
  first=self.q.register_worker("idle-worker","host-a")
  self.assertEqual(first["status"],"online")
  self.assertEqual(self.q.workers(stale_after_seconds=30)[0]["status"],"online")
  with self.q.db() as c:
   c.execute("UPDATE worker_registry SET last_seen_at=? WHERE worker_id=?",
             ("2000-01-01T00:00:00+00:00","idle-worker"))
  self.assertEqual(self.q.workers(stale_after_seconds=30)[0]["status"],"offline")
  self.q.register_worker("idle-worker","host-a")
  self.assertEqual(self.q.workers(stale_after_seconds=30)[0]["status"],"online")
 def test_worker_pause_persists_until_explicit_resume(self):
  self.q.pause("provider outcome uncertain", "job-123")
  self.assertTrue(self.q.is_paused())
  self.assertEqual(self.q.worker_control()["paused_job_id"], "job-123")
  reopened=JobQueue(self.q.db_path,10)
  self.assertTrue(reopened.is_paused())
  resumed=reopened.resume(actor="operator-1",note="Checked provider history; safe to resume")
  self.assertFalse(resumed["paused"])
  self.assertIsNone(resumed["pause_reason"])
  self.assertFalse(self.q.is_paused())
  events=reopened.worker_control_events()
  self.assertEqual([e["event_type"] for e in events[:2]],["resumed","paused"])
  self.assertEqual(events[0]["actor"],"operator-1")
  self.assertIn("Checked provider history",events[0]["reason"])
 def test_generic_claim_excludes_production_jobs(self):
  production=self.q.enqueue("short_video_production", {"topic":"pipeline"})
  ordinary=self.q.enqueue("thumbnail_task", {"image":"x"})
  claimed=self.q.claim("generic-worker",exclude_job_type="short_video_production")
  self.assertEqual(claimed["id"],ordinary["id"])
  self.assertEqual(self.q.get(production["id"])["status"],"queued")

 def test_terminal_production_failure_atomically_syncs_production_run(self):
  job=self.q.enqueue("short_video_production", {"topic":"provider timeout"})
  claimed=self.q.claim("worker-a",job_type="short_video_production")
  self.create_production_run(job["id"],"failed_retriable")
  failed=self.q.fail(job["id"],"worker-a",claimed["lease_token"],
                     "provider_timeout","provider outcome uncertain",False)
  self.assertEqual(failed["status"],"failed_terminal")
  with self.q.db() as c:
   run=c.execute("SELECT * FROM production_runs WHERE job_id=?",(job["id"],)).fetchone()
  self.assertEqual(run["status"],"failed_terminal")
  self.assertEqual(run["current_stage"],"failed_terminal")
  self.assertEqual(run["error"],"provider outcome uncertain")

 def test_cancel_queued_production_atomically_syncs_production_run(self):
  job=self.q.enqueue("short_video_production", {"topic":"cancel"})
  self.create_production_run(job["id"],"queued")
  cancelled=self.q.cancel(job["id"],"operator cancelled before start")
  self.assertEqual(cancelled["status"],"cancelled")
  with self.q.db() as c:
   run=c.execute("SELECT * FROM production_runs WHERE job_id=?",(job["id"],)).fetchone()
  self.assertEqual(run["status"],"cancelled")
  self.assertEqual(run["current_stage"],"cancelled")

 def test_cancel_running_production_pauses_instead_of_claiming_clean_cancel(self):
  job=self.q.enqueue("short_video_production", {"topic":"ambiguous"})
  claimed=self.q.claim("worker-a",job_type="short_video_production")
  self.create_production_run(job["id"],"running")
  result=self.q.cancel(job["id"],"operator requested cancellation")
  self.assertEqual(result["status"],"failed_terminal")
  self.assertEqual(result["error_code"],"worker_paused")
  self.assertTrue(self.q.is_paused())
  with self.q.db() as c:
   run=c.execute("SELECT * FROM production_runs WHERE job_id=?",(job["id"],)).fetchone()
  self.assertEqual(run["status"],"failed_terminal")
  with self.assertRaises(LeaseConflict):
   self.q.finish(job["id"],"worker-a",claimed["lease_token"])

if __name__=="__main__": unittest.main()
