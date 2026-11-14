import hashlib, json, os, sqlite3, urllib.parse, urllib.request
from contextlib import contextmanager
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

REGIONS = {
 "KR":{"hl":"ko","gl":"KR","ceid":"KR:ko"},
 "US":{"hl":"en","gl":"US","ceid":"US:en"},
 "JP":{"hl":"ja","gl":"JP","ceid":"JP:ja"},
 "GB":{"hl":"en-GB","gl":"GB","ceid":"GB:en"},
}
GOOGLE_RSS="https://news.google.com/rss/search"
HN_TOP="https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM="https://hacker-news.firebaseio.com/v0/item/{}.json"


@contextmanager
def connection(path):
 db=sqlite3.connect(path,timeout=30)
 try:
  yield db
  db.commit()
 except Exception:
  db.rollback()
  raise
 finally:
  db.close()

def now():
 return datetime.now(timezone.utc).isoformat()

def published(value):
 if not value: return None
 try:
  d=parsedate_to_datetime(value)
  if d.tzinfo is None: d=d.replace(tzinfo=timezone.utc)
  return d.astimezone(timezone.utc).isoformat()
 except (TypeError,ValueError,OverflowError): return None

def uid(source,url):
 return hashlib.sha256((source+"|"+url).encode()).hexdigest()

def fetch(url,timeout=12):
 req=urllib.request.Request(url,headers={"User-Agent":"NexusStudioPro/0.1"})
 with urllib.request.urlopen(req,timeout=timeout) as response: return response.read()

class TrendStore:
 def __init__(self,path="data/nexus.sqlite3"):
  self.path=path
  os.makedirs(os.path.dirname(path) or ".",exist_ok=True)
  with connection(path) as db:
   db.execute("""CREATE TABLE IF NOT EXISTS trend_signals(
    id TEXT PRIMARY KEY,source TEXT NOT NULL,region TEXT NOT NULL,query TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,url TEXT NOT NULL,summary TEXT,published_at TEXT,
    source_score REAL,source_comments INTEGER,source_metrics_json TEXT NOT NULL DEFAULT '{}',
    collected_at TEXT NOT NULL,UNIQUE(source,url))""")
   db.execute("CREATE INDEX IF NOT EXISTS idx_trends_region_date ON trend_signals(region,published_at)")
 def save(self,items):
  with connection(self.path) as db:
   db.execute("PRAGMA busy_timeout=30000")
   for x in items:
    db.execute("""INSERT INTO trend_signals VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
     ON CONFLICT(source,url) DO UPDATE SET region=excluded.region,query=excluded.query,
     title=excluded.title,summary=excluded.summary,
     published_at=COALESCE(excluded.published_at,trend_signals.published_at),
     source_score=COALESCE(excluded.source_score,trend_signals.source_score),
     source_comments=COALESCE(excluded.source_comments,trend_signals.source_comments),
     source_metrics_json=excluded.source_metrics_json,collected_at=excluded.collected_at""",
     (x["id"],x["source"],x["region"],x.get("query",""),x["title"],x["url"],x.get("summary"),
      x.get("published_at"),x.get("source_score"),x.get("source_comments"),
      json.dumps(x.get("source_metrics",{}),ensure_ascii=False),x["collected_at"]))
  return {"processed":len(items)}
 def list(self,region=None,source=None,q=None,limit=50):
  sql="SELECT * FROM trend_signals WHERE 1=1"; args=[]
  if region: sql+=" AND region=?"; args.append(region.upper())
  if source: sql+=" AND source=?"; args.append(source)
  if q:
   sql+=" AND (title LIKE ? OR summary LIKE ? OR query LIKE ?)"; p="%"+q+"%"; args.extend([p,p,p])
  sql+=" ORDER BY COALESCE(published_at,collected_at) DESC LIMIT ?"
  args.append(max(1,min(int(limit),200)))
  with sqlite3.connect(self.path,timeout=30) as db:
   db.row_factory=sqlite3.Row
   return [dict(r) for r in db.execute(sql,args)]

class GoogleNewsRSS:
 source="google_news_rss"
 def __init__(self,transport=fetch): self.transport=transport
 def collect(self,region,query,limit=30):
  region=region.upper()
  if region not in REGIONS: raise ValueError("Unsupported region: use KR, US, JP or GB")
  url=GOOGLE_RSS+"?"+urllib.parse.urlencode({**REGIONS[region],"q":query})
  root=ET.fromstring(self.transport(url))
  result=[]
  for n in root.findall("./channel/item")[:max(1,min(int(limit),100))]:
   title=(n.findtext("title") or "").strip(); link=(n.findtext("link") or "").strip()
   if not title or not link: continue
   result.append({"id":uid(self.source,link),"source":self.source,"region":region,"query":query,
    "title":title,"url":link,"summary":(n.findtext("description") or "").strip() or None,
    "published_at":published(n.findtext("pubDate")),"source_score":None,"source_comments":None,
    "source_metrics":{},"collected_at":now()})
  return result

class HackerNews:
 source="hacker_news"
 def __init__(self,transport=fetch): self.transport=transport
 def collect(self,limit=30):
  ids=json.loads(self.transport(HN_TOP).decode())
  result=[]
  for item_id in ids[:max(1,min(int(limit),100))]:
   item=json.loads(self.transport(HN_ITEM.format(int(item_id))).decode())
   if not item or item.get("type")!="story" or item.get("dead") or item.get("deleted"): continue
   url=item.get("url") or "https://news.ycombinator.com/item?id="+str(item_id)
   result.append({"id":uid(self.source,url),"source":self.source,"region":"GLOBAL","query":"top stories",
    "title":(item.get("title") or "").strip(),"url":url,"summary":None,
    "published_at":datetime.fromtimestamp(item["time"],timezone.utc).isoformat() if item.get("time") else None,
    "source_score":item.get("score"),"source_comments":item.get("descendants"),
    "source_metrics":{"by":item.get("by"),"hn_item_id":item_id},"collected_at":now()})
  return [x for x in result if x["title"]]

class TrendIngestor:
 def __init__(self,store,google=None,hacker_news=None):
  self.store=store; self.google=google or GoogleNewsRSS(); self.hn=hacker_news or HackerNews()
 def collect(self,region="US",query="artificial intelligence",limit=30,include_hacker_news=False):
  region=region.upper()
  if region not in REGIONS: raise ValueError("Unsupported region: use KR, US, JP or GB")
  items=self.google.collect(region,query,limit)
  if include_hacker_news and region=="US": items.extend(self.hn.collect(limit))
  saved=self.store.save(items)
  return {"region":region,"query":query,"fetched":len(items),**saved,
   "sources":sorted({x["source"] for x in items}),
   "metrics_note":"Google News RSS provides no search volume or view velocity; those metrics remain null."}
