"""Long-running worker for short-video production jobs.

Run: python worker.py
The worker only claims short_video_production jobs; it does not consume other queue types.
"""
import json
import os
import signal
import socket
import threading
import uuid

from production_pipeline import (ProductionPipeline, ProductionStore,
                                 ProductionLeaseConflict, ProviderError, PolicyBlocked)
from queue_store import JobQueue, LeaseConflict
from worker_runtime import parse_worker_runtime_config, request_worker_shutdown


DB_PATH = os.getenv("NEXUS_DB_PATH", "data/nexus.sqlite3")
LEASE_SECONDS, IDLE_SECONDS, HEARTBEAT_SECONDS = parse_worker_runtime_config(
    os.getenv("NEXUS_LEASE_SECONDS", "300"),
    os.getenv("NEXUS_IDLE_SECONDS", "3"),
    os.getenv("NEXUS_HEARTBEAT_SECONDS", "10"),
)
WORKER_ID = os.getenv("NEXUS_WORKER_ID", "nexus-production-" + str(uuid.uuid4())[:8])

queue = JobQueue(DB_PATH, LEASE_SECONDS)
store = ProductionStore(DB_PATH)
pipeline = ProductionPipeline(store)
stopping = threading.Event()
active_job_id = None
active_lost_lease_event = None
WORKER_GENERATION_TOKEN = None


def handle_shutdown_signal(signum, frame):
    request_worker_shutdown(
        queue, stopping, active_job_id, active_lost_lease_event, signum,
        worker_id=WORKER_ID, generation_token=WORKER_GENERATION_TOKEN,
    )


def heartbeat_loop(job_id, token, lost_lease, heartbeat_stop, interval=None):
    interval = HEARTBEAT_SECONDS if interval is None else max(0, interval)
    while not heartbeat_stop.wait(interval):
        try:
            queue.heartbeat(job_id, WORKER_ID, token, WORKER_GENERATION_TOKEN)
        except LeaseConflict as exc:
            lost_lease.set()
            stopping.set()
            try:
                queue.pause(f"heartbeat lease conflict: {exc}", job_id, worker_id=WORKER_ID, generation_token=WORKER_GENERATION_TOKEN)
            except Exception:
                pass
            return
        except Exception as exc:
            # A heartbeat DB failure makes lease ownership uncertain. Persist a
            # global pause when possible; never silently continue to another job.
            lost_lease.set()
            stopping.set()
            try:
                queue.pause(f"heartbeat failure: {type(exc).__name__}: {exc}", job_id, worker_id=WORKER_ID, generation_token=WORKER_GENERATION_TOKEN)
            except Exception:
                pass
            return


def ensure_worker_registered():
    """Register one process incarnation for direct and main-loop invocations."""
    global WORKER_GENERATION_TOKEN
    if WORKER_GENERATION_TOKEN is None:
        registration = queue.register_worker(WORKER_ID, socket.gethostname())
        WORKER_GENERATION_TOKEN = registration["generation_token"]
    return WORKER_GENERATION_TOKEN


def run_once():
    ensure_worker_registered()
    if stopping.is_set() or queue.is_paused():
        return False
    # Recovery failures escape: no claim may occur while state is uncertain.
    store.reconcile_missing_runs(
        queue, worker_id=WORKER_ID, generation_token=WORKER_GENERATION_TOKEN
    )
    integrity = store.reconcile_status_integrity(
        queue, worker_id=WORKER_ID, generation_token=WORKER_GENERATION_TOKEN
    )
    orphan_report = store.integrity_report(queue, limit=200)
    if orphan_report.get("orphaned", 0):
        orphaned_items = [
            {
                "job_id": item["job_id"],
                "classification": item["classification"],
                "production_status": item["production_status"],
                "queue_status": item["queue_status"],
            }
            for item in orphan_report["items"]
            if item["record_kind"] in (
                "queue_without_production", "production_without_queue"
            )
        ]
        reason = (
            "Orphaned production lifecycle records require operator investigation: "
            + json.dumps(orphaned_items[:10], ensure_ascii=False)
        )
        queue.pause(reason, worker_id=WORKER_ID, generation_token=WORKER_GENERATION_TOKEN)
        print(
            f"production_orphan_integrity_blocked orphaned={orphan_report['orphaned']}; "
            "worker_paused"
        )
        return False
    if integrity["unresolved"]:
        reason = (
            "Production lifecycle state mismatch requires operator reconciliation: "
            + json.dumps(integrity["unresolved_jobs"][:10], ensure_ascii=False)
        )
        queue.pause(reason, worker_id=WORKER_ID, generation_token=WORKER_GENERATION_TOKEN)
        print(
            f"production_state_integrity_blocked unresolved={integrity['unresolved']} "
            f"repaired={integrity['repaired']}; worker_paused"
        )
        return False
    job = queue.claim(WORKER_ID, socket.gethostname(), job_type="short_video_production", generation_token=WORKER_GENERATION_TOKEN)
    if job is None:
        return False
    lost_lease = threading.Event()
    heartbeat_stop = threading.Event()
    global active_job_id, active_lost_lease_event
    # Publish the claimed job to the signal handler immediately. A SIGTERM can
    # arrive after claim() commits but before the heartbeat thread is started.
    active_job_id = job["id"]
    active_lost_lease_event = lost_lease
    heartbeat = threading.Thread(
        target=heartbeat_loop, args=(job["id"], job["lease_token"], lost_lease, heartbeat_stop),
        daemon=True)
    try:
        # If shutdown raced with claim(), do not start any provider work. The
        # signal handler may already have paused/terminalized this running job;
        # only persist a second pause if that first attempt did not stick.
        if stopping.is_set() or lost_lease.is_set():
            if not queue.is_paused():
                queue.pause(
                    "Worker shutdown requested immediately after job claim; "
                    "provider execution was not started",
                    job["id"], worker_id=WORKER_ID,
                    generation_token=WORKER_GENERATION_TOKEN,
                )
            return True
        heartbeat.start()
        # Close the enqueue/worker race: repair a missing production row after claim.
        # Start the heartbeat first so SIGTERM or lease loss during reconciliation
        # is still fenced before any external provider request begins.
        store.reconcile_missing_runs(
            queue, job_ids=[job["id"]], worker_id=WORKER_ID,
            generation_token=WORKER_GENERATION_TOKEN,
        )
        if stopping.is_set() or lost_lease.is_set():
            raise LeaseConflict("Worker shutdown or lease loss occurred before provider execution")
        result = pipeline.execute(job["id"], job["payload"],
                                  worker_id=WORKER_ID, lease_token=job["lease_token"],
                                  stop_event=lost_lease,
                                  generation_token=WORKER_GENERATION_TOKEN)
        if lost_lease.is_set():
            raise LeaseConflict("Worker lease was lost while generating media")
        queue.finish(job["id"], WORKER_ID, job["lease_token"],
                     {"production_status": "review_pending",
                      "artifact_count": len(result["artifacts"])},
                     generation_token=WORKER_GENERATION_TOKEN)
        store.reconcile_review_pending(
            queue, worker_id=WORKER_ID, generation_token=WORKER_GENERATION_TOKEN
        )
        print(f"review_pending job={job['id']}")
    except KeyboardInterrupt:
        stopping.set()
        reason = "Worker interrupted during provider execution; outcome may be ambiguous"
        try:
            # Pause first so the current running job and production record are
            # terminalized atomically before its lease can be released.
            queue.pause(reason, job["id"], worker_id=WORKER_ID, generation_token=WORKER_GENERATION_TOKEN)
        except Exception:
            try:
                queue.fail(job["id"], WORKER_ID, job["lease_token"],
                           "worker_interrupted_ambiguous", reason, False, generation_token=WORKER_GENERATION_TOKEN)
            except LeaseConflict:
                pass
        raise
    except PolicyBlocked as exc:
        try:
            queue.fail(job["id"], WORKER_ID, job["lease_token"],
                       "policy_blocked", str(exc), False, generation_token=WORKER_GENERATION_TOKEN)
        except LeaseConflict:
            print(f"lease_lost job={job['id']}")
        print(f"policy_blocked job={job['id']} stage={exc.stage}")
    except ProviderError as exc:
        stopping.set()
        try:
            queue.fail(job["id"], WORKER_ID, job["lease_token"],
                       "provider_" + exc.stage, str(exc), exc.retryable, generation_token=WORKER_GENERATION_TOKEN)
        except LeaseConflict:
            print(f"lease_lost job={job['id']}")
        try:
            queue.pause(f"provider failure at {exc.stage}: {exc}", job["id"], worker_id=WORKER_ID, generation_token=WORKER_GENERATION_TOKEN)
        except Exception:
            pass
        print(f"provider_failure job={job['id']} stage={exc.stage} retryable={exc.retryable}")
    except (LeaseConflict, ProductionLeaseConflict) as exc:
        stopping.set()
        try:
            queue.fail(job["id"], WORKER_ID, job["lease_token"],
                       "worker_interrupted_ambiguous", str(exc), False, generation_token=WORKER_GENERATION_TOKEN)
        except LeaseConflict:
            pass
        try:
            queue.pause(f"lease/production conflict: {exc}", job["id"], worker_id=WORKER_ID, generation_token=WORKER_GENERATION_TOKEN)
        except Exception:
            pass
        print(f"lease_lost job={job['id']}; worker_paused")
    except Exception as exc:
        stopping.set()
        try:
            queue.fail(job["id"], WORKER_ID, job["lease_token"],
                       "worker_error", str(exc), False, generation_token=WORKER_GENERATION_TOKEN)
        except LeaseConflict:
            print(f"lease_lost job={job['id']}")
        try:
            queue.pause(f"fatal worker error: {type(exc).__name__}: {exc}", job["id"], worker_id=WORKER_ID, generation_token=WORKER_GENERATION_TOKEN)
        except Exception:
            pass
        print(f"worker_failure job={job['id']} error={type(exc).__name__}")
    finally:
        heartbeat_stop.set()
        if heartbeat.is_alive():
            heartbeat.join(timeout=5)
        active_job_id = None
        active_lost_lease_event = None
    return True


def main():
    signal.signal(signal.SIGTERM, handle_shutdown_signal)
    print(f"worker_started id={WORKER_ID} lease_seconds={LEASE_SECONDS} heartbeat_seconds={HEARTBEAT_SECONDS}")
    generation_token = None
    try:
        # One registration per process incarnation. Re-registering in the
        # polling loop would rotate the fencing token and invalidate shutdown.
        registration = queue.register_worker(WORKER_ID, socket.gethostname())
        generation_token = registration["generation_token"]
        global WORKER_GENERATION_TOKEN
        WORKER_GENERATION_TOKEN = generation_token
        while True:
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
            queue.pause(f"fatal worker startup/reconciliation error: {type(exc).__name__}: {exc}", worker_id=WORKER_ID, generation_token=WORKER_GENERATION_TOKEN)
        except Exception:
            pass
        print(f"worker_fatal error={type(exc).__name__}; worker_paused")
        raise
    finally:
        try:
            if generation_token is not None:
                queue.mark_worker_offline(WORKER_ID, generation_token)
            WORKER_GENERATION_TOKEN = None
        except Exception as exc:
            # Preserve the original worker failure if shutdown bookkeeping fails.
            print(f"worker_offline_record_failed error={type(exc).__name__}")


if __name__ == "__main__":
    main()
