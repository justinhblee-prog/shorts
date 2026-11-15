import os
from typing import Any
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from pydantic import BaseModel, Field
from queue_store import JobQueue, JobNotFound, LeaseConflict
from trends import TrendStore, TrendIngestor
from youtube_intel import CompetitorStore, CompetitorIntelligence
from profitability import OpportunityStore, score_opportunity
from production_pipeline import ProductionStore, ProductionPipeline, submit_production, ProviderError
from brand_operations import BrandStore, BrandNotFound
from review_workflow import ReviewStore, ReviewNotFound, ReviewConflict, valid_review_token
from youtube_publishing import YouTubeUploadStore, YouTubePublisher, YouTubeUploadError
from ledger import LedgerStore
from performance_insights import PerformanceAnalyzer
from scheduler_store import ScheduleStore
from media_staging import MediaStager, MediaStagingError
from preflight import build_preflight

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
review_store=ReviewStore(os.getenv("NEXUS_DB_PATH","data/nexus.sqlite3"))
youtube_upload_store=YouTubeUploadStore(os.getenv("NEXUS_DB_PATH","data/nexus.sqlite3"))
youtube_publisher=YouTubePublisher(youtube_upload_store)
ledger_store=LedgerStore(os.getenv("NEXUS_DB_PATH","data/nexus.sqlite3"))
performance_analyzer=PerformanceAnalyzer(os.getenv("NEXUS_DB_PATH","data/nexus.sqlite3"))
schedule_store=ScheduleStore(os.getenv("NEXUS_DB_PATH","data/nexus.sqlite3"))
media_stager=MediaStager()

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

class ReviewDecision(BaseModel):
    reviewer_id:str=Field(min_length=1,max_length=128)
    comment:str=Field(default="",max_length=4000)


class YouTubeUploadRequest(BaseModel):
    media_path:str=Field(min_length=1,max_length=2000)
    title:str=Field(min_length=1,max_length=100)
    description:str=Field(default="",max_length=5000)
    tags:list[str]=Field(default_factory=list,max_length=30)
    category_id:str=Field(default="22",min_length=1,max_length=4)

class LedgerEntry(BaseModel):
    job_id:str|None=None
    brand:str=Field(min_length=1,max_length=100)
    region:str=Field(min_length=2,max_length=8)
    entry_type:str
    amount:float=Field(ge=0)
    currency:str=Field(min_length=3,max_length=3)
    source_type:str
    source_reference:str=Field(min_length=1,max_length=300)
    occurred_at:str=Field(min_length=10,max_length=40)
    note:str=Field(default="",max_length=2000)


class ScheduleInput(BaseModel):
    name:str=Field(min_length=1,max_length=120)
    interval_seconds:int=Field(ge=3600,le=31536000)
    brand:str=Field(min_length=1,max_length=100)
    region:str=Field(min_length=2,max_length=8)
    language:str=Field(min_length=2,max_length=40)
    topic:str=Field(min_length=1,max_length=500)
    start_at:str|None=None

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
def set_brand_activation(slug:str,body:BrandActivation,x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    try:
        return brand_store.set_active(slug,body.active)
    except BrandNotFound:
        raise HTTPException(404,"Brand not found")

@app.post("/api/production/jobs",status_code=201)
def create_production_job(body:ProductionBrief,x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
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
def get_production_job(job_id:str,x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    result=production_store.get(job_id)
    if result is None: raise HTTPException(404,"Production job not found")
    return result

@app.post("/api/production/jobs/{job_id}/execute")
def execute_production_job(job_id:str,body:ProductionExecute,x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
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


def require_review_access(token):
    expected=os.getenv("NEXUS_REVIEW_TOKEN")
    if not valid_review_token(token, expected):
        raise HTTPException(401,"Valid review token required")


@app.get("/api/review/pending")
def pending_reviews(limit:int=50, x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    return {"items":review_store.list_pending(limit)}



@app.get("/api/review/approved")
def approved_reviews(limit:int=50,x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    items=review_store.list_approved(limit)
    pending=[]
    for item in items:
        upload=youtube_upload_store.get(item["job_id"])
        item["upload_status"]=upload["status"] if upload else "not_uploaded"
        if item["upload_status"]!="uploaded":
            pending.append(item)
    return {"items":pending}


@app.post("/api/review/{job_id}/approve")
def approve_review(job_id:str, body:ReviewDecision,
                   x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    try:
        return review_store.decide(job_id,"approved",body.reviewer_id,body.comment)
    except ReviewNotFound:
        raise HTTPException(404,"Production job not found")
    except ReviewConflict as e:
        raise HTTPException(409,str(e))
    except ValueError as e:
        raise HTTPException(422,str(e))


@app.post("/api/review/{job_id}/reject")
def reject_review(job_id:str, body:ReviewDecision,
                  x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    try:
        return review_store.decide(job_id,"rejected",body.reviewer_id,body.comment)
    except ReviewNotFound:
        raise HTTPException(404,"Production job not found")
    except ReviewConflict as e:
        raise HTTPException(409,str(e))
    except ValueError as e:
        raise HTTPException(422,str(e))


@app.post("/api/review/{job_id}/request-revision")
def request_revision(job_id:str, body:ReviewDecision,
                     x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    try:
        return review_store.decide(job_id,"revision_requested",body.reviewer_id,body.comment)
    except ReviewNotFound:
        raise HTTPException(404,"Production job not found")
    except ReviewConflict as e:
        raise HTTPException(409,str(e))
    except ValueError as e:
        raise HTTPException(422,str(e))


@app.get("/api/review/{job_id}/history")
def review_history(job_id:str, x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    try:
        return {"items":review_store.history(job_id)}
    except ReviewNotFound:
        raise HTTPException(404,"Production job not found")




@app.post("/api/production/jobs/{job_id}/stage-media")
def stage_production_media(job_id:str,x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    production=production_store.get(job_id)
    if production is None:
        raise HTTPException(404,"Production job not found")
    if production["status"] not in ("rendered","review_pending","approved"):
        raise HTTPException(409,"Only rendered production jobs can be staged")
    video=next((item for item in production["artifacts"]
                if item["artifact_type"]=="video" and item["artifact_url"]),None)
    if video is None:
        raise HTTPException(409,"Rendered video artifact is not available")
    try:
        return media_stager.stage(job_id,video["artifact_url"])
    except MediaStagingError as e:
        raise HTTPException(502,str(e))


@app.post("/api/youtube/upload/{job_id}",status_code=201)
def upload_youtube_video(job_id:str,body:YouTubeUploadRequest,
                         x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    try:
        return youtube_publisher.upload_approved(
            job_id,body.media_path,review_store,body.title,body.description,
            body.tags,body.category_id)
    except ReviewNotFound:
        raise HTTPException(404,"Production job not found")
    except YouTubeUploadError as e:
        raise HTTPException(409,str(e))


@app.get("/api/youtube/uploads/{job_id}")
def get_youtube_upload(job_id:str,x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    result=youtube_upload_store.get(job_id)
    if result is None:
        raise HTTPException(404,"YouTube upload record not found")
    return result


@app.post("/api/youtube/videos/{video_id}/refresh-metrics")
def refresh_youtube_metrics(video_id:str,x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    try:
        return youtube_publisher.refresh_metrics(video_id)
    except YouTubeUploadError as e:
        raise HTTPException(502,str(e))



@app.post("/api/finance/ledger",status_code=201)
def record_financial_entry(body:LedgerEntry,x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    try:
        return ledger_store.record(body.model_dump())
    except (ValueError,KeyError) as e:
        raise HTTPException(422,str(e))


@app.get("/api/finance/report")
def financial_report(brand:str|None=None,from_date:str|None=None,to_date:str|None=None,
                     currency:str="USD",x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    try:
        return ledger_store.report(brand,from_date,to_date,currency)
    except ValueError as e:
        raise HTTPException(422,str(e))



@app.get("/api/performance/insights")
def performance_insights(brand:str|None=None,x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    return performance_analyzer.analyze(brand)



@app.post("/api/schedules",status_code=201)
def create_schedule(body:ScheduleInput,x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    brand=next((b for b in brand_store.list(active_only=True)
                if body.brand in (b["slug"],b["name"])),None)
    if brand is None: raise HTTPException(422,"Unknown or inactive brand")
    if body.region not in brand["config"]["regions"] or body.language not in brand["config"]["languages"]:
        raise HTTPException(422,"Region or language is not enabled for this brand")
    payload={"brand":brand["name"],"region":body.region,
             "language":body.language,"topic":body.topic}
    try:return schedule_store.create(body.name,body.interval_seconds,payload,body.start_at)
    except ValueError as e:raise HTTPException(422,str(e))


@app.get("/api/schedules")
def list_schedules(x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    return {"items":schedule_store.list()}



@app.get("/api/schedules/outbox")
def schedule_outbox(x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    return schedule_store.outbox_status()


@app.put("/api/schedules/{schedule_id}/activation")
def activate_schedule(schedule_id:str,active:bool,
                      x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    result=schedule_store.set_active(schedule_id,active)
    if result is None:raise HTTPException(404,"Schedule not found")
    return result


@app.post("/api/trends/collect")
def collect_trends(body:TrendCollect,x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    try:
        return trend_ingestor.collect(body.region,body.query,body.limit,body.include_hacker_news)
    except ValueError as e:
        raise HTTPException(422,str(e))
    except Exception as e:
        raise HTTPException(502,"Trend provider request failed: "+type(e).__name__)

@app.get("/api/trends")
def list_trends(region:str|None=None,source:str|None=None,q:str|None=None,limit:int=50,x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    try:
        return {"items":trend_store.list(region,source,q,limit)}
    except ValueError as e:
        raise HTTPException(422,str(e))


@app.get("/api/competitors/search")
def search_competitors(q:str,limit:int=5,x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    if len(q)<2 or len(q)>100: raise HTTPException(422,"q must contain 2-100 characters")
    try:
        return competitor_intel.search(q,limit)
    except RuntimeError as e:
        raise HTTPException(503,str(e))
    except Exception as e:
        raise HTTPException(502,"YouTube Data API request failed: "+type(e).__name__)

@app.get("/api/competitors")
def list_competitors(limit:int=50,x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    return {"channels":competitor_store.list_channels(limit)}

@app.get("/api/competitors/{channel_id}")
def inspect_competitor(channel_id:str,video_limit:int=10,x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
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
def create_opportunity_score(body:OpportunityInput,x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    try:
        result=score_opportunity(body.model_dump())
        return opportunity_store.save(result)
    except ValueError as e:
        raise HTTPException(422,str(e))

@app.get("/api/opportunities")
def list_opportunities(limit:int=50,x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    return {"opportunities":opportunity_store.list(limit)}

@app.get("/api/health")
def health(): return {"status":"ok","service":"nexus-studio-pro"}
@app.get("/api/queue/stats")
def stats(x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    return queue.stats()
@app.post("/api/jobs",status_code=201)
def enqueue(body:Enqueue,x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    return queue.enqueue(**body.model_dump())
@app.post("/api/jobs/claim")
def claim(body:Claim,x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    return {"job":queue.claim(body.worker_id,body.hostname)}
@app.post("/api/jobs/{jid}/heartbeat")
def heartbeat(jid:str,body:Lease,x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    try: return queue.heartbeat(jid,body.worker_id,body.lease_token)
    except JobNotFound: raise HTTPException(404,"Job not found")
    except LeaseConflict as e: raise HTTPException(409,str(e))
@app.post("/api/jobs/{jid}/complete")
def complete(jid:str,body:Complete,x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    try: return queue.finish(jid,body.worker_id,body.lease_token,body.result)
    except JobNotFound: raise HTTPException(404,"Job not found")
    except LeaseConflict as e: raise HTTPException(409,str(e))
@app.post("/api/jobs/{jid}/fail")
def fail(jid:str,body:Fail,x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    try: return queue.fail(jid,body.worker_id,body.lease_token,body.error_code,body.error_message,body.retryable)
    except JobNotFound: raise HTTPException(404,"Job not found")
    except LeaseConflict as e: raise HTTPException(409,str(e))
@app.post("/api/jobs/{jid}/cancel")
def cancel(jid:str,x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    try: return queue.cancel(jid)
    except JobNotFound: raise HTTPException(404,"Job not found")
    except ValueError as e: raise HTTPException(409,str(e))
@app.post("/api/queue/recover")
def recover(x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    return queue.recover()
@app.get("/api/workers")
def workers(x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    return {"workers":queue.workers()}
@app.get("/api/jobs/{jid}")
def get_job(jid:str,x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    try: return queue.get(jid)
    except JobNotFound: raise HTTPException(404,"Job not found")
@app.get("/api/jobs/{jid}/events")
def get_events(jid:str,x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    try: queue.get(jid); return {"events":queue.events(jid)}
    except JobNotFound: raise HTTPException(404,"Job not found")



@app.get("/api/preflight")
def preflight(x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    return build_preflight()


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

@app.get("/", include_in_schema=False)
def portal_home():
    return FileResponse(str(FRONTEND_DIR / "index.html"))

app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR)), name="assets")

if __name__=="__main__":
    import uvicorn
    uvicorn.run("app:app",host="0.0.0.0",port=int(os.getenv("PORT","8502")))
