import os
from typing import Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from queue_store import JobQueue, JobNotFound, LeaseConflict

queue=JobQueue(os.getenv("NEXUS_DB_PATH","data/nexus.sqlite3"),int(os.getenv("NEXUS_LEASE_SECONDS","90")))
app=FastAPI(title="NEXUS STUDIO PRO API",version="0.1.0")

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
