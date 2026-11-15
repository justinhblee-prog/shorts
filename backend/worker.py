"""Long-running worker for short-video production jobs.

Run: python worker.py
The worker only claims short_video_production jobs; it does not consume other queue types.
"""
import os
import signal
import socket
import threading
import uuid

from production_pipeline import (ProductionPipeline, ProductionStore,
                                 ProductionLeaseConflict, ProviderError, PolicyBlocked)
from queue_store import JobQueue, LeaseConflict
from worker_runtime import heartbeat_interval, request_worker_shutdown


DB_PATH = os.getenv("NEXUS_DB_PATH", "data/nexus.sqlite3")
LEASE_SECONDS = max(30, int(os.getenv("NEXUS_LEASE_SECONDS", "300")))
WORKER_ID = os.getenv("NEXUS_WORKER_ID", "nexus-production-" + str(uuid.uuid4())[:8])
IDLE_SECONDS = max(1, int(os.getenv("NEXUS_IDLE_SECONDS", "3")))


HEARTBEAT_SECONDS = heartbeat_interval(
    LEASE_SECONDS, os.getenv("NEXUS_HEARTBEAT_SECONDS", "10")
)

queue = JobQueue(DB_PATH, LEASE_SECONDS)
store = ProductionStore(DB_PATH)
pipeline = ProductionPipeline(store)
stopping = threading.Event()
active_job_id = None
active_lost_lease_event = None


def handle_shutdown_signal(signum, frame):
    request_worker_shutdown(
        queue, stopping, active_job_id, active_lost_lease_event, signum
    )


def heartbeat_loop(job_id, token, lost_lease, heartbeat_stop, interval=None):
    interval = HEARTBEAT_SECONDS if interval is None else max(0, interval)
    while not heartbeat_stop.wait(interval):
        try:
            queue.heartbeat(job_id, WORKER_ID, token)
        except LeaseConflict as exc:
            lost_lease.set()
            stopping.set()
            try:
                queue.pause(f"heartbeat lease conflict: {exc}", job_id)
            except Exception:
                pass
            return
        except Exception as exc:
            # A heartbeat DB failure makes lease ownership uncertain. Persist a
            # global pause when possible; never silently continue to another job.
            lost_lease.set()
            stopping.set()
            try:
                queue.pause(f"heartbeat failure: {type(exc).__name__}: {exc}", job_id)
            except Exception:
                pass
            return


def run_once():
    if queue.is_paused():
        return False
    # Recovery failures escape: no claim may occur while state is uncertain.
    store.reconcile_missing_runs(queue)
    store.reconcile_terminal_jobs(queue)
    store.reconcile_review_pending(queue)
    job = queue.claim(WORKER_ID, socket.gethostname(), job_type="short_video_production")
    if job is None:
        return False
    lost_lease = threading.Event()
    heartbeat_stop = threading.Event()
    global active_job_id, active_lost_lease_event
    active_job_id = job["id"]
    active_lost_lease_event = lost_lease
    heartbeat = threading.Thread(
        target=heartbeat_loop, args=(job["id"], job["lease_token"], lost_lease, heartbeat_stop),
        daemon=True)
    try:
        heartbeat.start()
        # Close the enqueue/worker race: repair a missing production row after claim.
        # Start the heartbeat first so SIGTERM or lease loss during reconciliation
        # is still fenced before any external provider request begins.
        store.reconcile_missing_runs(queue, job_ids=[job["id"]])
        if lost_lease.is_set():
            raise LeaseConflict("Worker lease was lost before provider execution")
        result = pipeline.execute(job["id"], job["payload"],
                                  worker_id=WORKER_ID, lease_token=job["lease_token"],
                                  stop_event=lost_lease)
        if lost_lease.is_set():
            raise LeaseConflict("Worker lease was lost while generating media")
        queue.finish(job["id"], WORKER_ID, job["lease_token"],
                     {"production_status": "review_pending",
                      "artifact_count": len(result["artifacts"])})
        store.reconcile_review_pending(queue)
        print(f"review_pending job={job['id']}")
    except KeyboardInterrupt:
        stopping.set()
        reason = "Worker interrupted during provider execution; outcome may be ambiguous"
        try:
            # Pause first so the current running job and production record are
            # terminalized atomically before its lease can be released.
            queue.pause(reason, job["id"])
        except Exception:
            try:
                queue.fail(job["id"], WORKER_ID, job["lease_token"],
                           "worker_interrupted_ambiguous", reason, False)
            except LeaseConflict:
                pass
        raise
    except PolicyBlocked as exc:
        try:
            queue.fail(job["id"], WORKER_ID, job["lease_token"],
                       "policy_blocked", str(exc), False)
        except LeaseConflict:
            print(f"lease_lost job={job['id']}")
        print(f"policy_blocked job={job['id']} stage={exc.stage}")
    except ProviderError as exc:
        stopping.set()
        failure_recorded=False
        try:
            queue.fail(job["id"], WORKER_ID, job["lease_token"],
                       "provider_" + exc.stage, str(exc), False)
            failure_recorded=True
        except LeaseConflict:
            print(f"lease_lost job={job['id']}")
        if not failure_recorded:
            try:
                queue.pause(f"provider failure at {exc.stage}: {exc}", job["id"])
            except Exception:
                pass
        print(f"provider_failure job={job['id']} stage={exc.stage} retryable={exc.retryable}")
    except (LeaseConflict, ProductionLeaseConflict) as exc:
        stopping.set()
        try:
            queue.fail(job["id"], WORKER_ID, job["lease_token"],
                       "worker_interrupted_ambiguous", str(exc), False)
        except LeaseConflict:
            pass
        try:
            queue.pause(f"lease/production conflict: {exc}", job["id"])
        except Exception:
            pass
        print(f"lease_lost job={job['id']}; worker_paused")
    except Exception as exc:
        stopping.set()
        try:
            queue.fail(job["id"], WORKER_ID, job["lease_token"],
                       "worker_error", str(exc), False)
        except LeaseConflict:
            print(f"lease_lost job={job['id']}")
        try:
            queue.pause(f"fatal worker error: {type(exc).__name__}: {exc}", job["id"])
        except Exception:
            pass
        print(f"worker_failure job={job['id']} error={type(exc).__name__}")
    finally:
        heartbeat_stop.set()
        if heartbeat.is_alive():
            heartbeat.join()
        active_job_id = None
        active_lost_lease_event = None
    return True


def main():
    signal.signal(signal.SIGTERM, handle_shutdown_signal)
    print(f"worker_started id={WORKER_ID} lease_seconds={LEASE_SECONDS} heartbeat_seconds={HEARTBEAT_SECONDS}")
    try:
        while True:
            # Keep idle and paused workers visible; job heartbeats alone only
            # refresh registry timestamps while a production lease is running.
            queue.register_worker(WORKER_ID, socket.gethostname())
            if stopping.is_set():
                return
            if queue.is_paused():
                stopping.wait(IDLE_SECONDS)
                continue
            if not run_once():
                stopping.wait(IDLE_SECONDS)
    except KeyboardInterrupt:
        print("worker_stopping")
    except Exception as exc:
        stopping.set()
        try:
            queue.pause(f"fatal worker startup/reconciliation error: {type(exc).__name__}: {exc}")
        except Exception:
            pass
        print(f"worker_fatal error={type(exc).__name__}; worker_paused")
        raise


if __name__ == "__main__":
    main()
