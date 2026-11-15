import json, sys, tempfile, unittest
from unittest import mock
from urllib.error import HTTPError
from pathlib import Path
from urllib.parse import urlparse, parse_qs
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from trends import (GoogleNewsRSS, HackerNews, TrendStore, TrendIngestor, fetch,
                    TrendFetchError, MAX_TREND_RESPONSE_BYTES)

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
 def test_direct_lookup_returns_only_exact_signal(self):
  xml=b'<rss><channel><item><title>Exact signal</title><link>https://example.com/exact</link></item></channel></rss>'
  TrendIngestor(self.store,google=GoogleNewsRSS(lambda url:xml)).collect("US","AI")
  item=self.store.list()[0]
  self.assertEqual(self.store.get(item["id"])["title"],"Exact signal")
  self.assertIsNone(self.store.get("not-a-real-trend"))
 def test_rejects_unknown_region(self):
  with self.assertRaises(ValueError): GoogleNewsRSS(lambda url:b"").collect("XX","test")
 def test_source_fetch_reads_only_configured_response_limit(self):
  response=mock.MagicMock()
  response.status=200
  response.headers={}
  response.read.return_value=b"x"*(MAX_TREND_RESPONSE_BYTES+1)
  response.__enter__.return_value=response
  opener=mock.Mock()
  opener.open.return_value=response
  with mock.patch("urllib.request.build_opener",return_value=opener):
   with self.assertRaisesRegex(TrendFetchError,"512 KiB"):
    fetch("https://news.google.com/rss/search?q=ai")
  response.read.assert_called_once_with(MAX_TREND_RESPONSE_BYTES+1)

 def test_source_fetch_validates_content_length_before_and_after_read(self):
  response=mock.MagicMock()
  response.status=200
  response.headers={"Content-Length":"-1"}
  response.__enter__.return_value=response
  opener=mock.Mock()
  opener.open.return_value=response
  with mock.patch("urllib.request.build_opener",return_value=opener):
   with self.assertRaisesRegex(TrendFetchError,"Content-Length|512 KiB"):
    fetch("https://news.google.com/rss/search?q=ai")
  response.read.assert_not_called()

  response.headers={"Content-Length":"4"}
  response.read.return_value=b"abc"
  with mock.patch("urllib.request.build_opener",return_value=opener):
   with self.assertRaisesRegex(TrendFetchError,"does not match"):
    fetch("https://news.google.com/rss/search?q=ai")

 def test_source_fetch_rejects_redirects_without_following_them(self):
  opener=mock.Mock()
  opener.open.side_effect=HTTPError(
   "https://news.google.com/rss/search?q=ai",302,"Found",
   {"Location":"https://attacker.example/collect"},None
  )
  with mock.patch("urllib.request.build_opener",return_value=opener) as build:
   with self.assertRaisesRegex(TrendFetchError,"HTTP status 302"):
    fetch("https://news.google.com/rss/search?q=ai")
  build.assert_called_once()
  opener.open.assert_called_once()

 def test_source_fetch_rejects_non_success_status(self):
  response=mock.MagicMock()
  response.status=503
  response.headers={}
  response.__enter__.return_value=response
  opener=mock.Mock()
  opener.open.return_value=response
  with mock.patch("urllib.request.build_opener",return_value=opener):
   with self.assertRaisesRegex(TrendFetchError,"HTTP status"):
    fetch("https://hacker-news.firebaseio.com/v0/topstories.json")
  response.read.assert_not_called()

if __name__=="__main__": unittest.main()
