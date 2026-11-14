"""Transparent scenario-based profitability model. Every forecast remains an estimate."""
import json, os, sqlite3, uuid
from contextlib import contextmanager
from datetime import datetime, timezone

def now(): return datetime.now(timezone.utc).isoformat()

@contextmanager
def connection(path):
 db=sqlite3.connect(path,timeout=30)
 try:
  db.execute("PRAGMA busy_timeout=30000")
  yield db
  db.commit()
 except Exception:
  db.rollback()
  raise
 finally:
  db.close()

def _nonnegative(name,value):
 value=float(value)
 if value<0: raise ValueError(name+" cannot be negative")
 return value

def score_opportunity(data):
 """Compute low/high scenario economics and an explainable 0-100 prioritization score."""
 low_views=_nonnegative("forecast_views_low",data["forecast_views_low"])
 high_views=_nonnegative("forecast_views_high",data["forecast_views_high"])
 low_rpm=_nonnegative("rpm_low",data["rpm_low"])
 high_rpm=_nonnegative("rpm_high",data["rpm_high"])
 cost_low=_nonnegative("cost_low",data["cost_low"])
 cost_high=_nonnegative("cost_high",data["cost_high"])
 if low_views>high_views or low_rpm>high_rpm or cost_low>cost_high:
  raise ValueError("Low scenario values must not exceed high scenario values")
 if not str(data.get("forecast_source","")).strip():
  raise ValueError("forecast_source is required; forecasts must be attributable")
 affiliate_low=_nonnegative("affiliate_revenue_low",data.get("affiliate_revenue_low",0))
 affiliate_high=_nonnegative("affiliate_revenue_high",data.get("affiliate_revenue_high",0))
 sponsor_low=_nonnegative("sponsor_revenue_low",data.get("sponsor_revenue_low",0))
 sponsor_high=_nonnegative("sponsor_revenue_high",data.get("sponsor_revenue_high",0))
 if affiliate_low>affiliate_high or sponsor_low>sponsor_high:
  raise ValueError("Low ancillary revenue must not exceed high ancillary revenue")
 eligible=bool(data.get("monetization_eligible",False))
 ad_low=low_views/1000*low_rpm if eligible else 0.0
 ad_high=high_views/1000*high_rpm if eligible else 0.0
 gross_low=ad_low+affiliate_low+sponsor_low
 gross_high=ad_high+affiliate_high+sponsor_high
 net_low=gross_low-cost_high
 net_high=gross_high-cost_low
 roi_low=(net_low/cost_high*100) if cost_high else None
 roi_high=(net_high/cost_low*100) if cost_low else None
 margin_high=(net_high/gross_high) if gross_high else 0.0
 evidence=max(0.0,min(1.0,float(data.get("evidence_quality",0))))
 fit=max(0.0,min(1.0,float(data.get("strategic_fit",0))))
 feasibility=max(0.0,min(1.0,float(data.get("production_feasibility",0))))
 roi_component=max(0.0,min(1.0,(roi_high or 0)/200))
 margin_component=max(0.0,min(1.0,margin_high))
 score=round(35*margin_component+25*roi_component+20*evidence+10*fit+10*feasibility,2)
 return {
  "title":str(data.get("title","")).strip(),
  "currency":str(data.get("currency","USD")).upper(),
  "scenario_type":"estimate",
  "forecast_source":str(data["forecast_source"]).strip(),
  "monetization_eligible":eligible,
  "views":{"low":int(low_views),"high":int(high_views)},
  "ad_revenue":{"low":round(ad_low,2),"high":round(ad_high,2)},
  "affiliate_revenue":{"low":round(affiliate_low,2),"high":round(affiliate_high,2)},
  "sponsor_revenue":{"low":round(sponsor_low,2),"high":round(sponsor_high,2)},
  "gross_revenue":{"low":round(gross_low,2),"high":round(gross_high,2)},
  "operating_cost":{"low":round(cost_low,2),"high":round(cost_high,2)},
  "net_profit":{"low":round(net_low,2),"high":round(net_high,2)},
  "roi_percent":{"low":round(roi_low,2) if roi_low is not None else None,
                 "high":round(roi_high,2) if roi_high is not None else None},
  "priority_score":score,
  "score_breakdown":{"margin":round(35*margin_component,2),"roi":round(25*roi_component,2),
                     "evidence":round(20*evidence,2),"strategic_fit":round(10*fit,2),
                     "production_feasibility":round(10*feasibility,2)},
  "assumptions":{"rpm_low":low_rpm,"rpm_high":high_rpm,
                 "note":"Scenario estimate from supplied assumptions, not measured earnings or a guaranteed outcome."}
 }

class OpportunityStore:
 def __init__(self,path="data/nexus.sqlite3"):
  self.path=path
  os.makedirs(os.path.dirname(path) or ".",exist_ok=True)
  with connection(path) as db:
   db.execute("""CREATE TABLE IF NOT EXISTS scored_opportunities(
    id TEXT PRIMARY KEY,title TEXT NOT NULL,priority_score REAL NOT NULL,
    currency TEXT NOT NULL,scenario_json TEXT NOT NULL,created_at TEXT NOT NULL)""")
 def save(self,result):
  oid=str(uuid.uuid4()); created=now()
  with connection(self.path) as db:
   db.execute("INSERT INTO scored_opportunities VALUES(?,?,?,?,?,?)",
    (oid,result.get("title") or "Untitled opportunity",result["priority_score"],
     result["currency"],json.dumps(result,ensure_ascii=False),created))
  return {"id":oid,"created_at":created,**result}
 def list(self,limit=50):
  with connection(self.path) as db:
   db.row_factory=sqlite3.Row
   return [{"id":r["id"],"title":r["title"],"priority_score":r["priority_score"],
    "currency":r["currency"],"created_at":r["created_at"],"scenario":json.loads(r["scenario_json"])}
    for r in db.execute("SELECT * FROM scored_opportunities ORDER BY priority_score DESC,created_at DESC LIMIT ?",
                         (max(1,min(int(limit),200)),))]
