import os
from typing import Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from queue_store import JobQueue, JobNotFound, LeaseConflict
from trends import TrendStore, TrendIngestor
from youtube_intel import CompetitorStore, CompetitorIntelligence
from profitability import OpportunityStore, score_opportunity
from production_pipeline import ProductionStore, ProductionPipeline, submit_production, ProviderError
from brand_operations import BrandStore, BrandNotFound

queue=JobQueue(os.getenv("NEXUS_DB_PATH","data/nexus.sqlite3"),int(os.getenv("NEXUS_LEASE_SECONDS","90")))
app=FastAPI(title="NEXUS STUDIO PRO API",version="0.1.0")
trend_store=TrendStore(os.getenv("NEXUS_DB_PATH","data/nexus.sqlite3"))
trend_ingestor=TrendIngestor(trend_store)
competitor_store=CompetitorStore(os.getenv("NEXUS_DB_PATH","data/nexus.sqlite3"))
competitor_intel=CompetitorIntelligence(competitor_store)
opportunity_store=OpportunityStore(os.getenv("NEXUS_DB_PATH","data/nexus.sqlite3"))
production_store=ProductionStore(os.getenv("NEXUS_DB_PATH","data/nexus.sqlite3"))
production_pipeline=ProductionPipeline(production_store)
brand_store=BrandStore(os.getenv("NEXUS_DB_PATH","data/nexus.sqlite3"))

class Enqueue(BaseModel):
    job_type:str=Field(min_length=1,max_length=100)
    payload:dict[str,Any]=Field(default_factory=dict)
    channel_name:str|None=None
    priority:int=100
    max_attempts:int=3
    idempotency_key:str|None=None
class Claim(BaseModel):
    worker_id:str=Field(min_length=1,max_length=128)
    hostname:str|None=None
class Lease(BaseModel):
    worker_id:str
    lease_token:str
class Complete(Lease):
    result:dict[str,Any]=Field(default_factory=dict)
class Fail(Lease):
    error_code:str="worker_error"
    error_message:str="Worker failed"
    retryable:bool=True

class BrandActivation(BaseModel):
    active:bool

class ProductionBrief(BaseModel):
    brand:str=Field(min_length=1,max_length=100)
    region:str=Field(min_length=2,max_length=8)
    language:str=Field(min_length=2,max_length=40)
    topic:str=Field(min_length=1,max_length=500)
    idempotency_key:str|None=None

class ProductionExecute(BaseModel):
    worker_id:str=Field(min_length=1,max_length=128)
    lease_token:str=Field(min_length=1,max_length=128)

class TrendCollect(BaseModel):
    region:str="US"
    query:str=Field(min_length=2,max_length=200)
    limit:int=30
    include_hacker_news:bool=False

@app.get("/api/brands")
def list_brands(active_only:bool=False):
    return {"brands":brand_store.list(active_only)}

@app.get("/api/brands/{slug}")
def get_brand(slug:str):
    result=brand_store.get(slug)
    if result is None: raise HTTPException(404,"Brand not found")
    return result

@app.put("/api/brands/{slug}/activation")
def set_brand_activation(slug:str,body:BrandActivation):
    try:
        return brand_store.set_active(slug,body.active)
    except BrandNotFound:
        raise HTTPException(404,"Brand not found")

@app.post("/api/production/jobs",status_code=201)
def create_production_job(body:ProductionBrief):
    try:
        brand = next((b for b in brand_store.list(active_only=True)
                      if body.brand in (b["slug"], b["name"])), None)
        if brand is None:
            raise HTTPException(422,"Unknown or inactive brand")
        config = brand["config"]
        if body.region not in config["regions"] or body.language not in config["languages"]:
            raise HTTPException(422,"Region or language is not enabled for this brand")
        brief = body.model_dump()
        brief["brand"] = brand["name"]
        return submit_production(queue,production_store,brief)
    except ValueError as e:
        raise HTTPException(422,str(e))

@app.get("/api/production/jobs/{job_id}")
def get_production_job(job_id:str):
    result=production_store.get(job_id)
    if result is None: raise HTTPException(404,"Production job not found")
    return result

@app.post("/api/production/jobs/{job_id}/execute")
def execute_production_job(job_id:str,body:ProductionExecute):
    try:
        job=queue.get(job_id)
        if job["job_type"]!="short_video_production":
            raise HTTPException(409,"Job is not a short-video production job")
        if job["status"]!="running" or job["worker_id"]!=body.worker_id or job["lease_token"]!=body.lease_token:
            raise HTTPException(409,"Current worker lease is required")
        result=production_pipeline.execute(job_id,job["payload"])
        queue.finish(job_id,body.worker_id,body.lease_token,{"production_status":"review_pending"})
        production_store.stage(job_id,"review_pending","review_pending")
        return production_store.get(job_id)
    except ProviderError as e:
        try:
            queue.fail(job_id,body.worker_id,body.lease_token,
                       "provider_"+e.stage,str(e),e.retryable)
        except Exception:
            pass
        raise HTTPException(502,{"stage":e.stage,"error":str(e),"retryable":e.retryable})
    except JobNotFound:
        raise HTTPException(404,"Job not found")
    except LeaseConflict as e:
        raise HTTPException(409,str(e))
    except HTTPException:
        raise
    except Exception as e:
        try:
            queue.fail(job_id,body.worker_id,body.lease_token,
                       "pipeline_internal_error",type(e).__name__,False)
        except Exception:
            pass
        raise HTTPException(500,"Production pipeline failed internally")

@app.post("/api/trends/collect")
def collect_trends(body:TrendCollect):
    try:
        return trend_ingestor.collect(body.region,body.query,body.limit,body.include_hacker_news)
    except ValueError as e:
        raise HTTPException(422,str(e))
    except Exception as e:
        raise HTTPException(502,"Trend provider request failed: "+type(e).__name__)

@app.get("/api/trends")
def list_trends(region:str|None=None,source:str|None=None,q:str|None=None,limit:int=50):
    try:
        return {"items":trend_store.list(region,source,q,limit)}
    except ValueError as e:
        raise HTTPException(422,str(e))


@app.get("/api/competitors/search")
def search_competitors(q:str,limit:int=5):
    if len(q)<2 or len(q)>100: raise HTTPException(422,"q must contain 2-100 characters")
    try:
        return competitor_intel.search(q,limit)
    except RuntimeError as e:
        raise HTTPException(503,str(e))
    except Exception as e:
        raise HTTPException(502,"YouTube Data API request failed: "+type(e).__name__)

@app.get("/api/competitors")
def list_competitors(limit:int=50):
    return {"channels":competitor_store.list_channels(limit)}

@app.get("/api/competitors/{channel_id}")
def inspect_competitor(channel_id:str,video_limit:int=10):
    try:
        result=competitor_intel.inspect(channel_id,video_limit)
        if result is None: raise HTTPException(404,"Channel not found")
        return result
    except RuntimeError as e:
        raise HTTPException(503,str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502,"YouTube Data API request failed: "+type(e).__name__)


class OpportunityInput(BaseModel):
    title:str=Field(default="",max_length=200)
    currency:str=Field(default="USD",min_length=3,max_length=3)
    forecast_source:str=Field(min_length=1,max_length=500)
    forecast_views_low:float=Field(ge=0)
    forecast_views_high:float=Field(ge=0)
    rpm_low:float=Field(ge=0)
    rpm_high:float=Field(ge=0)
    cost_low:float=Field(ge=0)
    cost_high:float=Field(ge=0)
    monetization_eligible:bool=False
    affiliate_revenue_low:float=Field(default=0,ge=0)
    affiliate_revenue_high:float=Field(default=0,ge=0)
    sponsor_revenue_low:float=Field(default=0,ge=0)
    sponsor_revenue_high:float=Field(default=0,ge=0)
    evidence_quality:float=Field(default=0,ge=0,le=1)
    strategic_fit:float=Field(default=0,ge=0,le=1)
    production_feasibility:float=Field(default=0,ge=0,le=1)


@app.post("/api/opportunities/score",status_code=201)
def create_opportunity_score(body:OpportunityInput):
    try:
        result=score_opportunity(body.model_dump())
        return opportunity_store.save(result)
    except ValueError as e:
        raise HTTPException(422,str(e))

@app.get("/api/opportunities")
def list_opportunities(limit:int=50):
    return {"opportunities":opportunity_store.list(limit)}

@app.get("/api/health")
def health(): return {"status":"ok","service":"nexus-studio-pro"}
@app.get("/api/queue/stats")
def stats(): return queue.stats()
@app.post("/api/jobs",status_code=201)
def enqueue(body:Enqueue): return queue.enqueue(**body.model_dump())
@app.post("/api/jobs/claim")
def claim(body:Claim): return {"job":queue.claim(body.worker_id,body.hostname)}
@app.post("/api/jobs/{jid}/heartbeat")
def heartbeat(jid:str,body:Lease):
    try: return queue.heartbeat(jid,body.worker_id,body.lease_token)
    except JobNotFound: raise HTTPException(404,"Job not found")
    except LeaseConflict as e: raise HTTPException(409,str(e))
@app.post("/api/jobs/{jid}/complete")
def complete(jid:str,body:Complete):
    try: return queue.finish(jid,body.worker_id,body.lease_token,body.result)
    except JobNotFound: raise HTTPException(404,"Job not found")
    except LeaseConflict as e: raise HTTPException(409,str(e))
@app.post("/api/jobs/{jid}/fail")
def fail(jid:str,body:Fail):
    try: return queue.fail(jid,body.worker_id,body.lease_token,body.error_code,body.error_message,body.retryable)
    except JobNotFound: raise HTTPException(404,"Job not found")
    except LeaseConflict as e: raise HTTPException(409,str(e))
@app.post("/api/jobs/{jid}/cancel")
def cancel(jid:str):
    try: return queue.cancel(jid)
    except JobNotFound: raise HTTPException(404,"Job not found")
    except ValueError as e: raise HTTPException(409,str(e))
@app.post("/api/queue/recover")
def recover(): return queue.recover()
@app.get("/api/workers")
def workers(): return {"workers":queue.workers()}
@app.get("/api/jobs/{jid}")
def get_job(jid:str):
    try: return queue.get(jid)
    except JobNotFound: raise HTTPException(404,"Job not found")
@app.get("/api/jobs/{jid}/events")
def get_events(jid:str):
    try: queue.get(jid); return {"events":queue.events(jid)}
    except JobNotFound: raise HTTPException(404,"Job not found")

if __name__=="__main__":
    import uvicorn
    uvicorn.run("app:app",host="0.0.0.0",port=int(os.getenv("PORT","8502")))
