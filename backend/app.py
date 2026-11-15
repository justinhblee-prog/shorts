import os
import secrets
from typing import Any, Literal
from fastapi import FastAPI, HTTPException, Header, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from pydantic import BaseModel, Field
from queue_store import JobQueue, JobNotFound, LeaseConflict, IdempotencyConflict
from trends import TrendStore, TrendIngestor
from youtube_intel import CompetitorStore, CompetitorIntelligence
from profitability import OpportunityStore, score_opportunity, analyze_competition
from trend_recommendations import rank_trend_candidates
from production_pipeline import ProductionStore, ProductionPipeline, submit_production, ProviderError, ProductionLeaseConflict
from brand_operations import BrandStore, BrandNotFound
from review_workflow import ReviewStore, ReviewNotFound, ReviewConflict, valid_review_token
from youtube_publishing import YouTubeUploadStore, YouTubePublisher, YouTubeUploadError
from tiktok_publishing import TikTokPublishStore, TikTokPublisher, TikTokPublishError
from tiktok_oauth import TikTokOAuthStore, TikTokOAuthManager, TikTokOAuthError
from ledger import LedgerStore
from performance_insights import PerformanceAnalyzer
from recommendation_evaluation import RecommendationEvaluationStore
from scheduler_store import ScheduleStore
from media_staging import MediaStager, MediaStagingError
from preflight import build_preflight
from policy_engine import POLICY_VERSION

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
tiktok_publish_store=TikTokPublishStore(os.getenv("NEXUS_DB_PATH","data/nexus.sqlite3"))
tiktok_oauth_store=TikTokOAuthStore(os.getenv("NEXUS_DB_PATH","data/nexus.sqlite3"))
tiktok_oauth_manager=TikTokOAuthManager(tiktok_oauth_store)
tiktok_publisher=TikTokPublisher(
    tiktok_publish_store,token_provider=tiktok_oauth_manager.get_access_token
)
ledger_store=LedgerStore(os.getenv("NEXUS_DB_PATH","data/nexus.sqlite3"))
performance_analyzer=PerformanceAnalyzer(os.getenv("NEXUS_DB_PATH","data/nexus.sqlite3"))
recommendation_evaluation_store=RecommendationEvaluationStore(os.getenv("NEXUS_DB_PATH","data/nexus.sqlite3"))
schedule_store=ScheduleStore(os.getenv("NEXUS_DB_PATH","data/nexus.sqlite3"))
media_stager=MediaStager()

class Enqueue(BaseModel):
    job_type:str=Field(min_length=1,max_length=100)
    payload:dict[str,Any]=Field(default_factory=dict)
    channel_name:str|None=None
    priority:int=100
    max_attempts:int=3
    idempotency_key:str|None=None

class QueueControlAction(BaseModel):
    operator_id:str=Field(min_length=1,max_length=128)
    note:str=Field(min_length=1,max_length=2000)

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


class PolicyEvidenceInput(BaseModel):
    reviewer_id:str=Field(min_length=1,max_length=128)
    rights:dict[str,bool]|None=None
    synthetic_media_status:Literal[
        "none","ai_assisted_nonrealistic","ai_generated","realistic_alteration","unknown"
    ]|None=None
    platform_disclosures:dict[str,bool]|None=None
    platforms:list[Literal["youtube","tiktok"]]|None=None
    risk_flags:dict[str,bool]|None=None
    factual_claims_verified:bool|None=None
    originality_notes:str|None=Field(default=None,max_length=4000)
    claim_evidence_notes:str|None=Field(default=None,max_length=4000)
    source_urls:list[str]|None=Field(default=None,max_length=30)
    transformative_contribution:str|None=Field(default=None,max_length=4000)
    commercial_relationship_disclosed:bool|None=None
    child_safety_review_confirmed:bool|None=None


class YouTubeUploadRequest(BaseModel):
    media_path:str=Field(min_length=1,max_length=2000)
    title:str=Field(min_length=1,max_length=100)
    description:str=Field(default="",max_length=5000)
    tags:list[str]=Field(default_factory=list,max_length=30)
    category_id:str=Field(default="22",min_length=1,max_length=4)

class TikTokPublishRequest(BaseModel):
    media_path:str=Field(min_length=1,max_length=2000)
    title:str=Field(min_length=1,max_length=2200)
    operator_id:str=Field(min_length=1,max_length=128)
    explicit_consent:bool
    brand_content_toggle:bool
    brand_organic_toggle:bool


class YouTubeUploadReconciliation(BaseModel):
    outcome:Literal["uploaded","not_uploaded"]
    confirmed:bool
    video_id:str|None=Field(default=None,min_length=1,max_length=128)
    note:str=Field(min_length=1,max_length=2000)
    operator_id:str=Field(min_length=1,max_length=128)

class YouTubeLateSuccessResolution(BaseModel):
    operator_id:str=Field(min_length=1,max_length=128)
    video_id:str=Field(min_length=1,max_length=128)
    note:str=Field(min_length=1,max_length=2000)

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

class TrendProductionDraft(BaseModel):
    brand:str=Field(min_length=1,max_length=100)
    language:str=Field(min_length=2,max_length=40)
    idempotency_key:str|None=None

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
        # Freeze the selected brand's editorial profile into the durable job payload
        # so workers use the same brand rules even if the profile is later edited.
        profile = config
        brief["brand_profile"] = {
            "positioning": profile.get("positioning", ""),
            "audience": profile.get("audience", ""),
            "tone": profile.get("tone", []),
            "risk_level": profile.get("risk_level", "standard"),
            "review_rules": profile.get("review_rules", []),
        }
        return submit_production(queue,production_store,brief)
    except IdempotencyConflict as e:
        raise HTTPException(409,str(e))
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
        result=production_pipeline.execute(
            job_id,job["payload"],worker_id=body.worker_id,lease_token=body.lease_token
        )
        queue.finish(job_id,body.worker_id,body.lease_token,{"production_status":"review_pending"})
        production_store.reconcile_review_pending(queue)
        return production_store.get(job_id)
    except ProviderError as e:
        try:
            queue.fail(job_id,body.worker_id,body.lease_token,
                       "provider_"+e.stage,str(e),e.retryable)
        except Exception:
            pass
        try:
            queue.pause(f"API provider failure at {e.stage}: {e}", job_id)
        except Exception:
            pass
        raise HTTPException(502,{"stage":e.stage,"error":str(e),"retryable":e.retryable})
    except JobNotFound:
        raise HTTPException(404,"Job not found")
    except ProductionLeaseConflict as e:
        try:
            queue.pause(f"API production lease conflict: {e}", job_id)
        except Exception:
            pass
        raise HTTPException(409,str(e))
    except LeaseConflict as e:
        try:
            queue.pause(f"API queue lease conflict: {e}", job_id)
        except Exception:
            pass
        raise HTTPException(409,str(e))
    except HTTPException:
        raise
    except Exception as e:
        try:
            queue.fail(job_id,body.worker_id,body.lease_token,
                       "pipeline_internal_error",type(e).__name__,False)
        except Exception:
            pass
        try:
            queue.pause(f"API pipeline internal error: {type(e).__name__}: {e}", job_id)
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
    production_store.reconcile_review_pending(queue)
    return {"items":review_store.list_pending(limit)}



@app.get("/api/review/approved")
def approved_reviews(limit:int=50,x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    items=review_store.list_approved(limit)
    pending=[]
    for item in items:
        upload=youtube_upload_store.get(item["job_id"])
        item["upload_status"]=upload["status"] if upload else "not_uploaded"
        item["upload_video_id"]=upload.get("video_id") if upload else None
        item["upload_events"]=upload.get("events",[]) if upload else []
        item["upload_reconciliation_required"]=bool(
            upload and upload.get("reconciliation_required")
        )
        script=next((artifact for artifact in item.get("artifacts",[])
                     if artifact.get("stage")=="script"
                     and artifact.get("artifact_type")=="text"),None)
        metadata=(script or {}).get("metadata") or {}
        policy=metadata.get("policy_preflight") or {}
        tiktok_selected="tiktok" in (policy.get("platforms") or [])
        tiktok=tiktok_publish_store.get(item["job_id"])
        item["tiktok_eligible"]=bool(
            tiktok_selected and policy.get("policy_version")==POLICY_VERSION
            and not policy.get("approval_blockers")
            and policy.get("status")!="blocked"
        )
        item["tiktok_status"]=(tiktok or {}).get("status") if tiktok_selected else "not_selected"
        if tiktok_selected and not tiktok:
            item["tiktok_status"]="not_started"
        item["tiktok_publish_id"]=(tiktok or {}).get("publish_id")
        item["tiktok_video_id"]=(tiktok or {}).get("video_id")
        item["tiktok_events"]=(tiktok or {}).get("events",[])
        item["tiktok_is_aigc"]=(tiktok or {}).get("is_aigc")
        item["tiktok_reconciliation_required"]=bool(
            tiktok and tiktok.get("status")=="reconciliation_required"
        )
        if item["upload_status"]!="uploaded" or (
            item["tiktok_eligible"] and item["tiktok_status"]!="publish_complete"
        ):
            pending.append(item)
    return {"items":pending}


@app.post("/api/review/{job_id}/policy-evidence")
def update_review_policy_evidence(
    job_id:str, body:PolicyEvidenceInput,
    x_review_token:str|None=Header(default=None)
):
    require_review_access(x_review_token)
    declarations=body.model_dump(exclude={"reviewer_id"},exclude_none=True)
    try:
        return review_store.update_policy_evidence(
            job_id,body.reviewer_id,declarations
        )
    except ReviewNotFound:
        raise HTTPException(404,"Production job not found")
    except ReviewConflict as e:
        raise HTTPException(409,str(e))
    except ValueError as e:
        raise HTTPException(422,str(e))


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
        existing=media_stager.staged_path(job_id)
        if existing.is_file() and not existing.is_symlink():
            return {"media_path":existing.name,"size_bytes":existing.stat().st_size,
                    "already_staged":True}
        return media_stager.stage(job_id,video["artifact_url"])
    except MediaStagingError as e:
        raise HTTPException(502,str(e))


@app.post("/api/production/jobs/{job_id}/cleanup-media")
def cleanup_production_media(job_id:str,x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    try:
        return media_stager.cleanup_uploaded(job_id,youtube_upload_store)
    except MediaStagingError as e:
        raise HTTPException(409,str(e))


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


@app.post("/api/youtube/uploads/{job_id}/reconcile")
def reconcile_youtube_upload(job_id:str,body:YouTubeUploadReconciliation,
                              x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    if not body.confirmed:
        raise HTTPException(422,"Explicit operator confirmation is required")
    if body.outcome=="uploaded" and not body.video_id:
        raise HTTPException(422,"A verified YouTube video ID is required")
    try:
        return youtube_upload_store.reconcile(
            job_id,body.outcome,body.video_id,body.note,body.operator_id
        )
    except YouTubeUploadError as e:
        raise HTTPException(409,str(e))


@app.post("/api/youtube/uploads/{job_id}/resolve-late-result")
def resolve_late_youtube_upload(job_id:str,body:YouTubeLateSuccessResolution,
                                x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    try:
        return youtube_upload_store.resolve_late_success(
            job_id,body.operator_id,body.note,body.video_id
        )
    except YouTubeUploadError as e:
        raise HTTPException(409,str(e))


@app.post("/api/youtube/videos/{video_id}/refresh-metrics")
def refresh_youtube_metrics(video_id:str,x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    try:
        return youtube_publisher.refresh_metrics(video_id)
    except YouTubeUploadError as e:
        raise HTTPException(502,str(e))

@app.get("/api/tiktok/oauth/start")
def start_tiktok_oauth(
    response:Response,x_review_token:str|None=Header(default=None)
):
    require_review_access(x_review_token)
    try:
        result=tiktok_oauth_manager.start_authorization()
        response.set_cookie(
            "tiktok_oauth_state",result["state"],max_age=600,
            httponly=True,secure=True,samesite="lax",
            path="/api/tiktok/oauth/callback"
        )
        result.pop("state",None)
        return result
    except TikTokOAuthError as e:
        raise HTTPException(503,str(e))


@app.get("/api/tiktok/oauth/callback")
def tiktok_oauth_callback(
    request:Request,code:str|None=None,state:str|None=None,
    error:str|None=None,error_description:str|None=None
):
    cookie_state=request.cookies.get("tiktok_oauth_state")
    if error or not state or not cookie_state or not secrets.compare_digest(cookie_state,state):
        redirect=RedirectResponse(
            url="/?tiktok_oauth=denied" if error else "/?tiktok_oauth=error",
            status_code=303
        )
        redirect.delete_cookie("tiktok_oauth_state",path="/api/tiktok/oauth/callback")
        return redirect
    try:
        tiktok_oauth_manager.exchange_code(code,state)
        redirect=RedirectResponse(url="/?tiktok_oauth=connected",status_code=303)
    except TikTokOAuthError:
        redirect=RedirectResponse(url="/?tiktok_oauth=error",status_code=303)
    redirect.delete_cookie("tiktok_oauth_state",path="/api/tiktok/oauth/callback")
    return redirect


@app.get("/api/tiktok/oauth/status")
def tiktok_oauth_status(x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    result=tiktok_oauth_manager.status()
    if not result.get("connected") and os.getenv("TIKTOK_ACCESS_TOKEN"):
        result={"connected":True,"status":"static_token_configured","mode":"static_env"}
    return result


@app.post("/api/tiktok/oauth/disconnect")
def disconnect_tiktok_oauth(x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    if os.getenv("TIKTOK_ACCESS_TOKEN"):
        raise HTTPException(
            409,"Static TIKTOK_ACCESS_TOKEN is configured; remove it from the runtime before disconnecting OAuth."
        )
    try:
        return tiktok_oauth_manager.disconnect()
    except TikTokOAuthError as e:
        raise HTTPException(502,str(e))


@app.get("/api/tiktok/creator-info")
def get_tiktok_creator_info(x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    try:
        return tiktok_publisher.creator_info()
    except TikTokPublishError as e:
        raise HTTPException(502,str(e))


@app.post("/api/tiktok/publish/{job_id}",status_code=201)
def publish_tiktok_video(job_id:str,body:TikTokPublishRequest,
                         x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    try:
        return tiktok_publisher.publish_private_approved(
            job_id,body.media_path,review_store,body.title,body.operator_id,
            explicit_consent=body.explicit_consent,
            brand_content_toggle=body.brand_content_toggle,
            brand_organic_toggle=body.brand_organic_toggle
        )
    except ReviewNotFound:
        raise HTTPException(404,"Production job not found")
    except TikTokPublishError as e:
        raise HTTPException(409,str(e))


@app.get("/api/tiktok/publications/{job_id}")
def get_tiktok_publication(job_id:str,x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    result=tiktok_publish_store.get(job_id)
    if result is None:
        raise HTTPException(404,"TikTok publication record not found")
    return result


@app.post("/api/tiktok/publications/{job_id}/refresh-status")
def refresh_tiktok_publication_status(job_id:str,x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    try:
        return tiktok_publisher.refresh_status(job_id)
    except TikTokPublishError as e:
        raise HTTPException(409,str(e))



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


@app.post("/api/trends/{trend_id}/draft-production",status_code=201)
def draft_production_from_trend(trend_id:str,body:TrendProductionDraft,
                                x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    try:
        trend=trend_store.get(trend_id)
        if trend is None:
            raise HTTPException(404,"Trend signal not found")
        brand=next((item for item in brand_store.list(active_only=True)
                    if body.brand in (item["slug"],item["name"])),None)
        if brand is None:
            raise HTTPException(422,"Unknown or inactive brand")
        config=brand["config"]
        region=trend.get("region")
        if region not in config.get("regions",[]):
            raise HTTPException(422,"Trend region is not enabled for this brand")
        if body.language not in config.get("languages",[]):
            raise HTTPException(422,"Language is not enabled for this brand")
        title=(trend.get("title") or "").strip()
        if not title:
            raise HTTPException(422,"Trend signal has no usable title")
        profile=config
        brief={
            "brand":brand["name"],"region":region,"language":body.language,
            "topic":title[:500],
            "idempotency_key":body.idempotency_key or
                f"trend:{trend_id}:{brand['slug']}:{body.language}",
            "brand_profile":{
                "positioning":profile.get("positioning",""),
                "audience":profile.get("audience",""),
                "tone":profile.get("tone",[]),
                "risk_level":profile.get("risk_level","standard"),
                "review_rules":profile.get("review_rules",[]),
            },
            "trend_context":{
                "source":trend.get("source"),"title":title,
                "url":trend.get("url"),"summary":trend.get("summary"),
                "published_at":trend.get("published_at"),"region":region,
            },
        }
        submitted=submit_production(queue,production_store,brief)
        recommendation_evaluation_store.link_production(
            trend_id,brand["slug"],submitted["job"]["id"]
        )
        return submitted
    except IdempotencyConflict as e:
        raise HTTPException(409,str(e))
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
    competitor_channel_ids:list[str]=Field(default_factory=list,max_length=10)


@app.post("/api/opportunities/score",status_code=201)
def create_opportunity_score(body:OpportunityInput,x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    try:
        data=body.model_dump()
        channel_ids=data.pop("competitor_channel_ids",[])
        result=score_opportunity(data)
        benchmark=analyze_competition(result.get("title",""),channel_ids,competitor_store)
        observed=benchmark["observed_videos"]
        matched=benchmark["topic_matched_videos"]
        pressure=min(1.0,matched/max(1,len(channel_ids)*3)) if observed else None
        penalty=round(10*pressure,2) if pressure is not None else 0.0
        result["priority_score"]=round(max(0.0,result["priority_score"]-penalty),2)
        result["score_breakdown"]["competitor_pressure_penalty"]=penalty
        result["competitive_context"]={
            **benchmark,"competition_pressure_index":round(pressure,3) if pressure is not None else None,
            "score_adjustment":-penalty if observed else 0.0,
        }
        return opportunity_store.save(result)
    except ValueError as e:
        raise HTTPException(422,str(e))


def _build_trend_recommendations(region, limit):
    trends=trend_store.list(region=region,limit=200)
    brands=brand_store.list(active_only=True)
    performance=performance_analyzer.analyze()
    performance_by_brand={item["brand"]:item for item in performance.get("brands",[])}
    return rank_trend_candidates(
        trends,brands,competitor_store,limit,
        performance_by_brand=performance_by_brand,
        performance_videos=performance.get("videos",[]),
        performance_cohorts=performance.get("cohorts",[])
    )


def _trend_recommendation_payload(ranked):
    return {
        "items":ranked,
        "count":len(ranked),
        "method":"100-point editorial score: freshness (0-40), editorial brand fit (0-40), source provenance completeness (0-10), and topic distinctiveness (0-10). Brand/topic-matched historical performance cohorts are displayed separately and are not scored.",
        "warning":"Editorial recommendation score only. Brand/region/topic-matched cohort evidence is contextual, may be sparse, and does not alter ranking until held-out validation demonstrates stable improvement. This is not a profitability forecast, search-volume estimate, or automatic production approval."
    }


@app.get("/api/trends/recommendations")
def trend_recommendations(region:str|None=None,limit:int=30,x_review_token:str|None=Header(default=None)):
    """Read-only recommendation retrieval; does not create an evaluation exposure."""
    require_review_access(x_review_token)
    return _trend_recommendation_payload(_build_trend_recommendations(region,limit))


@app.post("/api/trends/recommendations/snapshot")
def capture_trend_recommendations(region:str|None=None,limit:int=30,
                                  x_review_token:str|None=Header(default=None)):
    """Explicitly capture the recommendation set returned to the production workspace."""
    require_review_access(x_review_token)
    ranked=_build_trend_recommendations(region,limit)
    exposure=recommendation_evaluation_store.record_run(region,ranked)
    return {
        **_trend_recommendation_payload(ranked),
        "evaluation_run_id":exposure["run_id"],
        "evaluation_candidates_recorded":exposure["recorded_candidates"],
        "evaluation_snapshot_deduplicated":exposure.get("deduplicated",False),
    }

@app.get("/api/recommendations/evaluation")
def recommendation_evaluation(x_review_token:str|None=Header(default=None)):
    """Report chronological holdout diagnostics for selected recommendation outcomes."""
    require_review_access(x_review_token)
    return recommendation_evaluation_store.evaluate(performance_analyzer.analyze())


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
@app.get("/api/queue/control")
def queue_control(x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    return {"control":queue.worker_control(),"events":queue.worker_control_events(30)}

@app.post("/api/queue/pause")
def pause_queue(body:QueueControlAction,x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    operator_id=body.operator_id.strip()
    note=body.note.strip()
    if not operator_id or not note:
        raise HTTPException(422,"operator_id and note must not be blank")
    control=queue.pause(note,actor=operator_id)
    return {"control":control,"events":queue.worker_control_events(30)}

@app.post("/api/queue/resume")
def resume_queue(body:QueueControlAction,x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    if not body.operator_id.strip() or not body.note.strip():
        raise HTTPException(422,"operator_id and note must not be blank")
    try:
        control=queue.resume(actor=body.operator_id.strip(),note=body.note.strip())
        return {"control":control,"events":queue.worker_control_events(30)}
    except ValueError as e:
        raise HTTPException(409,str(e))

@app.post("/api/jobs",status_code=201)
def enqueue(body:Enqueue,x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    try:
        return queue.enqueue(**body.model_dump())
    except IdempotencyConflict as e:
        raise HTTPException(409,str(e))
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
    result=build_preflight()
    oauth_status=tiktok_oauth_manager.status()
    tiktok_connected=bool(oauth_status.get("connected") or os.getenv("TIKTOK_ACCESS_TOKEN"))
    result["checks"]["tiktok_publish"]={
        "configured":tiktok_connected,
        "missing":[] if tiktok_connected else [
            "TikTok OAuth account connection or TIKTOK_ACCESS_TOKEN"
        ],
    }
    result["capabilities"]["tiktok_private_publish_configured"]=tiktok_connected
    result["tiktok_oauth"]=oauth_status
    if tiktok_connected:
        result["missing"]=[item for item in result["missing"]
                           if item!="TIKTOK_ACCESS_TOKEN"]
    elif "TikTok OAuth account connection or TIKTOK_ACCESS_TOKEN" not in result["missing"]:
        result["missing"].append("TikTok OAuth account connection or TIKTOK_ACCESS_TOKEN")
    return result


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

@app.get("/", include_in_schema=False)
def portal_home():
    return FileResponse(str(FRONTEND_DIR / "index.html"))

app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR)), name="assets")

if __name__=="__main__":
    import uvicorn
    uvicorn.run("app:app",host="0.0.0.0",port=int(os.getenv("PORT","8502")))
