import os
import sqlite3
import secrets
import logging
from typing import Any, Literal, Annotated
from fastapi import FastAPI, HTTPException, Header, Request, Response, Query
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
from reviewer_auth import resolve_review_principal, ReviewCredentialConfigurationError
from youtube_publishing import YouTubeUploadStore, YouTubePublisher, YouTubeUploadError
from tiktok_publishing import TikTokPublishStore, TikTokPublisher, TikTokPublishError
from tiktok_oauth import TikTokOAuthStore, TikTokOAuthManager, TikTokOAuthError
from tiktok_metrics import TikTokMetricsStore
from youtube_analytics import YouTubeAnalyticsStore
from ledger import LedgerStore
from performance_insights import PerformanceAnalyzer
from recommendation_evaluation import RecommendationEvaluationStore
from lifecycle_consistency import inspect_lifecycle_consistency
from operator_recovery import build_operator_recovery_plan
from failure_analysis import classify_failure
from stage_performance import build_stage_performance
from pipeline_performance import build_pipeline_performance
from operational_economics import build_operational_economics
from scheduler_store import ScheduleStore
from media_staging import MediaStager, MediaStagingError
from preflight import build_preflight
from policy_engine import POLICY_VERSION
from api_rate_limit import ApiRateLimitMiddleware, SQLiteRateLimitStore
from operator_rbac import has_permission, OperatorRoleConfigurationError

queue=JobQueue(os.getenv("NEXUS_DB_PATH","data/nexus.sqlite3"),int(os.getenv("NEXUS_LEASE_SECONDS","90")))
class TikTokOAuthAccessLogRedaction(logging.Filter):
    """Prevent authorization codes and OAuth state values entering access logs."""
    def filter(self, record):
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3:
            path = args[2]
            if isinstance(path, str) and path.startswith("/api/tiktok/oauth/callback"):
                sanitized = list(args)
                sanitized[2] = "/api/tiktok/oauth/callback?[REDACTED]"
                record.args = tuple(sanitized)
        return True


oauth_log_filter = TikTokOAuthAccessLogRedaction()
uvicorn_access_logger = logging.getLogger("uvicorn.access")
uvicorn_access_logger.addFilter(oauth_log_filter)
for access_handler in uvicorn_access_logger.handlers:
    access_handler.addFilter(oauth_log_filter)


app=FastAPI(title="NEXUS STUDIO PRO API",version="0.1.0")
rate_limit_store=SQLiteRateLimitStore(os.getenv("NEXUS_DB_PATH","data/nexus.sqlite3"))
app.add_middleware(
    ApiRateLimitMiddleware,
    store=rate_limit_store,
    trusted_proxy_cidrs=os.getenv("NEXUS_TRUSTED_PROXY_CIDRS", ""),
    limits={
        "default": int(os.getenv("NEXUS_API_RATE_LIMIT_PER_MINUTE", "120")),
        "auth": int(os.getenv("NEXUS_API_AUTH_RATE_LIMIT_PER_MINUTE", "20")),
        "publish": int(os.getenv("NEXUS_API_PUBLISH_RATE_LIMIT_PER_MINUTE", "10")),
        "control": int(os.getenv("NEXUS_API_CONTROL_RATE_LIMIT_PER_MINUTE", "30")),
        "review": int(os.getenv("NEXUS_API_REVIEW_RATE_LIMIT_PER_MINUTE", "60")),
        "production": int(os.getenv("NEXUS_API_PRODUCTION_RATE_LIMIT_PER_MINUTE", "30")),
    },
)
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
tiktok_metrics_store=TikTokMetricsStore(os.getenv("NEXUS_DB_PATH","data/nexus.sqlite3"))
youtube_analytics_store=YouTubeAnalyticsStore(os.getenv("NEXUS_DB_PATH","data/nexus.sqlite3"))
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

class RecommendationExperimentCreate(BaseModel):
    name:str=Field(min_length=1,max_length=160)
    operator_id:str=Field(min_length=1,max_length=128)
    control_label:str=Field(default="control",min_length=1,max_length=64)
    treatment_label:str=Field(default="treatment",min_length=1,max_length=64)
    treatment_allocation_basis_points:int=Field(default=5000,ge=1000,le=9000)


class RecommendationExperimentAssignment(BaseModel):
    participant_key:str=Field(min_length=1,max_length=256)


class RecommendationRenderedExposure(BaseModel):
    event_id:str=Field(min_length=36,max_length=36)
    trend_id:str=Field(min_length=1,max_length=256)
    visibility_ms:int=Field(ge=1000,le=30000)


class RecommendationRenderedExposureBatch(BaseModel):
    run_id:str=Field(min_length=1,max_length=128)
    exposures:list[RecommendationRenderedExposure]=Field(min_length=1,max_length=100)


class QueueControlAction(BaseModel):
    operator_id:str=Field(min_length=1,max_length=128)
    note:str=Field(min_length=1,max_length=2000)
    recovery_confirmed:bool=False

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
    privacy_level:Literal["SELF_ONLY"]
    explicit_consent:bool
    brand_content_toggle:bool
    brand_organic_toggle:bool


class YouTubeUploadReconciliation(BaseModel):
    outcome:Literal["uploaded","not_uploaded"]
    confirmed:bool
    video_id:str|None=Field(default=None,min_length=1,max_length=128)
    note:str=Field(min_length=1,max_length=2000)
    operator_id:str=Field(min_length=1,max_length=128)

class TikTokPublicationReconciliation(BaseModel):
    outcome:Literal["published","not_published"]
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
    instance_token:str=Field(min_length=1,max_length=128)

class TrendCollect(BaseModel):
    region:str="US"
    query:str=Field(min_length=2,max_length=200)
    limit:int=30
    include_hacker_news:bool=False

class TrendProductionDraft(BaseModel):
    brand:str=Field(min_length=1,max_length=100)
    language:str=Field(min_length=2,max_length=40)
    recommendation_candidate_id:str|None=Field(default=None,max_length=128)
    idempotency_key:str|None=None

class RecommendationSkipFeedback(BaseModel):
    trend_id:str=Field(min_length=1,max_length=128)
    brand_slug:str=Field(min_length=1,max_length=100)
    recommendation_candidate_id:str=Field(min_length=1,max_length=128)
    reviewer_id:str=Field(min_length=1,max_length=128)
    reason:str=Field(default="",max_length=1000)

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
    require_review_permission(x_review_token, "brand.manage")
    try:
        return brand_store.set_active(slug,body.active)
    except BrandNotFound:
        raise HTTPException(404,"Brand not found")

@app.post("/api/production/jobs",status_code=201)
def create_production_job(body:ProductionBrief,x_review_token:str|None=Header(default=None)):
    require_review_permission(x_review_token, "production.create")
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

@app.get("/api/lifecycle/jobs/{job_id}")
def get_job_lifecycle(job_id:str,x_review_token:str|None=Header(default=None)):
    """Return the authoritative cross-system lifecycle record for one production job."""
    require_review_access(x_review_token)
    try:
        job=queue.get(job_id)
    except JobNotFound:
        raise HTTPException(404,"Job not found")
    if job.get("job_type")!="short_video_production":
        raise HTTPException(409,"Job is not a short-video production job")
    production=production_store.get(job_id)
    if production is None:
        raise HTTPException(404,"Production record not found")
    decisions=review_store.history(job_id)
    latest_review=decisions[-1] if decisions else None
    youtube=youtube_upload_store.get(job_id)
    tiktok=tiktok_publish_store.get(job_id)
    queue_events=queue.events(job_id)
    timeline=[]
    for event in queue_events:
        timeline.append({
            "stage":"queue","event":event.get("event_type"),
            "outcome":event.get("to_status"),"occurred_at":event.get("created_at"),
            "attempt_id":None,"reference_id":None,
        })
    for artifact in production.get("artifacts",[]):
        timeline.append({
            "stage":"production","event":"artifact_created",
            "outcome":artifact.get("stage") or artifact.get("artifact_type"),
            "occurred_at":artifact.get("created_at"),"attempt_id":None,
            "reference_id":artifact.get("id"),
        })
    for decision in decisions:
        timeline.append({
            "stage":"human_review","event":"review_decision",
            "outcome":decision.get("decision"),"occurred_at":decision.get("created_at"),
            "attempt_id":None,"reference_id":decision.get("id"),
        })
    for event in (youtube or {}).get("events",[]):
        timeline.append({
            "stage":"youtube","event":event.get("event_type"),
            "outcome":event.get("resulting_status") or event.get("outcome"),
            "occurred_at":event.get("created_at"),"attempt_id":event.get("attempt_id"),
            "reference_id":event.get("video_id"),
        })
    for event in (tiktok or {}).get("events",[]):
        timeline.append({
            "stage":"tiktok","event":event.get("event_type"),
            "outcome":event.get("outcome"),"occurred_at":event.get("created_at"),
            "attempt_id":event.get("attempt_id"),
            "reference_id":event.get("video_id") or event.get("publish_id"),
        })
    timeline.sort(key=lambda item:str(item.get("occurred_at") or ""))
    return {
        "job":job,
        "queue_events":queue_events,
        "timeline":timeline,
        "production":production,
        "review":{"history":decisions,"latest":latest_review},
        "publishing":{"youtube":youtube,"tiktok":tiktok},
    }


@app.get("/api/lifecycle/jobs/{job_id}/consistency")
def get_job_lifecycle_consistency(job_id:str,x_review_token:str|None=Header(default=None)):
    """Read-only cross-platform consistency diagnostics; never retries or mutates."""
    require_review_access(x_review_token)
    try:
        job=queue.get(job_id)
    except JobNotFound:
        raise HTTPException(404,"Job not found")
    if job.get("job_type")!="short_video_production":
        raise HTTPException(409,"Job is not a short-video production job")
    production=production_store.get(job_id)
    if production is None:
        raise HTTPException(404,"Production record not found")
    decisions=review_store.history(job_id)
    latest=decisions[-1] if decisions else None
    result=inspect_lifecycle_consistency(
        job,production,{"latest":latest},
        youtube_upload_store.get(job_id),tiktok_publish_store.get(job_id),
    )
    return {"job_id":job_id,**result}


@app.get("/api/lifecycle/jobs/{job_id}/recovery")
def get_job_recovery_plan(job_id:str,x_review_token:str|None=Header(default=None)):
    """Return an operator checklist; this endpoint never performs recovery actions."""
    require_review_access(x_review_token)
    try:
        job=queue.get(job_id)
    except JobNotFound:
        raise HTTPException(404,"Job not found")
    if job.get("job_type")!="short_video_production":
        raise HTTPException(409,"Job is not a short-video production job")
    production=production_store.get(job_id)
    if production is None:
        raise HTTPException(404,"Production record not found")
    decisions=review_store.history(job_id)
    latest=decisions[-1] if decisions else None
    return build_operator_recovery_plan(
        job,production,{"latest":latest},
        youtube_upload_store.get(job_id),tiktok_publish_store.get(job_id),
    )


@app.get("/api/lifecycle/jobs/{job_id}/overview")
def get_job_lifecycle_overview(job_id:str,x_review_token:str|None=Header(default=None)):
    """Return a single read-only operational view across all production stages."""
    require_review_access(x_review_token)
    trace=get_job_lifecycle(job_id,x_review_token)
    consistency=get_job_lifecycle_consistency(job_id,x_review_token)
    recovery=get_job_recovery_plan(job_id,x_review_token)
    failure=get_job_failure_analysis(job_id,x_review_token)
    job=trace["job"]
    production=trace["production"]
    review=trace["review"].get("latest") or {}
    publishing=trace["publishing"]
    youtube=publishing.get("youtube") or {}
    tiktok=publishing.get("tiktok") or {}
    def stage(name,status,occurred_at=None,reference_id=None):
        return {"stage":name,"status":status or "not_started",
                "occurred_at":occurred_at,"reference_id":reference_id}
    artifacts=production.get("artifacts") or []
    latest_artifact=artifacts[-1] if artifacts else {}
    stages=[
        stage("queue",job.get("status"),job.get("updated_at"),job.get("id")),
        stage("production",production.get("status"),production.get("updated_at"),
              latest_artifact.get("id")),
        stage("human_review",review.get("decision"),review.get("created_at"),review.get("id")),
        stage("youtube",youtube.get("status"),youtube.get("updated_at"),youtube.get("video_id")),
        stage("tiktok",tiktok.get("status"),tiktok.get("updated_at"),
              tiktok.get("video_id") or tiktok.get("publish_id")),
    ]
    performance=build_stage_performance(job,trace.get("queue_events",[]))
    return {
        "job_id":job_id,
        "performance":performance,
        "summary":{"brand":production.get("brand"),"topic":production.get("topic"),
                   "queue_status":job.get("status"),"production_status":production.get("status"),
                   "current_stage":production.get("current_stage"),
                   "latest_review":review.get("decision"),
                   "youtube_status":youtube.get("status") or "not_started",
                   "tiktok_status":tiktok.get("status") or "not_started",
                   "consistency_status":consistency.get("status"),
                   "failure_category":(failure.get("latest_failure") or {}).get("category")},
        "stages":stages,
        "trace":trace,
        "consistency":consistency,
        "recovery":recovery,
        "failure":failure,
        "read_only":True,"automatic_retry_performed":False,
        "remote_status_refresh_performed":False,"publishing_performed":False,
    }
@app.get("/api/lifecycle/queue")
def get_lifecycle_queue(
    limit:int=50, offset:int=0, status:str|None=None,
    x_review_token:str|None=Header(default=None),
):
    """Bounded, read-only global production queue and lifecycle risk overview."""
    require_review_access(x_review_token)
    if status and status not in {
        "queued","running","review_pending","approved","rejected",
        "revision_requested","failed_retriable","failed_terminal","cancelled",
    }:
        raise HTTPException(422,"Unsupported queue status filter")
    page=queue.list_jobs(
        job_type="short_video_production",limit=limit,offset=offset,status=status
    )
    items=[]
    risk_counts={"blocked":0,"attention_required":0,"consistent":0,"missing_production":0}
    production_status_counts={}
    summaries=queue.lifecycle_summaries([job["id"] for job in page["items"]])
    for job in page["items"]:
        job_id=job["id"]
        snapshot=summaries.get(job_id)
        if snapshot is None or snapshot.get("production_status") is None:
            production=None
            consistency={"status":"blocked","findings":[{
                "code":"production_record_missing","severity":"blocker",
                "message":"Durable production record is missing","stage":"production",
            }]}
            latest=None
        else:
            production={
                "status":snapshot.get("production_status"),
                "current_stage":snapshot.get("current_stage"),
                "brand":snapshot.get("brand"),"topic":snapshot.get("topic"),
            }
            latest={"decision":snapshot.get("latest_review_decision")} if snapshot.get("latest_review_decision") else None
            youtube={
                "status":snapshot.get("youtube_status"),
                "attempt_id":snapshot.get("youtube_attempt_id"),
                "video_id":snapshot.get("youtube_video_id"),
                "events":snapshot.get("youtube_events") or [],
            }
            tiktok={
                "status":snapshot.get("tiktok_status"),
                "attempt_id":snapshot.get("tiktok_attempt_id"),
                "video_id":snapshot.get("tiktok_video_id"),
                "events":snapshot.get("tiktok_events") or [],
            }
            consistency=inspect_lifecycle_consistency(
                job,production,{"latest":latest},youtube,tiktok,
            )
        risk=consistency["status"]
        risk_counts[risk]=risk_counts.get(risk,0)+1
        production_state=(production or {}).get("status") or "missing"
        production_status_counts[production_state]=production_status_counts.get(production_state,0)+1
        if production is None:
            risk_counts["missing_production"]+=1
        findings=consistency.get("findings",[])
        items.append({
            "job_id":job_id,"status":job.get("status"),
            "production_status":(production or {}).get("status"),
            "current_stage":(production or {}).get("current_stage"),
            "brand":(production or {}).get("brand"),
            "topic":(production or {}).get("topic"),
            "updated_at":job.get("updated_at"),
            "attempt":job.get("attempt"),"max_attempts":job.get("max_attempts"),
            "error_code":job.get("error_code"),
            "risk_status":risk,
            "blocker_count":sum(1 for f in findings if f.get("severity")=="blocker"),
            "warning_count":sum(1 for f in findings if f.get("severity")=="warning"),
            "findings":findings[:8],
            "latest_review_decision":(latest or {}).get("decision"),
        })
    return {
        "items":items,"total":page["total"],"limit":page["limit"],
        "offset":page["offset"],"status_counts":page["status_counts"],
        "production_status_counts":production_status_counts,
        "risk_counts":risk_counts,"read_only":True,
        "automatic_retry_performed":False,
    }


@app.post("/api/production/jobs/{job_id}/execute")
def execute_production_job(job_id:str,body:ProductionExecute,x_review_token:str|None=Header(default=None)):
    require_review_permission(x_review_token, "production.execute")
    try:
        job=queue.get(job_id)
        if job["job_type"]!="short_video_production":
            raise HTTPException(409,"Job is not a short-video production job")
        if job["status"]!="running" or job["worker_id"]!=body.worker_id or job["lease_token"]!=body.lease_token:
            raise HTTPException(409,"Current worker lease is required")
        queue.assert_current_worker_instance(body.worker_id,body.instance_token)
        result=production_pipeline.execute(
            job_id,job["payload"],worker_id=body.worker_id,lease_token=body.lease_token,
            instance_token=body.instance_token
        )
        queue.finish(job_id,body.worker_id,body.lease_token,
                     {"production_status":"review_pending"},instance_token=body.instance_token)
        production_store.reconcile_review_pending(queue)
        return production_store.get(job_id)
    except ProviderError as e:
        try:
            queue.fail(job_id,body.worker_id,body.lease_token,
                       "provider_"+e.stage,str(e),e.retryable,instance_token=body.instance_token)
        except Exception:
            pass
        try:
            queue.pause(f"API provider failure at {e.stage}: {e}", job_id,
                        worker_id=body.worker_id,instance_token=body.instance_token)
        except Exception:
            pass
        raise HTTPException(502,{"stage":e.stage,"error":str(e),"retryable":e.retryable})
    except JobNotFound:
        raise HTTPException(404,"Job not found")
    except ProductionLeaseConflict as e:
        try:
            queue.pause(f"API production lease conflict: {e}", job_id,
                        worker_id=body.worker_id,instance_token=body.instance_token)
        except Exception:
            pass
        raise HTTPException(409,str(e))
    except LeaseConflict as e:
        try:
            queue.pause(f"API queue lease conflict: {e}", job_id,
                        worker_id=body.worker_id,instance_token=body.instance_token)
        except Exception:
            pass
        raise HTTPException(409,str(e))
    except HTTPException:
        raise
    except Exception as e:
        try:
            queue.fail(job_id,body.worker_id,body.lease_token,
                       "pipeline_internal_error",type(e).__name__,False,
                       instance_token=body.instance_token)
        except Exception:
            pass
        try:
            queue.pause(f"API pipeline internal error: {type(e).__name__}: {e}", job_id,
                        worker_id=body.worker_id,instance_token=body.instance_token)
        except Exception:
            pass
        raise HTTPException(500,"Production pipeline failed internally")


def require_review_access(token):
    try:
        reviewer_id = resolve_review_principal(token)
    except ReviewCredentialConfigurationError:
        # Broken operator configuration must never fall back to a shared token.
        raise HTTPException(503,"Review authentication is not configured safely")
    if not reviewer_id:
        raise HTTPException(401,"Valid review token required")
    return reviewer_id


def require_review_permission(token, permission):
    """Authenticate the bearer token and enforce its configured operator role."""
    operator_id = require_review_access(token)
    try:
        allowed = has_permission(operator_id, permission)
    except OperatorRoleConfigurationError:
        raise HTTPException(503,"Operator role configuration is not configured safely")
    if not allowed:
        raise HTTPException(403,"Operator role does not grant this action")
    return operator_id


@app.get("/api/review/pending")
def pending_reviews(limit:int=50, x_review_token:str|None=Header(default=None)):
    require_review_permission(x_review_token, "review.read")
    production_store.reconcile_review_pending(queue)
    return {"items":review_store.list_pending(limit)}



@app.get("/api/review/approved")
def approved_reviews(limit:int=50,x_review_token:str|None=Header(default=None)):
    require_review_permission(x_review_token, "review.read")
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
    authenticated_reviewer = require_review_permission(x_review_token, "review.evidence")
    declarations=body.model_dump(exclude={"reviewer_id"},exclude_none=True)
    try:
        return review_store.update_policy_evidence(
            job_id,authenticated_reviewer or body.reviewer_id,declarations
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
    authenticated_reviewer = require_review_permission(x_review_token, "review.decide")
    try:
        staged_path=media_stager.staged_path(job_id)
        return review_store.decide(
            job_id,"approved",authenticated_reviewer or body.reviewer_id,body.comment,
            staged_media_path=staged_path
        )
    except ReviewNotFound:
        raise HTTPException(404,"Production job not found")
    except ReviewConflict as e:
        raise HTTPException(409,str(e))
    except ValueError as e:
        raise HTTPException(422,str(e))


@app.post("/api/review/{job_id}/reject")
def reject_review(job_id:str, body:ReviewDecision,
                  x_review_token:str|None=Header(default=None)):
    authenticated_reviewer = require_review_permission(x_review_token, "review.decide")
    try:
        return review_store.decide(job_id,"rejected",authenticated_reviewer or body.reviewer_id,body.comment)
    except ReviewNotFound:
        raise HTTPException(404,"Production job not found")
    except ReviewConflict as e:
        raise HTTPException(409,str(e))
    except ValueError as e:
        raise HTTPException(422,str(e))


@app.post("/api/review/{job_id}/request-revision")
def request_revision(job_id:str, body:ReviewDecision,
                     x_review_token:str|None=Header(default=None)):
    authenticated_reviewer = require_review_permission(x_review_token, "review.decide")
    try:
        return review_store.decide(job_id,"revision_requested",authenticated_reviewer or body.reviewer_id,body.comment)
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




def require_canonical_staged_media(job_id:str,media_path:str):
    """Accept only the current job's deterministic staging file, never an arbitrary media-root file."""
    expected=media_stager.staged_path(job_id)
    candidate=Path(media_path)
    if not candidate.is_absolute():
        candidate=media_stager.media_dir/candidate
    try:
        resolved=candidate.resolve(strict=True)
        resolved.relative_to(media_stager.media_dir)
    except (OSError,ValueError):
        raise HTTPException(409,"Media must be staged for this production job before publishing")
    if candidate.is_symlink() or not resolved.is_file() or resolved!=expected.resolve():
        raise HTTPException(409,"Media path does not match this job's canonical staged artifact")
    return str(resolved)


@app.post("/api/production/jobs/{job_id}/stage-media")
def stage_production_media(job_id:str,x_review_token:str|None=Header(default=None)):
    require_review_permission(x_review_token, "media.manage")
    production=production_store.get(job_id)
    if production is None:
        raise HTTPException(404,"Production job not found")
    if production["status"] not in ("rendered","review_pending"):
        raise HTTPException(409,"Only rendered production jobs can be staged")
    video=next((item for item in production["artifacts"]
                if item["artifact_type"]=="video" and item["artifact_url"]),None)
    if video is None:
        raise HTTPException(409,"Rendered video artifact is not available")
    try:
        # Stage the exact renderer artifact before human approval so its bytes
        # can be fingerprinted and bound into the approval record.
        return media_stager.stage(job_id,video["artifact_url"])
    except MediaStagingError as e:
        raise HTTPException(502,str(e))


@app.post("/api/production/jobs/{job_id}/cleanup-media")
def cleanup_production_media(job_id:str,x_review_token:str|None=Header(default=None)):
    require_review_permission(x_review_token, "media.manage")
    try:
        return media_stager.cleanup_uploaded(job_id,youtube_upload_store)
    except MediaStagingError as e:
        raise HTTPException(409,str(e))


@app.post("/api/youtube/upload/{job_id}",status_code=201)
def upload_youtube_video(job_id:str,body:YouTubeUploadRequest,
                         x_review_token:str|None=Header(default=None)):
    require_review_permission(x_review_token, "publish.execute")
    staged_path=require_canonical_staged_media(job_id,body.media_path)
    try:
        return youtube_publisher.upload_approved(
            job_id,staged_path,review_store,body.title,body.description,
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
    authenticated_operator = require_review_permission(x_review_token, "publish.reconcile")
    if not body.confirmed:
        raise HTTPException(422,"Explicit operator confirmation is required")
    if body.outcome=="uploaded" and not body.video_id:
        raise HTTPException(422,"A verified YouTube video ID is required")
    try:
        return youtube_upload_store.reconcile(
            job_id,body.outcome,body.video_id,body.note,
            authenticated_operator or body.operator_id
        )
    except YouTubeUploadError as e:
        raise HTTPException(409,str(e))


@app.post("/api/youtube/uploads/{job_id}/resolve-late-result")
def resolve_late_youtube_upload(job_id:str,body:YouTubeLateSuccessResolution,
                                x_review_token:str|None=Header(default=None)):
    authenticated_operator = require_review_permission(x_review_token, "publish.reconcile")
    try:
        return youtube_upload_store.resolve_late_success(
            job_id,authenticated_operator or body.operator_id,body.note,body.video_id
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
    require_review_permission(x_review_token, "publish.manage")
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
    request:Request,
    code:Annotated[str|None,Query(max_length=4096)]=None,
    state:Annotated[str|None,Query(max_length=256)]=None,
    error:Annotated[str|None,Query(max_length=128)]=None,
    error_description:Annotated[str|None,Query(max_length=1024)]=None
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
    require_review_permission(x_review_token, "publish.manage")
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
    authenticated_operator = require_review_permission(x_review_token, "publish.execute")
    staged_path=require_canonical_staged_media(job_id,body.media_path)
    try:
        return tiktok_publisher.publish_private_approved(
            job_id,staged_path,review_store,body.title,
            authenticated_operator or body.operator_id,
            explicit_consent=body.explicit_consent,
            privacy_level=body.privacy_level,
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


@app.post("/api/tiktok/publications/{job_id}/reconcile")
def reconcile_tiktok_publication(
    job_id:str, body:TikTokPublicationReconciliation,
    x_review_token:str|None=Header(default=None)
):
    authenticated_operator = require_review_permission(x_review_token, "publish.reconcile")
    try:
        return tiktok_publish_store.reconcile(
            job_id, body.outcome, authenticated_operator or body.operator_id, body.note,
            video_id=body.video_id, confirmed=body.confirmed,
        )
    except TikTokPublishError as e:
        raise HTTPException(409,str(e))


@app.post("/api/tiktok/publications/{job_id}/refresh-status")
def refresh_tiktok_publication_status(job_id:str,x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    try:
        return tiktok_publisher.refresh_status(job_id)
    except TikTokPublishError as e:
        raise HTTPException(409,str(e))



@app.post("/api/finance/ledger",status_code=201)
def record_financial_entry(body:LedgerEntry,x_review_token:str|None=Header(default=None)):
    require_review_permission(x_review_token, "finance.write")
    try:
        return ledger_store.record(body.model_dump())
    except (ValueError,KeyError) as e:
        raise HTTPException(422,str(e))


@app.get("/api/finance/report")
def financial_report(brand:str|None=None,from_date:str|None=None,to_date:str|None=None,
                     currency:str="USD",x_review_token:str|None=Header(default=None)):
    require_review_permission(x_review_token, "finance.read")
    try:
        return ledger_store.report(brand,from_date,to_date,currency)
    except ValueError as e:
        raise HTTPException(422,str(e))



@app.get("/api/performance/insights")
def performance_insights(brand:str|None=None,x_review_token:str|None=Header(default=None)):
    require_review_permission(x_review_token, "analytics.read")
    return performance_analyzer.analyze(brand)


@app.get("/api/youtube/analytics-metrics")
def youtube_analytics_metrics(limit:int=100,x_review_token:str|None=Header(default=None)):
    require_review_permission(x_review_token, "analytics.read")
    bounded=max(1,min(limit,200))
    items=youtube_analytics_store.recent_metrics(youtube_upload_store,bounded)
    return {
        "items": items,
        "count": len(items),
        "limit": bounded,
        "source": "YouTube Analytics API v2",
        "read_only": True,
        "ranking_score_adjustment": 0,
    }


@app.get("/api/tiktok/metrics")
def tiktok_metrics(limit:int=100,x_review_token:str|None=Header(default=None)):
    require_review_permission(x_review_token, "analytics.read")
    bounded=max(1,min(limit,200))
    items=tiktok_metrics_store.recent_metrics(tiktok_publish_store,bounded)
    return {
        "items": items,
        "count": len(items),
        "limit": bounded,
        "source": "TikTok Display API v2",
        "read_only": True,
        "ranking_score_adjustment": 0,
    }


@app.get("/api/metrics/collection-status")
def metrics_collection_status(x_review_token:str|None=Header(default=None)):
    require_review_permission(x_review_token, "analytics.read")
    interval=max(300,int(os.getenv("NEXUS_METRICS_COLLECTION_INTERVAL_SECONDS","21600")))
    youtube=youtube_upload_store.metrics_collection_status(interval*2)
    youtube["credentials_configured"]=all(os.getenv(key) for key in (
        "YOUTUBE_CLIENT_ID","YOUTUBE_CLIENT_SECRET","YOUTUBE_REFRESH_TOKEN"
    ))
    youtube["available_metrics"]=["view_count","like_count","comment_count"]
    youtube["unavailable_metrics"]=[
        "audience_retention","swipe_away_rate","watch_time","estimated_revenue"
    ]
    youtube_analytics = youtube_analytics_store.status(interval*4)
    youtube_analytics["credentials_configured"] = all(os.getenv(key) for key in (
        "YOUTUBE_CLIENT_ID","YOUTUBE_CLIENT_SECRET","YOUTUBE_REFRESH_TOKEN"
    ))
    youtube_analytics["scope_authorized"] = bool(
        youtube_analytics.get("last_success_at")
        and youtube_analytics["status"] not in ("scope_missing", "authorization_failed")
    )
    if not youtube_analytics["scope_authorized"] and youtube_analytics["status"] in (
        "not_started", "waiting_for_uploaded_videos"
    ):
        youtube_analytics["status"] = "scope_unverified"
        youtube_analytics["last_error"] = "yt-analytics.readonly consent has not been verified"
    tiktok = tiktok_metrics_store.status(tiktok_publish_store, interval*2)
    oauth_status = tiktok_oauth_manager.status()
    granted_scopes = {scope.strip() for scope in str(oauth_status.get("scope") or "").split(",")}
    tiktok["credentials_configured"] = bool(oauth_status.get("connected"))
    tiktok["required_scope"] = "video.list"
    tiktok["scope_authorized"] = "video.list" in granted_scopes
    if not tiktok["scope_authorized"] and tiktok["status"] in ("not_started", "not_configured"):
        tiktok["status"] = "scope_missing"
        tiktok["last_error"] = "TikTok reauthorization with video.list is required"
    return {
        "platforms": {"youtube": youtube, "youtube_analytics": youtube_analytics, "tiktok": tiktok},
        "collection_interval_seconds": interval,
        "read_only": True,
    }



@app.post("/api/schedules",status_code=201)
def create_schedule(body:ScheduleInput,x_review_token:str|None=Header(default=None)):
    require_review_permission(x_review_token, "schedules.manage")
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
    require_review_permission(x_review_token, "schedules.manage")
    return {"items":schedule_store.list()}



@app.get("/api/schedules/outbox")
def schedule_outbox(x_review_token:str|None=Header(default=None)):
    require_review_permission(x_review_token, "schedules.manage")
    return schedule_store.outbox_status()


@app.put("/api/schedules/{schedule_id}/activation")
def activate_schedule(schedule_id:str,active:bool,
                      x_review_token:str|None=Header(default=None)):
    require_review_permission(x_review_token, "schedules.manage")
    result=schedule_store.set_active(schedule_id,active)
    if result is None:raise HTTPException(404,"Schedule not found")
    return result


@app.post("/api/trends/collect")
def collect_trends(body:TrendCollect,x_review_token:str|None=Header(default=None)):
    require_review_permission(x_review_token, "trends.collect")
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
    require_review_permission(x_review_token, "production.create")
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
        recommendation_link = recommendation_evaluation_store.link_production(
            trend_id, brand["slug"], submitted["job"]["id"],
            candidate_id=body.recommendation_candidate_id,
        )
        submitted["recommendation_evaluation_link"] = recommendation_link
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


def _trend_recommendation_payload(ranked, candidate_ids=None):
    candidate_ids = candidate_ids or {}
    for item in ranked:
        trend_id=(item.get("trend") or {}).get("id")
        for candidate in item.get("brand_candidates") or []:
            if trend_id and candidate.get("brand"):
                candidate["human_decision"]=recommendation_evaluation_store.latest_decision(
                    trend_id,candidate["brand"]
                )
                candidate["evaluation_candidate_id"] = candidate_ids.get(
                    (str(trend_id), str(candidate["brand"]))
                )
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
    require_review_permission(x_review_token, "recommendations.manage")
    ranked=_build_trend_recommendations(region,limit)
    exposure=recommendation_evaluation_store.record_run(region,ranked)
    candidate_ids = {
        (item["trend_id"], item["brand_slug"]): item["candidate_id"]
        for item in exposure.get("candidate_ids", [])
    }
    return {
        **_trend_recommendation_payload(ranked, candidate_ids),
        "evaluation_run_id":exposure["run_id"],
        "evaluation_candidates_recorded":exposure["recorded_candidates"],
        "evaluation_snapshot_deduplicated":exposure.get("deduplicated",False),
    }

@app.get("/api/recommendations/evaluation")
def recommendation_evaluation(x_review_token:str|None=Header(default=None)):
    """Report chronological holdout diagnostics for selected recommendation outcomes."""
    require_review_access(x_review_token)
    return recommendation_evaluation_store.evaluate(performance_analyzer.analyze())

@app.post("/api/recommendations/evaluation/snapshots")
def capture_recommendation_evaluation_snapshot(x_review_token:str|None=Header(default=None)):
    """Capture an immutable evaluation record on explicit operator request."""
    require_review_permission(x_review_token, "recommendations.manage")
    result=recommendation_evaluation_store.evaluate(performance_analyzer.analyze())
    snapshot=recommendation_evaluation_store.record_evaluation_snapshot(result)
    return {
        **snapshot,
        "status": result.get("status"),
        "selected_production_count": result.get("selected_production_count",0),
        "measured_outcome_count": result.get("measured_outcome_count",0),
        "holdout_run_count": result.get("holdout_run_count",0),
        "holdout_score_views_spearman": result.get("holdout_score_views_spearman"),
        "ranking_score_adjustment_enabled": False,
    }

@app.get("/api/recommendations/evaluation/snapshots")
def list_recommendation_evaluation_snapshots(
    limit:int=20,x_review_token:str|None=Header(default=None)
):
    require_review_access(x_review_token)
    return recommendation_evaluation_store.list_evaluation_snapshots(limit)


@app.post("/api/recommendations/exposures/rendered")
def record_recommendation_rendered_exposures(
    body:RecommendationRenderedExposureBatch,
    x_review_token:str|None=Header(default=None)
):
    require_review_access(x_review_token)
    try:
        result=recommendation_evaluation_store.record_rendered_exposures(
            body.run_id,[item.model_dump() for item in body.exposures]
        )
    except ValueError as e:
        raise HTTPException(422,str(e))
    if result is None:
        raise HTTPException(404,"Recommendation run not found")
    return result


@app.get("/api/recommendations/exposures/{run_id}/report")
def recommendation_rendered_exposure_report(
    run_id:str,x_review_token:str|None=Header(default=None)
):
    require_review_access(x_review_token)
    result=recommendation_evaluation_store.rendered_exposure_report(
        run_id,performance_analyzer.analyze()
    )
    if result is None:
        raise HTTPException(404,"Recommendation run not found")
    return result


@app.get("/api/recommendations/experiments/integrity")
def recommendation_experiment_integrity_report(
    x_review_token:str|None=Header(default=None)
):
    require_review_access(x_review_token)
    return recommendation_evaluation_store.experiment_integrity_report()


@app.post("/api/recommendations/experiments")
def create_recommendation_experiment(
    body:RecommendationExperimentCreate,
    x_review_token:str|None=Header(default=None)
):
    authenticated_operator = require_review_permission(x_review_token, "recommendations.manage")
    try:
        return recommendation_evaluation_store.create_experiment(
            body.name,authenticated_operator or body.operator_id,body.control_label,body.treatment_label,
            body.treatment_allocation_basis_points
        )
    except ValueError as e:
        raise HTTPException(422,str(e))


@app.get("/api/recommendations/experiments")
def list_recommendation_experiments(
    limit:int=20,x_review_token:str|None=Header(default=None)
):
    require_review_access(x_review_token)
    return recommendation_evaluation_store.list_experiments(limit)


@app.post("/api/recommendations/experiments/{experiment_id}/shadow-assignment")
def assign_recommendation_experiment_shadow(
    experiment_id:str,body:RecommendationExperimentAssignment,
    x_review_token:str|None=Header(default=None)
):
    require_review_permission(x_review_token, "recommendations.manage")
    try:
        result=recommendation_evaluation_store.assign_shadow(
            experiment_id,body.participant_key
        )
    except ValueError as e:
        raise HTTPException(422,str(e))
    if result is None:
        raise HTTPException(404,"Recommendation experiment not found")
    return result


@app.get("/api/recommendations/experiments/{experiment_id}/report")
def recommendation_experiment_report(
    experiment_id:str,x_review_token:str|None=Header(default=None)
):
    require_review_access(x_review_token)
    result=recommendation_evaluation_store.experiment_report(experiment_id)
    if result is None:
        raise HTTPException(404,"Recommendation experiment not found")
    return result


@app.post("/api/recommendations/feedback/skip")
def skip_recommendation_feedback(
    body:RecommendationSkipFeedback,
    x_review_token:str|None=Header(default=None)
):
    authenticated_operator = require_review_permission(x_review_token, "recommendations.manage")
    try:
        result=recommendation_evaluation_store.record_skip(
            body.trend_id, body.brand_slug, authenticated_operator or body.reviewer_id, body.reason,
            candidate_id=body.recommendation_candidate_id,
        )
    except ValueError as e:
        raise HTTPException(422,str(e))
    if not result.get("recorded"):
        raise HTTPException(409,result.get("reason","Recommendation exposure not found"))
    return result


@app.get("/api/opportunities")
def list_opportunities(limit:int=50,x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    return {"opportunities":opportunity_store.list(limit)}

@app.get("/api/publishing/dashboard")
def publishing_dashboard(
    limit:int=100, x_review_token:str|None=Header(default=None)
):
    """Read-only cross-platform publication state with platform-specific evidence."""
    require_review_access(x_review_token)
    if limit < 1 or limit > 200:
        raise HTTPException(422, "limit must be between 1 and 200")
    youtube = youtube_upload_store.list_recent(limit)
    tiktok = tiktok_publish_store.list_recent(limit)

    def summarize(records):
        counts = {}
        for record in records:
            status = record.get("status") or "unknown"
            counts[status] = counts.get(status, 0) + 1
        return counts

    def present(record, platform):
        events = record.get("events") or []
        latest = events[-1] if events else None
        if platform == "youtube":
            needs_attention = bool(record.get("reconciliation_required")) or record.get("status") in (
                "reconciliation_required", "late_success_review_required"
            )
            remote_id = record.get("video_id")
            error = record.get("last_error") or record.get("error")
        else:
            needs_attention = record.get("status") == "reconciliation_required"
            remote_id = record.get("video_id") or record.get("publish_id")
            error = record.get("error") or record.get("fail_reason")
        return {
            "platform": platform,
            "job_id": record.get("job_id"),
            "status": record.get("status") or "unknown",
            "attempt_id": record.get("attempt_id"),
            "remote_id": remote_id,
            "privacy_level": record.get("privacy_level") if platform == "tiktok" else "private",
            "updated_at": record.get("updated_at"),
            "last_attempt_at": record.get("last_attempt_at"),
            "last_success_at": record.get("last_success_at"),
            "error": error,
            "fail_reason": record.get("fail_reason"),
            "reconciliation_required": needs_attention,
            "latest_event": latest,
            "events": events,
        }

    items = [present(item, "youtube") for item in youtube]
    items.extend(present(item, "tiktok") for item in tiktok)
    items.sort(key=lambda item: (item.get("updated_at") or "", item["platform"], item["job_id"] or ""), reverse=True)
    attention = sum(1 for item in items if item["reconciliation_required"] or item["error"])
    return {
        "items": items,
        "count": len(items),
        "platforms": {
            "youtube": {"count": len(youtube), "status_counts": summarize(youtube)},
            "tiktok": {"count": len(tiktok), "status_counts": summarize(tiktok),
                       "privacy_mode": "SELF_ONLY"},
        },
        "summary": {
            "reconciliation_required": sum(1 for item in items if item["reconciliation_required"]),
            "errors_present": sum(1 for item in items if item["error"]),
            "attention_required": attention,
        },
        "read_only": True,
        "actions_taken": [],
        "limitations": [
            "Platform states are shown independently; no cross-platform success state is inferred.",
            "A stored remote identifier or operator attestation is not independent proof of public visibility.",
            "Refreshing remote status and resolving uncertain outcomes require separate explicit operator actions.",
            "TikTok publication remains restricted to SELF_ONLY while the app is unaudited.",
        ],
    }


@app.get("/api/health")
def health(): return {"status":"ok","service":"nexus-studio-pro"}
@app.get("/api/ops/health")
def operational_health(x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    return queue.operational_health()

@app.get("/api/ops/recovery-plan")
def operational_recovery_plan(x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    health = queue.operational_health()
    checks = [
        {"id":"provider_outcomes","label":"외부 AI·게시 공급자의 이전 작업 결과와 중복 실행 여부 확인","operator_required":True},
        {"id":"artifacts_and_billing","label":"생성 파일의 존재·무결성과 과금 내역 확인","operator_required":True},
        {"id":"approval_and_policy","label":"최신 사람 승인 및 플랫폼 정책 증거 확인","operator_required":True},
        {"id":"worker_state","label":"Worker 프로세스·로그·heartbeat 상태 확인","operator_required":True},
    ]
    return {
        "status":"blocked" if health["blockers"] else ("review_required" if health["queue"]["paused"] else "not_paused"),
        "queue_paused":health["queue"]["paused"],
        "health":health,
        "automatic_checks":{"no_expired_leases":health["leases"]["expired_running"]==0,
                            "complete_lease_ownership":health["leases"]["running_missing_ownership"]==0},
        "operator_checks":checks,
        "resume_allowed":bool(health["queue"]["paused"] and not health["blockers"]),
        "resume_requires_explicit_operator_confirmation":True,
        "actions_taken":[],
    }
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
    authenticated_operator = require_review_permission(x_review_token, "queue.control")
    operator_id=(authenticated_operator or body.operator_id).strip()
    note=body.note.strip()
    if not operator_id or not note:
        raise HTTPException(422,"operator_id and note must not be blank")
    control=queue.pause(note,actor=operator_id)
    return {"control":control,"events":queue.worker_control_events(30)}

@app.post("/api/queue/resume")
def resume_queue(body:QueueControlAction,x_review_token:str|None=Header(default=None)):
    authenticated_operator = require_review_permission(x_review_token, "queue.control")
    operator_id=(authenticated_operator or body.operator_id).strip()
    if not operator_id or not body.note.strip():
        raise HTTPException(422,"operator_id and note must not be blank")
    if not body.recovery_confirmed:
        raise HTTPException(422,"Explicit recovery checklist confirmation is required")
    health=queue.operational_health()
    if health["blockers"]:
        raise HTTPException(409,{"message":"Queue recovery is blocked by unresolved operational safety signals","blockers":health["blockers"]})
    try:
        control=queue.resume(actor=operator_id,note=body.note.strip())
        return {"control":control,"events":queue.worker_control_events(30)}
    except ValueError as e:
        raise HTTPException(409,str(e))

@app.post("/api/jobs",status_code=201)
def enqueue(body:Enqueue,x_review_token:str|None=Header(default=None)):
    require_review_permission(x_review_token, "queue.enqueue")
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
    require_review_permission(x_review_token, "queue.control")
    return queue.recover()
@app.get("/api/workers")
def workers(x_review_token:str|None=Header(default=None)):
    require_review_access(x_review_token)
    return {"workers":queue.workers()}
@app.get("/api/jobs/{jid}/failure-analysis")
def get_job_failure_analysis(jid:str,x_review_token:str|None=Header(default=None)):
    """Read-only classification of the most recent persisted job failure."""
    require_review_access(x_review_token)
    try:
        job=queue.get(jid)
        events=queue.events(jid)
    except JobNotFound:
        raise HTTPException(404,"Job not found")
    failure_events=[event for event in events if event.get("event_type") in
                    ("failed","lease_expired","lease_recovered","worker_pause")]
    if not failure_events:
        return {"job_id":jid,"job_status":job["status"],"latest_failure":None,
                "read_only":True,"actions_taken":[]}
    event=failure_events[-1]
    details=event.get("details") or {}
    code=details.get("error_code") or job.get("error_code") or event.get("event_type")
    message=job.get("error_message") or details.get("error_message") or details.get("reason") or ""
    analysis=classify_failure(code,message,job.get("job_type"),job.get("status"),
                              job.get("attempt"),job.get("max_attempts"),details.get("retryable"))
    return {"job_id":jid,"job_status":job["status"],"failure_event":{
                "event_type":event.get("event_type"),"created_at":event.get("created_at"),
                "from_status":event.get("from_status"),"to_status":event.get("to_status")},
            "latest_failure":analysis,"read_only":True,"actions_taken":[]}
@app.get("/api/analytics/operations-economics")
def get_operations_economics(
    limit:int=500, x_review_token:str|None=Header(default=None),
):
    """Read-only bounded production quality, publishing and recorded-financial analytics."""
    require_review_access(x_review_token)
    if limit < 1 or limit > 500:
        raise HTTPException(422,"limit must be between 1 and 500")
    try:
        return build_operational_economics(queue.db_path, limit=limit)
    except sqlite3.OperationalError as exc:
        logging.exception("Operational economics analytics schema unavailable")
        raise HTTPException(503,"Operational analytics are not available for this database schema") from exc


@app.get("/api/performance/pipeline")
def get_pipeline_performance(
    limit:int=100, min_samples:int=5,
    x_review_token:str|None=Header(default=None),
):
    """Return bounded cohort statistics from durable queue event timestamps."""
    require_review_access(x_review_token)
    if min_samples < 1 or min_samples > 100:
        raise HTTPException(422,"min_samples must be between 1 and 100")
    page=queue.list_jobs(job_type="short_video_production",limit=min(100,max(1,limit)))
    jobs=page["items"]
    event_map={job["id"]:queue.events(job["id"]) for job in jobs}
    result=build_pipeline_performance(jobs,event_map,min_samples=min_samples)
    result["cohort_total_jobs"]=page["total"]
    result["cohort_limit"]=min(100,max(1,limit))
    return result


@app.get("/api/jobs/{jid}/stage-performance")
def get_job_stage_performance(jid:str,x_review_token:str|None=Header(default=None)):
    """Return read-only observed queue-state dwell times for one job."""
    require_review_access(x_review_token)
    try:
        job=queue.get(jid)
    except JobNotFound:
        raise HTTPException(404,"Job not found")
    events=queue.events(jid)
    return build_stage_performance(job,events)


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
