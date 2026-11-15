import os,tempfile,unittest
from production_pipeline import ProductionStore
from youtube_publishing import YouTubeUploadStore
from review_workflow import ReviewStore
from ledger import LedgerStore
from performance_insights import PerformanceAnalyzer

class PerformanceTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.db=os.path.join(self.tmp.name,"x.db")
  self.p=ProductionStore(self.db); self.review=ReviewStore(self.db); self.u=YouTubeUploadStore(self.db); self.l=LedgerStore(self.db)
 def tearDown(self): self.tmp.cleanup()
 def video(self,job,brand,region,topic,video):
  self.p.create(job,{"brand":brand,"region":region,"language":"English","topic":topic})
  self.p.stage(job,"rendered","review_pending")
  self.review.decide(job,"approved","test-reviewer","Approved for analytics fixture")
  attempt=self.u.begin(job,"t","d"); self.u.finish(job,video,attempt["attempt_id"])
 def entry(self,brand,currency,kind,ref,amount):
  self.l.record({"brand":brand,"region":"US","entry_type":kind,"amount":amount,
   "currency":currency,"source_type":"operator_receipt","source_reference":ref,
   "occurred_at":"2026-11-15T00:00:00+00:00"})
 def test_insufficient_snapshots_not_misrepresented_as_growth(self):
  self.video("j1","Brain Glitch","US","Sleep","vid1")
  r=PerformanceAnalyzer(self.db).analyze()
  self.assertEqual(r["brands"][0]["measured_videos"],0)
  self.assertIn("insufficient_evidence",[x["type"] for x in r["brands"][0]["recommendations"]])
 def test_snapshot_difference_and_recorded_finance(self):
  self.video("j1","Brain Glitch","US","Sleep","vid1")
  self.u.snapshot("vid1",{"viewCount":"100","likeCount":"5","commentCount":"1"})
  self.u.snapshot("vid1",{"viewCount":"180","likeCount":"9","commentCount":"2"})
  self.entry("Brain Glitch","USD","youtube_ads","month1",12)
  r=PerformanceAnalyzer(self.db).analyze()
  self.assertEqual(r["brands"][0]["view_delta"],80)
  self.assertEqual(r["financial"][0]["revenue"],12)
  self.assertEqual(r["regions"][0]["view_delta"],80)
  self.assertEqual(r["videos"][0]["measurement_status"],"measured")
 def test_financials_never_mix_currencies_and_brand_filter_applies(self):
  self.entry("Brain Glitch","USD","youtube_ads","usd-rev",100)
  self.entry("Brain Glitch","KRW","production_cost","krw-cost",20000)
  self.entry("Silent Signals","USD","sponsor","other-brand",50)
  result=PerformanceAnalyzer(self.db).analyze("Brain Glitch")
  self.assertEqual({x["currency"] for x in result["financial"]},{"USD","KRW"})
  self.assertEqual(len(result["financial"]),2)
  self.assertTrue(all(x["brand"]=="Brain Glitch" for x in result["financial"]))
  usd=next(x for x in result["financial"] if x["currency"]=="USD")
  krw=next(x for x in result["financial"] if x["currency"]=="KRW")
  self.assertEqual(usd["net"],100)
  self.assertEqual(krw["net"],-20000)
 def test_counter_reset_is_excluded_from_growth_aggregation(self):
  self.video("j1","Brain Glitch","US","Sleep","vid1")
  self.u.snapshot("vid1",{"viewCount":"180"})
  self.u.snapshot("vid1",{"viewCount":"20"})
  result=PerformanceAnalyzer(self.db).analyze()
  self.assertEqual(result["brands"][0]["view_delta"],0)
  self.assertEqual(result["brands"][0]["measured_videos"],0)
  self.assertEqual(result["videos"][0]["measurement_status"],"counter_reset_or_invalid")
if __name__=="__main__":unittest.main()
