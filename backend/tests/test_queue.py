import sys, tempfile, unittest, time
from datetime import datetime, timedelta, timezone
from threading import Event, Thread
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
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
  ambiguous=self.q.ambiguous_production_jobs()
  self.assertEqual(len(ambiguous),1)
  self.assertEqual(ambiguous[0]["id"],job["id"])
  with self.assertRaisesRegex(ValueError,"evidence_reference"):
   self.q.reconcile_production_retry(job["id"],"operator-1","","checked")
  reconciled=self.q.reconcile_production_retry(
   job["id"],"operator-1","provider-console:request-456",
   "Provider console confirms the request was not executed")
  self.assertEqual(reconciled["status"],"failed_retriable")
  self.assertEqual(reconciled["error_code"],"operator_reconciled_no_side_effect")
  self.assertTrue(self.q.is_paused())
  with self.q.db() as c:
   run=c.execute("SELECT status,current_stage FROM production_runs WHERE job_id=?",
                 (job["id"],)).fetchone()
  self.assertEqual(tuple(run),("queued","operator_reconciled_retry_authorized"))
  audit=self.q.production_reconciliation_events(job["id"])
  self.assertEqual(len(audit),1)
  self.assertEqual(audit[0]["previous_status"],"cancelled")
  self.assertEqual(audit[0]["resulting_status"],"failed_retriable")

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

 def test_worker_restart_racing_expired_lease_recovery_preserves_new_generation(self):
  old=self.q.register_worker("race-worker","host-a")
  job=self.q.enqueue("render",{"topic":"restart-recovery-race"})
  claimed=self.q.claim("race-worker","host-a",generation_token=old["generation_token"])
  with self.q.db() as c:
   c.execute("UPDATE pipeline_jobs SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",(job["id"],))
  gate=Event()
  def restart():
   gate.wait()
   return self.q.register_worker("race-worker","host-a")
  def recover():
   gate.wait()
   return self.q.recover()
  with ThreadPoolExecutor(max_workers=2) as pool:
   restarted=pool.submit(restart)
   recovery=pool.submit(recover)
   gate.set()
   current=restarted.result()
   result=recovery.result()
  self.assertNotEqual(old["generation_token"],current["generation_token"])
  self.assertEqual(result["requeued"],1)
  self.assertEqual(self.q.get(job["id"])["status"],"queued")
  self.assertFalse(self.q.mark_worker_offline("race-worker",old["generation_token"]))
  registry=self.q.workers()[0]
  self.assertEqual(registry["generation_token"],current["generation_token"])
  self.assertEqual(registry["status"],"online")
  events=[event for event in self.q.events(job["id"]) if event["event_type"]=="lease_expired"]
  self.assertEqual(len(events),1)
  replacement_claim=self.q.claim("race-worker","host-a",generation_token=current["generation_token"])
  self.assertEqual(replacement_claim["id"],job["id"])
  with self.assertRaises(LeaseConflict):
   self.q.heartbeat(job["id"],"race-worker",claimed["lease_token"],old["generation_token"])

 def test_production_restart_racing_expired_lease_recovery_never_requeues_ambiguous_work(self):
  old=self.q.register_worker("production-restart-worker","host-a")
  job=self.q.enqueue("short_video_production",{"topic":"restart-ambiguous"})
  with self.q.db() as c:
   c.execute("""CREATE TABLE production_runs(
    job_id TEXT PRIMARY KEY,status TEXT,current_stage TEXT,error TEXT,updated_at TEXT)""")
   c.execute("INSERT INTO production_runs VALUES(?,?,?,?,?)",
             (job["id"],"rendering","rendering",None,"now"))
  claimed=self.q.claim("production-restart-worker","host-a",
                       job_type="short_video_production",
                       generation_token=old["generation_token"])
  with self.q.db() as c:
   c.execute("UPDATE pipeline_jobs SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",
             (job["id"],))
  gate=Event()
  def restart():
   gate.wait()
   return self.q.register_worker("production-restart-worker","host-a")
  def recover():
   gate.wait()
   return self.q.recover()
  with ThreadPoolExecutor(max_workers=2) as pool:
   restarted=pool.submit(restart)
   recovery=pool.submit(recover)
   gate.set()
   current=restarted.result()
   result=recovery.result()
  self.assertNotEqual(old["generation_token"],current["generation_token"])
  # Whichever transaction wins must quarantine the in-flight provider call.
  # Recovery-first records lease expiry; restart-first records generation replacement.
  self.assertIn(result,({"requeued":0,"terminal":0},{"requeued":0,"terminal":1}))
  persisted=self.q.get(job["id"])
  self.assertEqual(persisted["status"],"failed_terminal")
  self.assertIn(persisted["error_code"],(
   "production_lease_expired_ambiguous",
   "production_pause_external_outcome_ambiguous"))
  self.assertTrue(self.q.is_paused())
  with self.q.db() as c:
   run=c.execute("SELECT status,current_stage FROM production_runs WHERE job_id=?",
                 (job["id"],)).fetchone()
  self.assertEqual(tuple(run),("failed_terminal",
   "lease_expired_ambiguous" if persisted["error_code"]=="production_lease_expired_ambiguous"
   else "pause_outcome_ambiguous"))
  self.assertFalse(self.q.mark_worker_offline("production-restart-worker",
                                               old["generation_token"]))
  registry=next(row for row in self.q.workers()
                if row["worker_id"]=="production-restart-worker")
  self.assertEqual(registry["generation_token"],current["generation_token"])
  self.assertEqual(registry["status"],"online")
  with self.assertRaises(LeaseConflict):
   self.q.finish(job["id"],"production-restart-worker",claimed["lease_token"],
                 generation_token=old["generation_token"])

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

 def test_cancel_captures_timestamp_after_waiting_for_write_lock(self):
  base=datetime(2030,1,1,tzinfo=timezone.utc)
  clock={"value":base}
  original_now=queue_store.now
  queue_store.now=lambda:clock["value"]
  job=self.q.enqueue("render",{"topic":"cancel-lock-clock"})
  lock_context=self.q.db()
  lock_connection=lock_context.__enter__()
  thread_result={}
  started=Event()
  try:
   lock_connection.execute("BEGIN IMMEDIATE")
   def cancel():
    started.set()
    try:
     thread_result["result"]=self.q.cancel(job["id"],"operator stop")
    except Exception as exc:
     thread_result["error"]=exc
   thread=Thread(target=cancel)
   thread.start()
   self.assertTrue(started.wait(1))
   time.sleep(0.05)
   clock["value"]=base+timedelta(seconds=11)
   lock_connection.commit()
   thread.join(2)
   self.assertFalse(thread.is_alive())
   self.assertNotIn("error",thread_result)
   persisted=self.q.get(job["id"])
   expected=queue_store.stamp(base+timedelta(seconds=11))
   self.assertEqual(persisted["updated_at"],expected)
   cancelled_events=[event for event in self.q.events(job["id"])
                     if event["event_type"]=="cancelled"]
   self.assertEqual(len(cancelled_events),1)
   self.assertEqual(cancelled_events[0]["created_at"],expected)
  finally:
   if lock_connection.in_transaction:
    lock_connection.rollback()
   lock_context.__exit__(None,None,None)
   queue_store.now=original_now

 def test_reconciliation_captures_timestamp_after_waiting_for_write_lock(self):
  job=self.q.enqueue("short_video_production",{"topic":"reconcile-lock-clock"})
  self.q.claim("worker-reconcile-clock")
  self.q.pause("provider outcome uncertain")
  base=datetime(2030,1,1,tzinfo=timezone.utc)
  clock={"value":base}
  original_now=queue_store.now
  queue_store.now=lambda:clock["value"]
  lock_context=self.q.db()
  lock_connection=lock_context.__enter__()
  thread_result={}
  started=Event()
  try:
   lock_connection.execute("BEGIN IMMEDIATE")
   def reconcile():
    started.set()
    try:
     thread_result["result"]=self.q.reconcile_production_retry(
      job["id"],"operator-clock","provider-console:confirmed-not-run",
      "Provider confirms no side effect")
    except Exception as exc:
     thread_result["error"]=exc
   thread=Thread(target=reconcile)
   thread.start()
   self.assertTrue(started.wait(1))
   time.sleep(0.05)
   clock["value"]=base+timedelta(seconds=11)
   lock_connection.commit()
   thread.join(2)
   self.assertFalse(thread.is_alive())
   self.assertNotIn("error",thread_result)
   persisted=self.q.get(job["id"])
   expected=queue_store.stamp(base+timedelta(seconds=11))
   self.assertEqual(persisted["updated_at"],expected)
   self.assertEqual(persisted["available_at"],expected)
   reconciliation=self.q.production_reconciliation_events(job["id"])
   self.assertEqual(len(reconciliation),1)
   self.assertEqual(reconciliation[0]["created_at"],expected)
   audit=[event for event in self.q.events(job["id"])
          if event["event_type"]=="operator_reconciliation"]
   self.assertEqual(len(audit),1)
   self.assertEqual(audit[0]["created_at"],expected)
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
 def test_pause_revokes_active_production_and_queues_ambiguous_reconciliation(self):
  job=self.q.enqueue("short_video_production", {"topic":"active"})
  claimed=self.q.claim("worker-active")
  self.assertEqual(claimed["id"],job["id"])
  self.q.pause("another worker failed", "job-other")
  stopped=self.q.get(job["id"])
  self.assertEqual(stopped["status"],"failed_terminal")
  self.assertEqual(stopped["error_code"],"production_pause_external_outcome_ambiguous")
  self.assertIsNone(stopped["lease_token"])
  with self.assertRaises(LeaseConflict):
   self.q.finish(job["id"],"worker-active",claimed["lease_token"])
  self.assertEqual(self.q.events(job["id"])[-1]["event_type"],"worker_pause")
  ambiguous=self.q.ambiguous_production_jobs()
  self.assertEqual([item["id"] for item in ambiguous],[job["id"]])
  with self.assertRaisesRegex(ValueError,"evidence_reference"):
   self.q.reconcile_production_retry(job["id"],"operator-2","","provider checked")
  reconciled=self.q.reconcile_production_retry(
   job["id"],"operator-2","provider-console:pause-request-9",
   "Provider console confirms the in-flight operation had no side effect")
  self.assertEqual(reconciled["status"],"failed_retriable")
  self.assertEqual(reconciled["error_code"],"operator_reconciled_no_side_effect")
  self.assertTrue(self.q.is_paused())
  audit=self.q.production_reconciliation_events(job["id"])
  self.assertEqual(len(audit),1)
  self.assertEqual(audit[0]["previous_status"],"failed_terminal")
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
 def test_claim_and_lease_mutations_are_fenced_by_worker_generation(self):
  first=self.q.register_worker("generation-worker","host-a")
  job=self.q.enqueue("render",{"generation":"test"})
  claimed=self.q.claim("generation-worker","host-a",generation_token=first["generation_token"])
  self.assertIsNotNone(claimed)
  self.assertEqual(self.q.workers()[0]["generation_token"],first["generation_token"])
  second=self.q.register_worker("generation-worker","host-a")
  self.assertNotEqual(first["generation_token"],second["generation_token"])
  with self.assertRaises(LeaseConflict):
   self.q.claim("generation-worker","host-a",generation_token=first["generation_token"])
  with self.assertRaises(LeaseConflict):
   self.q.heartbeat(job["id"],"generation-worker",claimed["lease_token"],first["generation_token"])
  with self.assertRaises(LeaseConflict):
   self.q.finish(job["id"],"generation-worker",claimed["lease_token"],generation_token=first["generation_token"])
  with self.assertRaises(LeaseConflict):
   self.q.fail(job["id"],"generation-worker",claimed["lease_token"],"old_process","stale",False,generation_token=first["generation_token"])
  self.assertEqual(self.q.get(job["id"])["status"],"running")

 def test_worker_offline_requires_generation_token(self):
  current=self.q.register_worker("generation-required","host-b")
  self.assertFalse(self.q.mark_worker_offline("generation-required"))
  self.assertEqual(self.q.workers()[0]["generation_token"],current["generation_token"])
  self.assertEqual(self.q.workers()[0]["status"],"online")

 def test_registered_worker_cannot_mutate_queue_without_generation_token(self):
  registration=self.q.register_worker("token-required-worker","host-a")
  job=self.q.enqueue("render",{"topic":"missing-generation-token"})
  claimed=self.q.claim("token-required-worker","host-a",generation_token=registration["generation_token"])
  with self.assertRaises(LeaseConflict):
   self.q.claim("token-required-worker","host-a")
  with self.assertRaises(LeaseConflict):
   self.q.heartbeat(job["id"],"token-required-worker",claimed["lease_token"])
  with self.assertRaises(LeaseConflict):
   self.q.finish(job["id"],"token-required-worker",claimed["lease_token"])
  with self.assertRaises(LeaseConflict):
   self.q.fail(job["id"],"token-required-worker",claimed["lease_token"],"stale","missing generation",False)
  with self.assertRaises(LeaseConflict):
   self.q.pause("missing generation",worker_id="token-required-worker")
  self.assertFalse(self.q.is_paused())
  self.assertEqual(self.q.get(job["id"])["status"],"running")
  self.assertEqual(self.q.workers()[0]["generation_token"],registration["generation_token"])

 def test_stale_worker_generation_cannot_pause_replacement_process(self):
  first=self.q.register_worker("pause-worker","host-a")
  second=self.q.register_worker("pause-worker","host-a")
  self.assertNotEqual(first["generation_token"],second["generation_token"])
  with self.assertRaises(LeaseConflict):
   self.q.pause("late error from old process",worker_id="pause-worker",generation_token=first["generation_token"])
  self.assertFalse(self.q.is_paused())
  self.q.pause("current process detected uncertainty",worker_id="pause-worker",generation_token=second["generation_token"])
  self.assertTrue(self.q.is_paused())
  self.assertEqual(self.q.worker_control()["pause_reason"],"current process detected uncertainty")

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


 def test_concurrent_operator_reconciliation_authorizes_only_one_retry(self):
  job=self.q.enqueue("short_video_production",{"topic":"concurrent-ambiguous"},max_attempts=1)
  with self.q.db() as c:
   c.execute("""CREATE TABLE production_runs(
    job_id TEXT PRIMARY KEY,status TEXT,current_stage TEXT,error TEXT,updated_at TEXT)""")
   c.execute("INSERT INTO production_runs VALUES(?,?,?,?,?)",
             (job["id"],"failed_terminal","lease_expired_ambiguous","uncertain","now"))
  self.q.claim("worker-lost")
  with self.q.db() as c:
   c.execute("UPDATE pipeline_jobs SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",
             (job["id"],))
  self.q.recover()
  barrier=__import__("threading").Barrier(2)
  def reconcile(operator):
   barrier.wait()
   try:
    result=self.q.reconcile_production_retry(
     job["id"],operator,"provider-console:confirmed-not-run",
     "Provider confirms no request was executed")
    return ("success",result["status"])
   except ValueError as exc:
    return ("rejected",str(exc))
  with ThreadPoolExecutor(max_workers=2) as pool:
   outcomes=list(pool.map(reconcile,("operator-a","operator-b")))
  self.assertEqual(sum(1 for outcome in outcomes if outcome[0]=="success"),1)
  self.assertEqual(sum(1 for outcome in outcomes if outcome[0]=="rejected"),1)
  self.assertEqual(self.q.get(job["id"])["status"],"failed_retriable")
  self.assertTrue(self.q.is_paused())
  events=self.q.production_reconciliation_events(job["id"])
  self.assertEqual(len(events),1)
  self.assertIn(events[0]["operator_id"],("operator-a","operator-b"))
  audit=[event for event in self.q.events(job["id"])
         if event["event_type"]=="operator_reconciliation"]
  self.assertEqual(len(audit),1)

 def test_re_registering_worker_with_active_production_lease_quarantines_job(self):
     registration = self.q.register_worker("replaced-active-worker", "host-a")
     job = self.q.enqueue("short_video_production", {"topic": "generation-replacement"})
     claimed = self.q.claim(
         "replaced-active-worker", "host-a",
         job_type="short_video_production",
         generation_token=registration["generation_token"],
     )
     self.assertEqual(claimed["id"], job["id"])

     replacement = self.q.register_worker("replaced-active-worker", "host-a")

     self.assertNotEqual(
         registration["generation_token"], replacement["generation_token"]
     )
     self.assertTrue(self.q.is_paused())
     quarantined = self.q.get(job["id"])
     self.assertEqual(quarantined["status"], "failed_terminal")
     self.assertEqual(
         quarantined["error_code"],
         "production_pause_external_outcome_ambiguous",
     )
     self.assertIsNone(quarantined["lease_token"])
     self.assertEqual(
         [item["id"] for item in self.q.ambiguous_production_jobs()],
         [job["id"]],
     )
     with self.assertRaises(LeaseConflict):
         self.q.heartbeat(
             job["id"], "replaced-active-worker", claimed["lease_token"],
             registration["generation_token"],
         )
     self.assertIsNone(self.q.claim(
         "replaced-active-worker", "host-a",
         job_type="short_video_production",
         generation_token=replacement["generation_token"],
     ))
     worker = self.q.workers()[0]
     self.assertEqual(worker["generation_token"], replacement["generation_token"])
     self.assertEqual(worker["status"], "online")



 def test_production_pause_audit_uses_serialized_transition_timestamp(self):
  job=self.q.enqueue("short_video_production",{"topic":"pause-audit-timestamp"})
  claimed=self.q.claim("pause-audit-worker",job_type="short_video_production")
  transition_time="2030-04-05T06:07:08+00:00"
  with self.q.db() as c:
   c.execute("BEGIN IMMEDIATE")
   self.q._pause_production_in_transaction(
    c,"controlled pause",job["id"],transition_time,actor="system")
   c.commit()
  event=[item for item in self.q.events(job["id"])
         if item["event_type"]=="worker_pause"][-1]
  control_event=self.q.worker_control_events(1)[0]
  self.assertEqual(event["created_at"],transition_time)
  self.assertEqual(control_event["created_at"],transition_time)
  self.assertEqual(self.q.get(job["id"])["updated_at"],transition_time)

 def test_recover_counts_all_production_jobs_terminalized_by_global_pause(self):
  expired=self.q.enqueue("short_video_production",{"topic":"expired-production"})
  active=self.q.enqueue("short_video_production",{"topic":"active-production"})
  self.q.claim("worker-expired",job_type="short_video_production")
  self.q.claim("worker-active",job_type="short_video_production")
  with self.q.db() as c:
   c.execute("UPDATE pipeline_jobs SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",
             (expired["id"],))
  result=self.q.recover()
  self.assertEqual(result,{"requeued":0,"terminal":2})
  for job in (expired,active):
   persisted=self.q.get(job["id"])
   self.assertEqual(persisted["status"],"failed_terminal")
   self.assertEqual(persisted["error_code"],"production_pause_external_outcome_ambiguous"
                    if job["id"]==active["id"] else "production_lease_expired_ambiguous")

 def test_expired_lease_audit_uses_serialized_recovery_timestamp(self):
  job=self.q.enqueue("render",{"topic":"lease-audit-timestamp"})
  self.q.claim("worker-timestamp")
  with self.q.db() as c:
   c.execute("UPDATE pipeline_jobs SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",
             (job["id"],))
  decision=datetime(2031,2,3,4,5,6,tzinfo=timezone.utc)
  later=decision+timedelta(seconds=11)
  with patch.object(queue_store,"now",side_effect=[decision,later]):
   result=self.q.recover()
  self.assertEqual(result,{"requeued":1,"terminal":0})
  persisted=self.q.get(job["id"])
  event=[item for item in self.q.events(job["id"]) if item["event_type"]=="lease_expired"][-1]
  self.assertEqual(persisted["updated_at"],decision.isoformat())
  self.assertEqual(event["created_at"],decision.isoformat())

 def test_operator_reconciliation_job_event_uses_locked_decision_timestamp(self):
  job=self.q.enqueue("short_video_production",{"topic":"reconcile-audit-time"})
  claim=self.q.claim("worker-reconcile-audit",job_type="short_video_production")
  self.q.cancel(job["id"],"test ambiguous cancellation")
  decision=datetime(2032,3,4,5,6,7,tzinfo=timezone.utc)
  later=decision+timedelta(seconds=13)
  with patch.object(queue_store,"now",side_effect=[decision,later]):
   result=self.q.reconcile_production_retry(
    job["id"],"operator-2","provider-console:confirmed-no-request",
    "Provider confirms no side effect")
  self.assertEqual(result["status"],"failed_retriable")
  event=[item for item in self.q.events(job["id"])
         if item["event_type"]=="operator_reconciliation"][-1]
  audit=self.q.production_reconciliation_events(job["id"])[-1]
  self.assertEqual(event["created_at"],decision.isoformat())
  self.assertEqual(audit["created_at"],decision.isoformat())
  self.assertEqual(result["updated_at"],decision.isoformat())

 def test_cancel_job_audit_uses_serialized_transition_timestamp(self):
  job=self.q.enqueue("short_video_production",{"topic":"cancel-audit-timestamp"})
  decision=datetime(2033,4,5,6,7,8,tzinfo=timezone.utc)
  later=decision+timedelta(seconds=17)
  with patch.object(queue_store,"now",side_effect=[decision,later]):
   result=self.q.cancel(job["id"],"operator requested cancellation")
  event=[item for item in self.q.events(job["id"])
         if item["event_type"]=="cancelled"][-1]
  self.assertEqual(result["updated_at"],decision.isoformat())
  self.assertEqual(event["created_at"],decision.isoformat())

 def test_worker_lifecycle_events_reuse_transition_timestamp(self):
  completed=self.q.enqueue("render",{"topic":"finish-event-time"})
  finished=self.q.claim("worker-finish-event")
  decision=datetime(2034,5,6,7,8,9,tzinfo=timezone.utc)
  later=decision+timedelta(seconds=19)
  with patch.object(queue_store,"now",side_effect=[decision,later]):
   self.q.finish(completed["id"],"worker-finish-event",finished["lease_token"],{"ok":True})
  finish_event=[item for item in self.q.events(completed["id"])
                if item["event_type"]=="completed"][-1]
  self.assertEqual(self.q.get(completed["id"])["updated_at"],decision.isoformat())
  self.assertEqual(finish_event["created_at"],decision.isoformat())

  failed=self.q.enqueue("render",{"topic":"fail-event-time"})
  claimed=self.q.claim("worker-fail-event")
  decision=datetime(2034,5,6,7,9,9,tzinfo=timezone.utc)
  later=decision+timedelta(seconds=23)
  with patch.object(queue_store,"now",side_effect=[decision,later]):
   self.q.fail(failed["id"],"worker-fail-event",claimed["lease_token"],
               "render_failed","controlled failure",retryable=True)
  fail_event=[item for item in self.q.events(failed["id"])
              if item["event_type"]=="failed"][-1]
  self.assertEqual(self.q.get(failed["id"])["updated_at"],decision.isoformat())
  self.assertEqual(fail_event["created_at"],decision.isoformat())

if __name__=="__main__": unittest.main()
