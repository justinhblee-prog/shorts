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
  self.assertEqual(r["net"],125); self.assertEqual(r["roi_percent"],400)
 def test_idempotent_source_reference(self):
  a=self.entry("sponsor","sponsor_invoice","inv-1",500)
  b=self.entry("sponsor","sponsor_invoice","inv-1",500)
  self.assertEqual(a["id"],b["id"])
 def test_source_reference_required(self):
  with self.assertRaises(ValueError):
   self.s.record({"brand":"x","region":"US","entry_type":"affiliate","amount":1,
    "currency":"USD","source_type":"affiliate_network","source_reference":"",
    "occurred_at":"2026-11-15T00:00:00+00:00"})
if __name__=="__main__": unittest.main()
