import os,tempfile,unittest
from production_pipeline import ProductionStore
from youtube_publishing import YouTubeUploadStore
from ledger import LedgerStore
from performance_insights import PerformanceAnalyzer
class PerformanceTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.db=os.path.join(self.tmp.name,"x.db")
  self.p=ProductionStore(self.db); self.u=YouTubeUploadStore(self.db); self.l=LedgerStore(self.db)
 def tearDown(self): self.tmp.cleanup()
 def test_insufficient_snapshots_not_misrepresented_as_growth(self):
  self.p.create("j1",{"brand":"Brain Glitch","region":"US","language":"English","topic":"Sleep"})
  self.p.stage("j1","review","approved")
  self.u.begin("j1","t","d"); self.u.finish("j1","vid1")
  r=PerformanceAnalyzer(self.db).analyze()
  self.assertEqual(r["brands"][0]["measured_videos"],0)
  self.assertIn("insufficient_evidence",[x["type"] for x in r["brands"][0]["recommendations"]])
 def test_snapshot_difference_and_recorded_finance(self):
  self.p.create("j1",{"brand":"Brain Glitch","region":"US","language":"English","topic":"Sleep"})
  self.p.stage("j1","review","approved")
  self.u.begin("j1","t","d"); self.u.finish("j1","vid1")
  self.u.snapshot("vid1",{"viewCount":"100","likeCount":"5","commentCount":"1"})
  self.u.snapshot("vid1",{"viewCount":"180","likeCount":"9","commentCount":"2"})
  self.l.record({"brand":"Brain Glitch","region":"US","entry_type":"youtube_ads","amount":12,
   "currency":"USD","source_type":"youtube_analytics","source_reference":"month1",
   "occurred_at":"2026-11-15T00:00:00+00:00"})
  r=PerformanceAnalyzer(self.db).analyze()
  self.assertEqual(r["brands"][0]["view_delta"],80)
  self.assertEqual(r["financial"]["Brain Glitch"]["revenue"],12)
if __name__=="__main__": unittest.main()
