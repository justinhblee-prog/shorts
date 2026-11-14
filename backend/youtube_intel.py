"""YouTube public competitor intelligence via Data API v3.
Requires YOUTUBE_DATA_API_KEY. Search calls consume quota; direct channel lookups are cheaper.
"""
import json, os, sqlite3, urllib.parse, urllib.request
from datetime import datetime, timezone

BASE="https://www.googleapis.com/youtube/v3"

def utc_now(): return datetime.now(timezone.utc).isoformat()

def http_json(url,timeout=15):
 req=urllib.request.Request(url,headers={"Accept":"application/json","User-Agent":"NexusStudioPro/0.1"})
 with urllib.request.urlopen(req,timeout=timeout) as response:
  return json.loads(response.read().decode("utf-8"))

class YouTubeDataAPI:
 def __init__(self,api_key=None,transport=http_json):
  self.api_key=api_key or os.getenv("YOUTUBE_DATA_API_KEY")
  self.transport=transport
 def _get(self,resource,params):
  if not self.api_key: raise RuntimeError("YOUTUBE_DATA_API_KEY is not configured")
  query={**params,"key":self.api_key}
  return self.transport(BASE+"/"+resource+"?"+urllib.parse.urlencode(query))
 def search_channels(self,query,limit=5):
  limit=max(1,min(int(limit),10))
  data=self._get("search",{"part":"snippet","type":"channel","q":query,"maxResults":limit})
  ids=[x.get("id",{}).get("channelId") for x in data.get("items",[])]
  ids=[x for x in ids if x]
  return self.channels(ids)
 def channels(self,channel_ids):
  ids=list(dict.fromkeys(str(x).strip() for x in channel_ids if str(x).strip()))[:50]
  if not ids: return []
  data=self._get("channels",{"part":"snippet,statistics,contentDetails","id":",".join(ids),"maxResults":50})
  return [self._channel(x) for x in data.get("items",[])]
 def _channel(self,item):
  stats=item.get("statistics",{})
  snippet=item.get("snippet",{})
  return {"channel_id":item.get("id"),"title":snippet.get("title",""),"description":snippet.get("description"),
   "custom_url":snippet.get("customUrl"),"published_at":snippet.get("publishedAt"),
   "country":snippet.get("country"),"subscriber_count":int(stats["subscriberCount"]) if stats.get("hiddenSubscriberCount") is not True and stats.get("subscriberCount") is not None else None,
   "view_count":int(stats["viewCount"]) if stats.get("viewCount") is not None else None,
   "video_count":int(stats["videoCount"]) if stats.get("videoCount") is not None else None,
   "hidden_subscriber_count":bool(stats.get("hiddenSubscriberCount",False)),
   "collected_at":utc_now()}
 def recent_videos(self,channel_id,limit=10):
  limit=max(1,min(int(limit),20))
  search=self._get("search",{"part":"snippet","channelId":channel_id,"type":"video","order":"date","maxResults":limit})
  ids=[x.get("id",{}).get("videoId") for x in search.get("items",[])]
  ids=[x for x in ids if x]
  if not ids: return []
  data=self._get("videos",{"part":"snippet,statistics,contentDetails","id":",".join(ids),"maxResults":len(ids)})
  result=[]
  for item in data.get("items",[]):
   st=item.get("statistics",{}); sn=item.get("snippet",{})
   result.append({"video_id":item.get("id"),"channel_id":sn.get("channelId",channel_id),
    "title":sn.get("title",""),"published_at":sn.get("publishedAt"),
    "view_count":int(st["viewCount"]) if st.get("viewCount") is not None else None,
    "like_count":int(st["likeCount"]) if st.get("likeCount") is not None else None,
    "comment_count":int(st["commentCount"]) if st.get("commentCount") is not None else None,
    "duration":item.get("contentDetails",{}).get("duration"),"collected_at":utc_now()})
  return result

class CompetitorStore:
 def __init__(self,path="data/nexus.sqlite3"):
  self.path=path
  os.makedirs(os.path.dirname(path) or ".",exist_ok=True)
  with sqlite3.connect(path,timeout=30) as db:
   db.execute("PRAGMA busy_timeout=30000")
   db.execute("""CREATE TABLE IF NOT EXISTS competitor_channels(
    channel_id TEXT PRIMARY KEY,title TEXT NOT NULL,description TEXT,custom_url TEXT,published_at TEXT,
    country TEXT,subscriber_count INTEGER,view_count INTEGER,video_count INTEGER,
    hidden_subscriber_count INTEGER NOT NULL DEFAULT 0,collected_at TEXT NOT NULL)""")
   db.execute("""CREATE TABLE IF NOT EXISTS competitor_channel_snapshots(
    id INTEGER PRIMARY KEY AUTOINCREMENT,channel_id TEXT NOT NULL,title TEXT NOT NULL,
    subscriber_count INTEGER,view_count INTEGER,video_count INTEGER,collected_at TEXT NOT NULL)""")
   db.execute("""CREATE TABLE IF NOT EXISTS competitor_videos(
    video_id TEXT PRIMARY KEY,channel_id TEXT NOT NULL,title TEXT NOT NULL,published_at TEXT,
    view_count INTEGER,like_count INTEGER,comment_count INTEGER,duration TEXT,collected_at TEXT NOT NULL)""")
 def save_channels(self,items):
  with sqlite3.connect(self.path,timeout=30) as db:
   for x in items:
    db.execute("""INSERT INTO competitor_channels VALUES(?,?,?,?,?,?,?,?,?,?,?)
     ON CONFLICT(channel_id) DO UPDATE SET title=excluded.title,description=excluded.description,
     custom_url=excluded.custom_url,published_at=excluded.published_at,country=excluded.country,
     subscriber_count=excluded.subscriber_count,view_count=excluded.view_count,
     video_count=excluded.video_count,hidden_subscriber_count=excluded.hidden_subscriber_count,
     collected_at=excluded.collected_at""",
     (x["channel_id"],x["title"],x.get("description"),x.get("custom_url"),x.get("published_at"),
      x.get("country"),x.get("subscriber_count"),x.get("view_count"),x.get("video_count"),
      int(x.get("hidden_subscriber_count",False)),x["collected_at"]))
    db.execute("""INSERT INTO competitor_channel_snapshots
     (channel_id,title,subscriber_count,view_count,video_count,collected_at) VALUES(?,?,?,?,?,?)""",
     (x["channel_id"],x["title"],x.get("subscriber_count"),x.get("view_count"),x.get("video_count"),x["collected_at"]))
 def save_videos(self,items):
  with sqlite3.connect(self.path,timeout=30) as db:
   for x in items:
    db.execute("""INSERT INTO competitor_videos VALUES(?,?,?,?,?,?,?,?,?)
     ON CONFLICT(video_id) DO UPDATE SET title=excluded.title,published_at=excluded.published_at,
     view_count=excluded.view_count,like_count=excluded.like_count,comment_count=excluded.comment_count,
     duration=excluded.duration,collected_at=excluded.collected_at""",
     (x["video_id"],x["channel_id"],x["title"],x.get("published_at"),x.get("view_count"),
      x.get("like_count"),x.get("comment_count"),x.get("duration"),x["collected_at"]))
 def list_channels(self,limit=50):
  with sqlite3.connect(self.path,timeout=30) as db:
   db.row_factory=sqlite3.Row
   return [dict(x) for x in db.execute("SELECT * FROM competitor_channels ORDER BY collected_at DESC LIMIT ?",(max(1,min(int(limit),200)),))]
 def list_videos(self,channel_id,limit=20):
  with sqlite3.connect(self.path,timeout=30) as db:
   db.row_factory=sqlite3.Row
   return [dict(x) for x in db.execute("SELECT * FROM competitor_videos WHERE channel_id=? ORDER BY published_at DESC LIMIT ?",(channel_id,max(1,min(int(limit),100))))]

class CompetitorIntelligence:
 def __init__(self,store,provider=None):
  self.store=store; self.provider=provider or YouTubeDataAPI()
 def search(self,query,limit=5):
  channels=self.provider.search_channels(query,limit)
  self.store.save_channels(channels)
  return {"query":query,"count":len(channels),"channels":channels,
   "data_note":"Public channel counters are point-in-time snapshots, not growth rates or revenue."}
 def inspect(self,channel_id,video_limit=10):
  channels=self.provider.channels([channel_id])
  if not channels: return None
  self.store.save_channels(channels)
  videos=self.provider.recent_videos(channel_id,video_limit)
  self.store.save_videos(videos)
  return {"channel":channels[0],"recent_videos":videos,
   "data_note":"Video views are observed public counters; no view velocity or revenue is inferred from a single snapshot."}
