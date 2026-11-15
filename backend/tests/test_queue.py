import sqlite3, sys, tempfile, unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from queue_store import JobQueue, LeaseConflict, IdempotencyConflict

class QueueTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.q=JobQueue(Path(self.tmp.name)/"test.db",10)
 def tearDown(self): self.tmp.cleanup()

 def test_worker_registry_instance_token_migrates_existing_database(self):
  legacy_path=Path(self.tmp.name)/"legacy.db"
  with sqlite3.connect(legacy_path) as c:
   c.execute("CREATE TABLE worker_registry(worker_id TEXT PRIMARY KEY, hostname TEXT, last_seen_at TEXT NOT NULL, status TEXT NOT NULL)")
   c.execute("INSERT INTO worker_registry VALUES('legacy-worker','old-host','2026-01-01T00:00:00+00:00','online')")
  migrated=JobQueue(legacy_path,10)
  with migrated.db() as c:
   columns={row["name"] for row in c.execute("PRAGMA table_info(worker_registry)")}
   row=c.execute("SELECT worker_id,instance_token FROM worker_registry").fetchone()
  self.assertIn("instance_token",columns)
  self.assertEqual(row["worker_id"],"legacy-worker")
  self.assertIsNone(row["instance_token"])

 def test_stale_worker_instance_cannot_mark_restarted_instance_offline(self):
  self.q.register_worker("worker-reused","host-a","instance-old")
  self.q.register_worker("worker-reused","host-b","instance-new")
  self.assertFalse(self.q.mark_worker_offline("worker-reused","instance-old"))
  row=self.q.workers()[0]
  self.assertEqual(row["status"],"online")
  self.assertNotIn("instance_token",row)
  with self.q.db() as c:
   self.assertEqual(c.execute("SELECT instance_token FROM worker_registry WHERE worker_id=?",("worker-reused",)).fetchone()[0],"instance-new")
  self.assertTrue(self.q.mark_worker_offline("worker-reused","instance-new"))
  self.assertEqual(self.q.workers()[0]["status"],"offline")

 def test_stale_worker_instance_cannot_heartbeat_after_restart(self):
  job=self.q.enqueue("render",{})
  claimed=self.q.claim("worker-reused",instance_token="instance-old")
  self.q.register_worker("worker-reused","host-b","instance-new")
  with self.assertRaises(LeaseConflict):
   self.q.heartbeat(job["id"],"worker-reused",claimed["lease_token"],"instance-old")
  self.assertEqual(self.q.get(job["id"])["lease_expires_at"],claimed["lease_expires_at"])

 def test_graceful_worker_shutdown_is_persisted_as_offline_not_stale(self):
  self.q.register_worker("worker-clean","host-a")
  self.assertTrue(self.q.mark_worker_offline("worker-clean"))
  self.assertEqual(self.q.workers()[0]["status"],"offline")
  health=self.q.operational_health()
  self.assertEqual(health["workers"]["total"],1)
  self.assertEqual(health["workers"]["online"],0)
  self.assertEqual(health["workers"]["stale"],0)
  self.assertEqual(health["status"],"healthy")
  self.assertFalse(self.q.mark_worker_offline("missing-worker"))

 def test_operational_health_reports_worker_staleness_without_mutation(self):
  job=self.q.enqueue("render",{})
  claimed=self.q.claim("worker-stale")
  with self.q.db() as c:
   c.execute("UPDATE worker_registry SET last_seen_at='2000-01-01T00:00:00+00:00' WHERE worker_id='worker-stale'")
  before=self.q.get(job["id"])
  result=self.q.operational_health()
  after=self.q.get(job["id"])
  self.assertEqual(result["status"],"attention_required")
  self.assertEqual(result["workers"]["stale"],1)
  self.assertEqual(result["leases"]["expired_running"],0)
  self.assertEqual(before["status"],after["status"])
  self.assertTrue(result["read_only"])
  self.assertEqual(result["actions_taken"],[])

 def test_operational_health_detects_expired_and_incomplete_running_leases(self):
  first=self.q.enqueue("render",{})
  self.q.claim("worker-expired")
  second=self.q.enqueue("render",{})
  self.q.claim("worker-incomplete")
  with self.q.db() as c:
   c.execute("UPDATE pipeline_jobs SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",(first["id"],))
   c.execute("UPDATE pipeline_jobs SET worker_id=NULL,lease_token=NULL,lease_expires_at=NULL WHERE id=?",(second["id"],))
  result=self.q.operational_health()
  self.assertEqual(result["status"],"blocked")
  self.assertEqual(result["leases"]["expired_running"],1)
  self.assertEqual(result["leases"]["running_missing_ownership"],1)
  self.assertEqual({x["code"] for x in result["blockers"]},
                   {"worker_lease_expired","worker_lease_incomplete"})
  self.assertEqual(self.q.get(first["id"])["status"],"running")

 def test_operational_health_reports_operator_pause_as_blocker(self):
  self.q.pause("manual safety stop")
  result=self.q.operational_health()
  self.assertEqual(result["status"],"blocked")
  self.assertTrue(result["queue"]["paused"])
  self.assertEqual(result["control"]["pause_reason"],"manual safety stop")
  self.assertEqual(result["blockers"][0]["code"],"production_queue_paused")

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
 def test_lifecycle_summaries_batch_compact_state_without_artifacts(self):
  job=self.q.enqueue("short_video_production",{"private_payload":"never return"})
  with self.q.db() as c:
   c.executescript("""
    CREATE TABLE production_runs(job_id TEXT PRIMARY KEY,brand TEXT,region TEXT,
      language TEXT,topic TEXT,status TEXT,current_stage TEXT,error TEXT,
      created_at TEXT,updated_at TEXT);
    CREATE TABLE review_decisions(id INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT,
      decision TEXT,previous_status TEXT,reviewer_id TEXT,comment TEXT,
      artifact_snapshot_json TEXT,created_at TEXT);
    CREATE TABLE youtube_uploads(job_id TEXT PRIMARY KEY,video_id TEXT,status TEXT,
      privacy_status TEXT,title TEXT,description TEXT,uploaded_at TEXT,error TEXT,
      updated_at TEXT,attempt_id TEXT,policy_version TEXT,policy_checked_on TEXT);
    CREATE TABLE youtube_upload_events(id INTEGER PRIMARY KEY AUTOINCREMENT,
      job_id TEXT,attempt_id TEXT,event_type TEXT,outcome TEXT,video_id TEXT,
      operator_id TEXT,note TEXT,previous_status TEXT,resulting_status TEXT,
      created_at TEXT,policy_version TEXT,policy_checked_on TEXT);
    CREATE TABLE tiktok_publications(job_id TEXT PRIMARY KEY,publish_id TEXT,status TEXT,
      privacy_level TEXT,title TEXT,is_aigc INTEGER,creator_username TEXT,
      creator_nickname TEXT,video_id TEXT,fail_reason TEXT,error TEXT,
      brand_content_toggle INTEGER,brand_organic_toggle INTEGER,operator_id TEXT,
      consented_at TEXT,updated_at TEXT,attempt_id TEXT,policy_version TEXT);
    CREATE TABLE tiktok_publication_events(id INTEGER PRIMARY KEY AUTOINCREMENT,
      job_id TEXT,attempt_id TEXT,event_type TEXT,outcome TEXT,publish_id TEXT,
      video_id TEXT,operator_id TEXT,note TEXT,created_at TEXT,policy_version TEXT);
   """)
   c.execute("INSERT INTO production_runs VALUES(?,?,?,?,?,?,?,?,?,?)",
     (job["id"],"NEXUS","KR","ko","AI trends","approved","review",None,"now","now"))
   c.execute("INSERT INTO review_decisions(job_id,decision,previous_status,reviewer_id,comment,artifact_snapshot_json,created_at) VALUES(?,?,?,?,?,?,?)",
     (job["id"],"approved","review_pending","reviewer","", "{}", "now"))
   c.execute("INSERT INTO youtube_uploads VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
     (job["id"],"video-1","uploaded","private","title","desc","now",None,"now","attempt-yt","v1","now"))
   c.execute("INSERT INTO youtube_upload_events(job_id,event_type,operator_id,created_at) VALUES(?,?,?,?)",
     (job["id"],"upload_attempt_started","operator","now"))
   c.execute("INSERT INTO tiktok_publication_events(job_id,event_type,operator_id,created_at) VALUES(?,?,?,?)",
     (job["id"],"publication_attempt_started","operator","now"))
   c.execute("INSERT INTO tiktok_publications VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
     (job["id"],"pub-1","processing","SELF_ONLY","title",1,None,None,None,None,None,0,0,"operator","now","now","attempt-tt","v1"))
  result=self.q.lifecycle_summaries([job["id"],job["id"]])
  self.assertEqual(set(result),{job["id"]})
  summary=result[job["id"]]
  self.assertEqual(summary["production_status"],"approved")
  self.assertEqual(summary["latest_review_decision"],"approved")
  self.assertEqual(summary["youtube_video_id"],"video-1")
  self.assertEqual(summary["youtube_events"],[{"event_type":"upload_attempt_started"}])
  self.assertEqual(summary["tiktok_status"],"processing")
  self.assertEqual(summary["tiktok_events"],[{"event_type":"publication_attempt_started"}])
  self.assertNotIn("payload",summary)
  self.assertNotIn("lease_token",summary)

 def test_lifecycle_summaries_reject_more_than_one_page(self):
  with self.assertRaises(ValueError):
   self.q.lifecycle_summaries([str(i) for i in range(101)])

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
if __name__=="__main__": unittest.main()
