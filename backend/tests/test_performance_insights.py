import os,tempfile,unittest
from production_pipeline import ProductionStore
from youtube_publishing import YouTubeUploadStore
from tiktok_publishing import TikTokPublishStore
from tiktok_metrics import TikTokMetricsStore
from review_workflow import ReviewStore
from ledger import LedgerStore
from performance_insights import PerformanceAnalyzer
from policy_engine import evaluate_content_policy

class PerformanceTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.db=os.path.join(self.tmp.name,"x.db")
  self.p=ProductionStore(self.db); self.review=ReviewStore(self.db); self.u=YouTubeUploadStore(self.db); self.l=LedgerStore(self.db)
 def tearDown(self): self.tmp.cleanup()
 def video(self,job,brand,region,topic,video):
  self.p.create(job,{"brand":brand,"region":region,"language":"English","topic":topic})
  self.p.stage(job,"rendered","review_pending")
  policy = evaluate_content_policy({
   "rights":{"visuals_cleared":True,"audio_cleared":True,"likeness_authorized":True},
   "synthetic_media_status":"none","factual_claims_verified":True,
   "originality_notes":"Analytics fixture has original content."
  })
  self.p.artifact(job,"script","text",None,{"script":"Analytics fixture script",
                                             "policy_preflight":policy})
  self.review.decide(job,"approved","test-reviewer","Approved for analytics fixture")
  attempt=self.u.begin(job,"t","d"); self.u.finish(job,video,attempt["attempt_id"])
 def entry(self,brand,currency,kind,ref,amount):
  self.l.record({"brand":brand,"region":"US","entry_type":kind,"amount":amount,
   "currency":currency,"source_type":"operator_receipt","source_reference":ref,
   "occurred_at":"2026-11-15T00:00:00+00:00"})
 def test_tiktok_performance_uses_tiktok_owned_video_snapshots_only(self):
  job="tt-1"
  self.p.create(job,{"brand":"Brain Glitch","region":"US","language":"English","topic":"Sleep"})
  self.p.stage(job,"rendered","review_pending")
  self.p.artifact(job,"rendering","video","https://media.example/tt.mp4",
                  {"duration_seconds":25,"aspect_ratio":"9:16"})
  store=TikTokPublishStore(self.db)
  attempt=store.begin(job,"Sleep tip",False,"operator-1","attempt-tt",False,False)
  store.set_initialized(job,attempt["attempt_id"],"publish-tt",{"creator_nickname":"test"})
  store.mark_status(job,attempt["attempt_id"],"PUBLISH_COMPLETE",["tt-video-1"])
  metrics=TikTokMetricsStore(self.db)
  metrics.save_snapshot(job,{"id":"tt-video-1","view_count":100,"like_count":10,
                             "comment_count":2,"share_count":1})
  metrics.save_snapshot(job,{"id":"tt-video-1","view_count":700,"like_count":40,
                             "comment_count":8,"share_count":5})
  with metrics.db() as connection:
   ids=[row["id"] for row in connection.execute(
    "SELECT id FROM tiktok_video_metric_snapshots WHERE video_id='tt-video-1' ORDER BY id"
   )]
   connection.execute("UPDATE tiktok_video_metric_snapshots SET collected_at=? WHERE id=?",
    ("2026-11-15T00:00:00+00:00",ids[0]))
   connection.execute("UPDATE tiktok_video_metric_snapshots SET collected_at=? WHERE id=?",
    ("2026-11-15T06:00:00+00:00",ids[1]))
  result=PerformanceAnalyzer(self.db).analyze(platform="tiktok")
  self.assertEqual(result["platform"],"tiktok")
  self.assertEqual(len(result["videos"]),1)
  self.assertEqual(result["videos"][0]["video_id"],"tt-video-1")
  self.assertEqual(result["videos"][0]["views_per_hour"],100.0)
  self.assertEqual(result["videos"][0]["interaction_delta"],40)
  self.assertEqual(result["videos"][0]["interactions_per_1000_view_delta"],66.67)
  self.assertEqual(result["metric_boundary"]["ranking_score_adjustment"],0)

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
 def test_snapshot_rates_and_interaction_ratio_are_time_normalized(self):
  self.video("j1","Brain Glitch","US","Sleep","vid1")
  self.u.snapshot("vid1",{"viewCount":"100","likeCount":"10","commentCount":"2"})
  self.u.snapshot("vid1",{"viewCount":"700","likeCount":"40","commentCount":"8"})
  with self.u.db() as connection:
   ids=[row["id"] for row in connection.execute(
    "SELECT id FROM youtube_video_snapshots WHERE video_id='vid1' ORDER BY id"
   )]
   connection.execute("UPDATE youtube_video_snapshots SET collected_at=? WHERE id=?",
    ("2026-11-15T00:00:00+00:00",ids[0]))
   connection.execute("UPDATE youtube_video_snapshots SET collected_at=? WHERE id=?",
    ("2026-11-15T06:00:00+00:00",ids[1]))
  result=PerformanceAnalyzer(self.db).analyze()
  video=result["videos"][0]
  self.assertEqual(video["elapsed_hours"],6.0)
  self.assertEqual(video["views_per_hour"],100.0)
  self.assertEqual(video["interaction_delta"],36)
  self.assertEqual(video["interactions_per_1000_view_delta"],60.0)

 def test_negative_interaction_counter_is_omitted_not_counted_as_negative(self):
  self.video("j1","Brain Glitch","US","Sleep","vid1")
  self.u.snapshot("vid1",{"viewCount":"100","likeCount":"10","commentCount":"2"})
  self.u.snapshot("vid1",{"viewCount":"200","likeCount":"4","commentCount":"5"})
  result=PerformanceAnalyzer(self.db).analyze()
  video=result["videos"][0]
  self.assertEqual(video["view_delta"],100)
  self.assertIsNone(video["like_delta"])
  self.assertIsNone(video["interaction_delta"])
  self.assertEqual(result["brands"][0]["like_delta"],0)

 def test_nonpositive_snapshot_interval_does_not_create_rate(self):
  self.video("j1","Brain Glitch","US","Sleep","vid1")
  self.u.snapshot("vid1",{"viewCount":"100","likeCount":"2","commentCount":"1"})
  self.u.snapshot("vid1",{"viewCount":"200","likeCount":"4","commentCount":"2"})
  with self.u.db() as connection:
   connection.execute(
    "UPDATE youtube_video_snapshots SET collected_at='2026-11-15T00:00:00+00:00' "
    "WHERE video_id='vid1'"
   )
  result=PerformanceAnalyzer(self.db).analyze()
  self.assertIsNone(result["videos"][0]["elapsed_hours"])
  self.assertIsNone(result["videos"][0]["views_per_hour"])

 def test_comparable_cohorts_isolate_region_age_duration_format_and_topic(self):
  def add_measured(job,brand,region,topic,video,duration,upload_at,first_at,second_at,views_delta):
   self.video(job,brand,region,topic,video)
   self.p.artifact(job,"rendering","video","https://media.example/"+video+".mp4",
                   {"duration_seconds":duration,"aspect_ratio":"9:16"})
   self.u.snapshot(video,{"viewCount":"100","likeCount":"5","commentCount":"1"})
   self.u.snapshot(video,{"viewCount":str(100+views_delta),"likeCount":"8","commentCount":"2"})
   with self.u.db() as connection:
    connection.execute("UPDATE youtube_uploads SET uploaded_at=? WHERE job_id=?",
                       (upload_at,job))
    ids=[row["id"] for row in connection.execute(
     "SELECT id FROM youtube_video_snapshots WHERE video_id=? ORDER BY id",(video,)
    )]
    connection.execute("UPDATE youtube_video_snapshots SET collected_at=? WHERE id=?",
                       (first_at,ids[0]))
    connection.execute("UPDATE youtube_video_snapshots SET collected_at=? WHERE id=?",
                       (second_at,ids[1]))

  add_measured("j1","Future Leak","US","AI robotics explained","vid1",30,
   "2026-11-14T00:00:00+00:00","2026-11-14T01:00:00+00:00",
   "2026-11-14T02:00:00+00:00",100)
  add_measured("j2","Future Leak","US","AI robotics explained","vid2",30,
   "2026-11-14T00:00:00+00:00","2026-11-14T01:00:00+00:00",
   "2026-11-14T02:00:00+00:00",200)
  add_measured("j3","Future Leak","US","AI robotics explained","vid3",30,
   "2026-11-14T00:00:00+00:00","2026-11-14T01:00:00+00:00",
   "2026-11-14T02:00:00+00:00",300)
  add_measured("j4","Future Leak","JP","AI robotics explained","vid4",30,
   "2026-11-14T00:00:00+00:00","2026-11-14T01:00:00+00:00",
   "2026-11-14T02:00:00+00:00",900)
  add_measured("j5","Future Leak","US","AI robotics explained","vid5",70,
   "2026-11-14T00:00:00+00:00","2026-11-14T01:00:00+00:00",
   "2026-11-14T02:00:00+00:00",800)
  add_measured("j6","Money Glitch","US","AI robotics explained","vid6",30,
   "2026-11-14T00:00:00+00:00","2026-11-14T01:00:00+00:00",
   "2026-11-14T02:00:00+00:00",500)

  result=PerformanceAnalyzer(self.db).analyze()
  cohort=next(x for x in result["cohorts"]
   if x["region"]=="US" and x["duration_bucket"]=="20_40s")
  self.assertEqual(cohort["publication_age_bucket"],"under_24h")
  self.assertEqual(cohort["format"],"vertical_short")
  self.assertEqual(cohort["topic_signature"],"ai explained robotics")
  self.assertEqual(cohort["sample_count"],3)
  self.assertEqual(cohort["median_views_per_hour"],200.0)
  self.assertEqual(cohort["evidence_status"],"observed")
  self.assertEqual(cohort["ranking_score_adjustment"],0)
  other_brand=next(x for x in result["cohorts"] if x["brand"]=="Money Glitch")
  self.assertEqual(other_brand["sample_count"],1)
  self.assertEqual(cohort["brand"],"Future Leak")
  self.assertNotIn("vid4",[x["job_id"] for x in result["videos"] if x["region"]=="US"])

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
