"""Long-running worker for short-video production jobs.

Run: python worker.py
The worker only claims short_video_production jobs; it does not consume other queue types.
"""
import os
import socket
import threading
import uuid

from production_pipeline import ProductionPipeline, ProductionStore, ProductionLeaseConflict, ProviderError
from queue_store import JobQueue, LeaseConflict


DB_PATH = os.getenv("NEXUS_DB_PATH", "data/nexus.sqlite3")
LEASE_SECONDS = max(30, int(os.getenv("NEXUS_LEASE_SECONDS", "300")))
WORKER_ID = os.getenv("NEXUS_WORKER_ID", "nexus-production-" + str(uuid.uuid4())[:8])
IDLE_SECONDS = max(1, int(os.getenv("NEXUS_IDLE_SECONDS", "3")))

queue = JobQueue(DB_PATH, LEASE_SECONDS)
store = ProductionStore(DB_PATH)
pipeline = ProductionPipeline(store)
stopping = threading.Event()


def heartbeat_loop(job_id, token, lost_lease, heartbeat_stop):
    interval = max(5, LEASE_SECONDS // 3)
    while not heartbeat_stop.wait(interval):
        try:
            queue.heartbeat(job_id, WORKER_ID, token)
        except LeaseConflict:
            lost_lease.set()
            return
        except Exception:
            # A transient DB error is retried on the next heartbeat interval.
            continue


def run_once():
    # Recover the cross-store crash window before claiming new work.
    store.reconcile_review_pending(queue)
    job = queue.claim(WORKER_ID, socket.gethostname(), job_type="short_video_production")
    if job is None:
        return False

    lost_lease = threading.Event()
    heartbeat_stop = threading.Event()
    heartbeat = threading.Thread(
        target=heartbeat_loop, args=(job["id"], job["lease_token"], lost_lease, heartbeat_stop),
        daemon=True)
    heartbeat.start()
    try:
        result = pipeline.execute(job["id"], job["payload"],\n                                    worker_id=WORKER_ID, lease_token=job["lease_token"])
        if lost_lease.is_set():
            raise LeaseConflict("Worker lease was lost while generating media")
        queue.finish(job["id"], WORKER_ID, job["lease_token"],
                     {"production_status": "review_pending",
                      "artifact_count": len(result["artifacts"])})
        store.stage(job["id"], "review_pending", "review_pending")
        print(f"review_pending job={job['id']}")
    except ProviderError as exc:
        try:
            queue.fail(job["id"], WORKER_ID, job["lease_token"],
                       "provider_" + exc.stage, str(exc), exc.retryable)
        except LeaseConflict:
            print(f"lease_lost job={job['id']}")
        print(f"provider_failure job={job['id']} stage={exc.stage} retryable={exc.retryable}")
    except LeaseConflict:
        print(f"lease_lost job={job['id']}")
    except Exception as exc:
        try:
            queue.fail(job["id"], WORKER_ID, job["lease_token"],
                       "worker_error", str(exc), False)
        except LeaseConflict:
            print(f"lease_lost job={job['id']}")
        print(f"worker_failure job={job['id']} error={type(exc).__name__}")
    finally:
        heartbeat_stop.set()
        heartbeat.join(timeout=5)
    return True


def main():
    print(f"worker_started id={WORKER_ID} lease_seconds={LEASE_SECONDS}")
    try:
        while not stopping.is_set():
            if not run_once():
                stopping.wait(IDLE_SECONDS)
    except KeyboardInterrupt:
        print("worker_stopping")


if __name__ == "__main__":
    main()
