import sys, tempfile, unittest, time
from datetime import datetime, timedelta, timezone
from threading import Event, Thread
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import queue_store
from queue_store import JobQueue, LeaseConflict, IdempotencyConflict

class QueueTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.q=JobQueue(Path(self.tmp.name)/"test.db",10)
 def tearDown(self): self.tmp.cleanup()
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

 def test_expired_lease_rejects_heartbeat_finish_and_fail_without_reclaim(self):
  operations = ("heartbeat", "finish", "fail")
  for operation in operations:
   with self.subTest(operation=operation):
    job_type="render_"+operation
    job=self.q.enqueue(job_type,{"operation":operation})
    claimed=self.q.claim("worker-expired-"+operation,job_type=job_type)
    with self.q.db() as c:
     c.execute(
      "UPDATE pipeline_jobs SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",
      (job["id"],),
     )
    with self.assertRaises(LeaseConflict):
     if operation=="heartbeat":
      self.q.heartbeat(job["id"],"worker-expired-"+operation,claimed["lease_token"])
     elif operation=="finish":
      self.q.finish(job["id"],"worker-expired-"+operation,claimed["lease_token"])
     else:
      self.q.fail(job["id"],"worker-expired-"+operation,claimed["lease_token"],
                  "late_failure","must not be recorded",True)
    persisted=self.q.get(job["id"])
    self.assertEqual(persisted["status"],"running")
    self.assertEqual(persisted["worker_id"],"worker-expired-"+operation)
    self.assertEqual(persisted["lease_token"],claimed["lease_token"])
 def test_cancel_revokes_worker_lease(self):
  j=self.q.enqueue("render",{}); a=self.q.claim("worker-a")
  cancelled=self.q.cancel(j["id"],"operator stop")
  self.assertEqual(cancelled["status"],"cancelled")
  with self.assertRaises(LeaseConflict): self.q.finish(j["id"],"worker-a",a["lease_token"])

 def test_cancel_queued_production_updates_queue_and_production_atomically(self):
  job=self.q.enqueue("short_video_production",{"topic":"queued"})
  with self.q.db() as c:
   c.execute("""CREATE TABLE production_runs(
    job_id TEXT PRIMARY KEY,status TEXT,current_stage TEXT,error TEXT,updated_at TEXT)""")
   c.execute("INSERT INTO production_runs VALUES(?,?,?,?,?)",
             (job["id"],"queued","queued",None,"now"))
  cancelled=self.q.cancel(job["id"],"operator requested cancellation")
  self.assertEqual(cancelled["status"],"cancelled")
  self.assertEqual(cancelled["error_code"],"cancelled")
  self.assertFalse(self.q.is_paused())
  with self.q.db() as c:
   row=c.execute("SELECT status,current_stage FROM production_runs WHERE job_id=?",
                 (job["id"],)).fetchone()
  self.assertEqual(tuple(row),("cancelled","cancelled"))

 def test_cancel_running_production_marks_ambiguous_and_pauses_queue(self):
  job=self.q.enqueue("short_video_production",{"topic":"running"})
  with self.q.db() as c:
   c.execute("""CREATE TABLE production_runs(
    job_id TEXT PRIMARY KEY,status TEXT,current_stage TEXT,error TEXT,updated_at TEXT)""")
   c.execute("INSERT INTO production_runs VALUES(?,?,?,?,?)",
             (job["id"],"rendering","rendering",None,"now"))
  claim=self.q.claim("worker-running",job_type="short_video_production")
  cancelled=self.q.cancel(job["id"],"operator requested cancellation")
  self.assertEqual(cancelled["status"],"cancelled")
  self.assertEqual(cancelled["error_code"],"cancelled_external_outcome_ambiguous")
  self.assertIn("reconciled manually",cancelled["error_message"])
  self.assertTrue(self.q.is_paused())
  self.assertIsNone(cancelled["lease_token"])
  with self.q.db() as c:
   row=c.execute("SELECT status,current_stage,error FROM production_runs WHERE job_id=?",
                 (job["id"],)).fetchone()
  self.assertEqual(row["status"],"cancelled")
  self.assertEqual(row["current_stage"],"cancelled_ambiguous")
  self.assertIn("external outcome",row["error"])
  with self.assertRaises(LeaseConflict):
   self.q.finish(job["id"],"worker-running",claim["lease_token"])

 def test_cancel_rejects_production_after_review_handoff(self):
  job=self.q.enqueue("short_video_production",{"topic":"review"})
  claim=self.q.claim("worker-review",job_type="short_video_production")
  self.q.finish(job["id"],"worker-review",claim["lease_token"])
  with self.assertRaisesRegex(ValueError,"review handoff"):
   self.q.cancel(job["id"])
  self.assertEqual(self.q.get(job["id"])["status"],"review_pending")

 def test_graceful_worker_shutdown_is_persisted_as_offline_not_stale(self):
  registration=self.q.register_worker("worker-clean","host-a")
  self.assertTrue(self.q.mark_worker_offline("worker-clean",registration["generation_token"]))
  self.assertEqual(self.q.workers()[0]["status"],"offline")
  self.assertFalse(self.q.mark_worker_offline("missing-worker"))


 def test_worker_registry_reports_heartbeat_age_and_stale_status(self):
  self.q.register_worker("worker-live","host-live")
  live=self.q.workers(stale_after_seconds=30)[0]
  self.assertEqual(live["status"],"online")
  self.assertGreaterEqual(live["heartbeat_age_seconds"],0)
  self.assertEqual(live["stale_after_seconds"],30)
  with self.q.db() as c:
   c.execute("UPDATE worker_registry SET last_seen_at='2000-01-01T00:00:00+00:00' WHERE worker_id='worker-live'")
  stale=self.q.workers(stale_after_seconds=30)[0]
  self.assertEqual(stale["status"],"stale")
  self.assertGreater(stale["heartbeat_age_seconds"],30)

 def test_explicitly_offline_worker_is_not_reported_as_stale(self):
  registration=self.q.register_worker("worker-clean","host-a")
  self.q.mark_worker_offline("worker-clean",registration["generation_token"])
  with self.q.db() as c:
   c.execute("UPDATE worker_registry SET last_seen_at='2000-01-01T00:00:00+00:00' WHERE worker_id='worker-clean'")
  worker=self.q.workers(stale_after_seconds=30)[0]
  self.assertEqual(worker["status"],"offline")
  self.assertGreater(worker["heartbeat_age_seconds"],30)

 def test_recover_expired_lease(self):
  j=self.q.enqueue("render",{}); a=self.q.claim("worker-a")
  with self.q.db() as c:
   c.execute("UPDATE pipeline_jobs SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",(j["id"],))
  result=self.q.recover()
  self.assertEqual(result["requeued"],1)
  self.assertEqual(self.q.get(j["id"])["status"],"queued")
 def test_concurrent_recovery_reclaims_expired_lease_once(self):
  job=self.q.enqueue("render",{"topic":"concurrent-recovery"})
  claimed=self.q.claim("worker-lost")
  with self.q.db() as c:
   c.execute(
    "UPDATE pipeline_jobs SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",
    (job["id"],),
   )
  with ThreadPoolExecutor(max_workers=8) as pool:
   results=list(pool.map(lambda _:self.q.recover(),range(8)))
  self.assertEqual(sum(result["requeued"] for result in results),1)
  self.assertEqual(sum(result["terminal"] for result in results),0)
  self.assertEqual(self.q.get(job["id"])["status"],"queued")
  events=[event for event in self.q.events(job["id"]) if event["event_type"]=="lease_expired"]
  self.assertEqual(len(events),1)
  self.assertEqual(events[0]["worker_id"],"worker-lost")
  self.assertEqual(events[0]["details"]["expired_worker_id"],"worker-lost")
  with self.assertRaises(LeaseConflict):
   self.q.finish(job["id"],"worker-lost",claimed["lease_token"])

 def test_heartbeat_and_recovery_fence_stale_worker_after_reclaim(self):
  job=self.q.enqueue("render",{"topic":"heartbeat-recovery"})
  first=self.q.claim("worker-first")
  renewed=self.q.heartbeat(job["id"],"worker-first",first["lease_token"])
  self.assertGreater(renewed["lease_expires_at"],first["lease_expires_at"])
  self.assertEqual(self.q.recover()["requeued"],0)
  with self.q.db() as c:
   c.execute(
    "UPDATE pipeline_jobs SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",
    (job["id"],),
   )
  self.assertEqual(self.q.recover()["requeued"],1)
  with self.assertRaises(LeaseConflict):
   self.q.heartbeat(job["id"],"worker-first",first["lease_token"])
  second=self.q.claim("worker-second")
  self.assertEqual(second["id"],job["id"])
  with self.assertRaises(LeaseConflict):
   self.q.heartbeat(job["id"],"worker-first",first["lease_token"])
  current=self.q.get(job["id"])
  self.assertEqual(current["status"],"running")
  self.assertEqual(current["worker_id"],"worker-second")
  self.assertEqual(current["lease_token"],second["lease_token"])
  self.assertEqual(
   len([event for event in self.q.events(job["id"]) if event["event_type"]=="heartbeat"]),1
  )

 def test_heartbeat_checks_lease_time_after_waiting_for_write_lock(self):
  base=datetime(2030,1,1,tzinfo=timezone.utc)
  clock={"value":base}
  original_now=queue_store.now
  queue_store.now=lambda:clock["value"]
  job=self.q.enqueue("render",{"topic":"lock-clock"})
  claimed=self.q.claim("worker-clock")
  lock_context=self.q.db()
  lock_connection=lock_context.__enter__()
  thread_result={}
  started=Event()
  try:
   lock_connection.execute("BEGIN IMMEDIATE")
   def heartbeat():
    started.set()
    try:
     thread_result["result"]=self.q.heartbeat(job["id"],"worker-clock",claimed["lease_token"])
    except Exception as exc:
     thread_result["error"]=exc
   thread=Thread(target=heartbeat)
   thread.start()
   self.assertTrue(started.wait(1))
   time.sleep(0.05)
   clock["value"]=base+timedelta(seconds=11)
   lock_connection.commit()
   thread.join(2)
   self.assertFalse(thread.is_alive())
   self.assertIsInstance(thread_result.get("error"),LeaseConflict)
   persisted=self.q.get(job["id"])
   self.assertEqual(persisted["lease_token"],claimed["lease_token"])
   self.assertEqual(
    len([event for event in self.q.events(job["id"]) if event["event_type"]=="heartbeat"]),0
   )
  finally:
   if lock_connection.in_transaction:
    lock_connection.rollback()
   lock_context.__exit__(None,None,None)
   queue_store.now=original_now

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
 def test_idle_worker_presence_refresh_and_stale_detection(self):
  first=self.q.register_worker("idle-worker","host-a")
  self.assertEqual(first["status"],"online")
  self.assertEqual(self.q.workers(stale_after_seconds=30)[0]["status"],"online")
  with self.q.db() as c:
   c.execute("UPDATE worker_registry SET last_seen_at=? WHERE worker_id=?",
             ("2000-01-01T00:00:00+00:00","idle-worker"))
  self.assertEqual(self.q.workers(stale_after_seconds=30)[0]["status"],"stale")
  self.q.register_worker("idle-worker","host-a")
  self.assertEqual(self.q.workers(stale_after_seconds=30)[0]["status"],"online")
 def test_stale_worker_generation_cannot_mark_restarted_process_offline(self):
  first=self.q.register_worker("reused-worker","host-a")
  second=self.q.register_worker("reused-worker","host-a")
  self.assertNotEqual(first["generation_token"],second["generation_token"])
  self.assertFalse(self.q.mark_worker_offline("reused-worker",first["generation_token"]))
  current=self.q.workers()[0]
  self.assertEqual(current["status"],"online")
  self.assertEqual(current["generation_token"],second["generation_token"])
  self.assertTrue(self.q.mark_worker_offline("reused-worker",second["generation_token"]))
  self.assertEqual(self.q.workers()[0]["status"],"offline")
 def test_worker_offline_requires_generation_token(self):
  current=self.q.register_worker("generation-required","host-b")
  self.assertFalse(self.q.mark_worker_offline("generation-required"))
  self.assertEqual(self.q.workers()[0]["generation_token"],current["generation_token"])
  self.assertEqual(self.q.workers()[0]["status"],"online")

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

 def test_lease_duration_rejects_ambiguous_or_unbounded_values(self):
  for invalid in (True, False, 1.5, "60", 0, -1, 3601, 10**9):
   with self.subTest(invalid=invalid):
    with self.assertRaisesRegex(ValueError, "lease_seconds"):
     JobQueue(Path(self.tmp.name)/"invalid.db", invalid)
  self.assertEqual(self.q.lease_seconds, 10)


 def test_expired_lease_recovery_paths_share_terminal_and_audit_semantics(self):
  for path in ("claim","recover"):
   with self.subTest(path=path):
    job=self.q.enqueue("render",{"path":path},max_attempts=1)
    claimed=self.q.claim("worker-"+path)
    with self.q.db() as c:
     c.execute("UPDATE pipeline_jobs SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",(job["id"],))
    if path=="claim":
     self.q.claim("worker-recovery",job_type="other")
    else:
     result=self.q.recover()
     self.assertEqual(result,{"requeued":0,"terminal":1})
    resolved=self.q.get(job["id"])
    self.assertEqual(resolved["status"],"failed_terminal")
    self.assertEqual(resolved["error_code"],"lease_expired")
    event=self.q.events(job["id"])[-1]
    self.assertEqual(event["event_type"],"lease_expired")
    self.assertEqual(event["details"]["resolution"],"attempts_exhausted")
    with self.assertRaises(LeaseConflict):
     self.q.finish(job["id"],"worker-"+path,claimed["lease_token"])

 def test_expired_production_recovery_updates_run_and_requires_manual_reconciliation(self):
  job=self.q.enqueue("short_video_production",{"topic":"uncertain"})
  with self.q.db() as c:
   c.execute("""CREATE TABLE production_runs(
    job_id TEXT PRIMARY KEY,status TEXT,current_stage TEXT,error TEXT,updated_at TEXT)""")
   c.execute("INSERT INTO production_runs VALUES(?,?,?,?,?)",
             (job["id"],"rendering","rendering",None,"now"))
  self.q.claim("worker-production")
  with self.q.db() as c:
   c.execute("UPDATE pipeline_jobs SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",(job["id"],))
  result=self.q.recover()
  self.assertEqual(result,{"requeued":0,"terminal":1})
  resolved=self.q.get(job["id"])
  self.assertEqual(resolved["status"],"failed_terminal")
  self.assertEqual(resolved["error_code"],"production_lease_expired_ambiguous")
  event=self.q.events(job["id"])[-1]
  self.assertEqual(event["event_type"],"lease_expired")
  self.assertEqual(event["details"]["resolution"],"manual_reconciliation_required")
  with self.q.db() as c:
   run=c.execute("SELECT status,current_stage FROM production_runs WHERE job_id=?",(job["id"],)).fetchone()
  self.assertEqual(tuple(run),("failed_terminal","lease_expired_ambiguous"))
  self.assertTrue(self.q.is_paused())


 def test_operator_reconciliation_authorizes_one_retry_only_with_evidence(self):
  job=self.q.enqueue("short_video_production",{"topic":"ambiguous"},max_attempts=1)
  with self.q.db() as c:
   c.execute("""CREATE TABLE production_runs(
    job_id TEXT PRIMARY KEY,status TEXT,current_stage TEXT,error TEXT,updated_at TEXT)""")
   c.execute("INSERT INTO production_runs VALUES(?,?,?,?,?)",
             (job["id"],"failed_terminal","lease_expired_ambiguous","uncertain","now"))
  self.q.claim("worker-lost")
  with self.q.db() as c:
   c.execute("UPDATE pipeline_jobs SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",(job["id"],))
  self.q.recover()
  self.assertEqual(len(self.q.ambiguous_production_jobs()),1)
  with self.assertRaisesRegex(ValueError,"evidence_reference"):
   self.q.reconcile_production_retry(job["id"],"operator-1","","checked")
  reconciled=self.q.reconcile_production_retry(
   job["id"],"operator-1","provider-console:request-123",
   "Provider console confirms request was rejected before execution")
  self.assertEqual(reconciled["status"],"failed_retriable")
  self.assertEqual(reconciled["attempt"],1)
  self.assertEqual(reconciled["max_attempts"],2)
  self.assertTrue(self.q.is_paused())
  with self.q.db() as c:
   run=c.execute("SELECT status,current_stage FROM production_runs WHERE job_id=?",
                 (job["id"],)).fetchone()
  self.assertEqual(tuple(run),("queued","operator_reconciled_retry_authorized"))
  events=self.q.production_reconciliation_events(job["id"])
  self.assertEqual(len(events),1)
  self.assertEqual(events[0]["operator_id"],"operator-1")
  self.assertEqual(events[0]["evidence_reference"],"provider-console:request-123")
  with self.assertRaisesRegex(ValueError,"not awaiting"):
   self.q.reconcile_production_retry(
    job["id"],"operator-1","provider-console:request-123","duplicate action")
  with self.q.db() as c:
   with self.assertRaises(Exception):
    c.execute("UPDATE production_reconciliation_events SET note='tampered' WHERE job_id=?",
              (job["id"],))

 def test_reconciliation_rejects_nonproduction_and_unambiguous_jobs(self):
  ordinary=self.q.enqueue("render",{})
  with self.assertRaises(Exception):
   self.q.reconcile_production_retry(ordinary["id"],"operator","evidence","note")
  production=self.q.enqueue("short_video_production",{"topic":"normal"})
  with self.assertRaisesRegex(ValueError,"not awaiting"):
   self.q.reconcile_production_retry(production["id"],"operator","evidence","note")

if __name__=="__main__": unittest.main()
