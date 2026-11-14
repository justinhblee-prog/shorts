import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from youtube_intel import YouTubeDataAPI, CompetitorStore, CompetitorIntelligence

class CompetitorTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory()
  self.store=CompetitorStore(str(Path(self.tmp.name)/"intel.db"))
 def tearDown(self): self.tmp.cleanup()
 def test_hidden_subscribers_are_not_fabricated(self):
  api=YouTubeDataAPI("test",lambda url:{"items":[{"id":"UC1","snippet":{"title":"Channel"},"statistics":{"hiddenSubscriberCount":True,"viewCount":"1234","videoCount":"7"}}]})
  channel=api.channels(["UC1"])[0]
  self.assertIsNone(channel["subscriber_count"])
  self.assertEqual(channel["view_count"],1234)
 def test_search_and_snapshot_storage(self):
  def transport(url):
   if "/search?" in url:
    return {"items":[{"id":{"channelId":"UC1"}}]}
   if "/channels?" in url:
    return {"items":[{"id":"UC1","snippet":{"title":"Demo"},"statistics":{"subscriberCount":"100","viewCount":"2000","videoCount":"5"}}]}
   raise AssertionError(url)
  intel=CompetitorIntelligence(self.store,YouTubeDataAPI("test",transport))
  result=intel.search("demo",1)
  self.assertEqual(result["count"],1)
  self.assertEqual(self.store.list_channels()[0]["subscriber_count"],100)
 def test_recent_video_stats_are_source_counts(self):
  def transport(url):
   if "/search?" in url: return {"items":[{"id":{"videoId":"v1"}}]}
   return {"items":[{"id":"v1","snippet":{"channelId":"UC1","title":"Video","publishedAt":"2026-11-14T00:00:00Z"},"statistics":{"viewCount":"50","likeCount":"3","commentCount":"1"},"contentDetails":{"duration":"PT30S"}}]}
  api=YouTubeDataAPI("test",transport)
  rows=api.recent_videos("UC1",1)
  self.assertEqual(rows[0]["view_count"],50)
  self.assertEqual(rows[0]["duration"],"PT30S")
 def test_api_key_is_required(self):
  with self.assertRaises(RuntimeError): YouTubeDataAPI(None,lambda url:{}).channels(["UC1"])
if __name__=="__main__": unittest.main()
