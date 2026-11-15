import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from profitability import score_opportunity, OpportunityStore, analyze_competition

BASE={"title":"AI workflow short","currency":"USD","forecast_source":"manual scenario v1",
 "forecast_views_low":10000,"forecast_views_high":30000,"rpm_low":2,"rpm_high":5,
 "cost_low":20,"cost_high":40,"monetization_eligible":True,
 "affiliate_revenue_low":0,"affiliate_revenue_high":10,
 "sponsor_revenue_low":0,"sponsor_revenue_high":0,
 "evidence_quality":0.8,"strategic_fit":0.9,"production_feasibility":0.7}

class ProfitabilityTests(unittest.TestCase):
 def test_calculates_estimate_not_actual(self):
  r=score_opportunity(BASE)
  self.assertEqual(r["scenario_type"],"estimate")
  self.assertEqual(r["ad_revenue"]["low"],20)
  self.assertEqual(r["ad_revenue"]["high"],150)
  self.assertEqual(r["gross_revenue"]["high"],160)
  self.assertEqual(r["net_profit"]["high"],140)
  self.assertIn("not measured earnings",r["assumptions"]["note"])
 def test_monetization_ineligible_disables_ad_revenue(self):
  d={**BASE,"monetization_eligible":False}
  r=score_opportunity(d)
  self.assertEqual(r["ad_revenue"],{"low":0.0,"high":0.0})
 def test_invalid_ranges_rejected(self):
  with self.assertRaises(ValueError): score_opportunity({**BASE,"forecast_views_low":40000})
 def test_forecast_requires_source(self):
  with self.assertRaises(ValueError): score_opportunity({**BASE,"forecast_source":""})
 def test_competitor_benchmark_uses_only_selected_stored_public_video_samples(self):
  class FakeCompetitorStore:
   def list_videos(self,channel_id,limit=30):
    return [
     {"channel_id":channel_id,"title":"Why AI agents are changing workflows","view_count":12000,"published_at":"2026-11-14"},
     {"channel_id":channel_id,"title":"Best pasta recipe","view_count":50000,"published_at":"2026-11-13"},
     {"channel_id":channel_id,"title":"AI agents explained for beginners","view_count":8000,"published_at":"2026-11-12"},
    ]
  result=analyze_competition("AI agents explained",["channel-1"],FakeCompetitorStore())
  self.assertEqual(result["selected_channels"],1)
  self.assertEqual(result["observed_videos"],3)
  self.assertEqual(result["topic_matched_videos"],2)
  self.assertEqual(result["median_matched_views"],10000)
  self.assertIn("no market-wide saturation",result["limitations"])
  empty=analyze_competition("AI agents",[],FakeCompetitorStore())
  self.assertEqual(empty["observed_videos"],0)

 def test_store_persists_ranked_scenarios(self):
  with tempfile.TemporaryDirectory() as d:
   store=OpportunityStore(str(Path(d)/"db.sqlite"))
   store.save(score_opportunity(BASE))
   self.assertEqual(len(store.list()),1)
if __name__=="__main__": unittest.main()
