import os,tempfile,unittest
from ledger import LedgerStore
class LedgerTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.s=LedgerStore(os.path.join(self.tmp.name,"x.db"))
 def tearDown(self): self.tmp.cleanup()
 def entry(self,kind,source,ref,amount):
  return self.s.record({"brand":"Brain Glitch","region":"US","entry_type":kind,
   "amount":amount,"currency":"USD","source_type":source,"source_reference":ref,
   "occurred_at":"2026-11-15T00:00:00+00:00"})
 def test_separate_revenue_and_cost(self):
  self.entry("youtube_ads","youtube_analytics","month-1",120)
  self.entry("affiliate","affiliate_network","order-1",30)
  self.entry("production_cost","ai_provider","invoice-1",25)
  r=self.s.report(brand="Brain Glitch")
  self.assertEqual(r["revenue"],150); self.assertEqual(r["costs"],25)
  self.assertEqual(r["net"],125); self.assertEqual(r["roi_percent"],500)
 def test_idempotent_source_reference(self):
  a=self.entry("sponsor","sponsor_invoice","inv-1",500)
  b=self.entry("sponsor","sponsor_invoice","inv-1",500)
  self.assertEqual(a["id"],b["id"])
 def test_financial_entries_and_reports_are_workspace_scoped(self):
  with self.s.db() as c:
   c.execute("CREATE TABLE production_runs(job_id TEXT PRIMARY KEY,workspace_id TEXT)")
   c.execute("INSERT INTO production_runs VALUES('job-a','workspace-a')")
  common={"brand":"Brain Glitch","region":"US","entry_type":"sponsor",
   "amount":100,"currency":"USD","source_type":"sponsor_invoice",
   "occurred_at":"2026-11-15T00:00:00+00:00"}
  a=self.s.record({**common,"job_id":"job-a","source_reference":"invoice-a"},
                  workspace_id="workspace-a")
  b=self.s.record({**common,"source_reference":"invoice-b"},
                  workspace_id="workspace-b")
  self.assertEqual(a["workspace_id"],"workspace-a")
  self.assertEqual(b["workspace_id"],"workspace-b")
  self.assertEqual(len(self.s.report(workspace_id="workspace-a")["entries"]),1)
  self.assertEqual(len(self.s.report(workspace_id="workspace-b")["entries"]),1)
  self.assertEqual(self.s.report()["entries"],[])
  with self.assertRaises(ValueError):
   self.s.record({**common,"job_id":"job-a","source_reference":"invoice-c"},
                 workspace_id="workspace-b")
  with self.assertRaises(ValueError):
   self.s.record({**common,"source_reference":"invoice-a"},
                 workspace_id="workspace-b")

 def test_source_reference_required(self):
  with self.assertRaises(ValueError):
   self.s.record({"brand":"x","region":"US","entry_type":"affiliate","amount":1,
    "currency":"USD","source_type":"affiliate_network","source_reference":"",
    "occurred_at":"2026-11-15T00:00:00+00:00"})
if __name__=="__main__": unittest.main()
