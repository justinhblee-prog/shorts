import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from queue_store import JobQueue, LeaseConflict

class QueueTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.q=JobQueue(Path(self.tmp.name)/"test.db",10)
 def tearDown(self): self.tmp.cleanup()
 def test_idempotency(self):
  a=self.q.enqueue("script",{"topic":"x"},idempotency_key="once")
  b=self.q.enqueue("script",{"topic":"y"},idempotency_key="once")
  self.assertEqual(a["id"],b["id"]); self.assertEqual(self.q.stats()["total"],1)
 def test_exclusive_claim_and_fenced_completion(self):
  j=self.q.enqueue("render",{}); a=self.q.claim("worker-a")
  self.assertEqual(a["id"],j["id"]); self.assertIsNone(self.q.claim("worker-b"))
  self.assertEqual(self.q.finish(j["id"],"worker-a",a["lease_token"])["status"],"review_pending")
  with self.assertRaises(LeaseConflict): self.q.finish(j["id"],"worker-a",a["lease_token"])
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
if __name__=="__main__": unittest.main()
