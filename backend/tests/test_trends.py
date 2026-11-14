import json, sys, tempfile, unittest
from pathlib import Path
from urllib.parse import urlparse, parse_qs
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from trends import GoogleNewsRSS, HackerNews, TrendStore, TrendIngestor

class TrendTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory()
  self.store=TrendStore(str(Path(self.tmp.name)/"trends.db"))
 def tearDown(self): self.tmp.cleanup()
 def test_google_rss_parses_region_and_keeps_unknown_metrics_null(self):
  xml=b'<rss><channel><item><title>AI report</title><link>https://example.com/a</link><description>Brief</description><pubDate>Sat, 14 Nov 2026 10:00:00 GMT</pubDate></item></channel></rss>'
  seen=[]
  provider=GoogleNewsRSS(lambda url:(seen.append(url) or xml))
  items=provider.collect("KR","AI",10)
  self.assertEqual(len(items),1)
  self.assertEqual(items[0]["region"],"KR")
  self.assertIsNone(items[0]["source_score"])
  self.assertEqual(parse_qs(urlparse(seen[0]).query)["ceid"],["KR:ko"])
 def test_hacker_news_uses_publisher_metrics(self):
  def transport(url):
   if url.endswith("topstories.json"): return b"[42]"
   return json.dumps({"id":42,"type":"story","title":"HN story","url":"https://example.com/hn","score":91,"descendants":12,"time":1794650400}).encode()
  item=HackerNews(transport).collect(5)[0]
  self.assertEqual(item["source_score"],91)
  self.assertEqual(item["source_comments"],12)
  self.assertEqual(item["region"],"GLOBAL")
 def test_store_upserts_same_source_url(self):
  xml=b'<rss><channel><item><title>One</title><link>https://example.com/1</link></item></channel></rss>'
  ing=TrendIngestor(self.store,google=GoogleNewsRSS(lambda url:xml))
  self.assertEqual(ing.collect("US","AI")["fetched"],1)
  self.assertEqual(ing.collect("US","AI")["fetched"],1)
  self.assertEqual(len(self.store.list()),1)
 def test_rejects_unknown_region(self):
  with self.assertRaises(ValueError): GoogleNewsRSS(lambda url:b"").collect("XX","test")
if __name__=="__main__": unittest.main()
