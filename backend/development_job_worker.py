"""Small worker runtime for dependency-aware engineering jobs.

The executor is injected by the trusted runner; this module never executes
arbitrary commands from a job record.
"""
import threading
import time

from development_jobs import DevelopmentJobConflict


class NonRetryableDevelopmentJobError(Exception):
    """An execution failure that must be quarantined rather than retried."""


class DevelopmentJobWorker:
    def __init__(self, store, worker_id, executor, poll_seconds=5):
        if not callable(executor):
            raise ValueError("executor must be callable")
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise ValueError("worker_id is required")
        if isinstance(poll_seconds, bool) or not isinstance(poll_seconds, (int, float)) or poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        self.store = store
        self.worker_id = worker_id.strip()
        self.executor = executor
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()

    def stop(self):
        """Request graceful shutdown after the current job."""
        self._stop.set()

    def run_once(self):
        """Claim and execute at most one eligible job; return its resulting status."""
        self.store.touch_worker(self.worker_id)
        job = self.store.claim_ready(self.worker_id)
        if job is None:
            return None
        self.store.touch_worker(self.worker_id, current_job_id=job["id"])

        lease_lost = threading.Event()
        heartbeat_stop = threading.Event()
        interval = max(1, self.store.lease_seconds // 3)

        def keep_lease_alive():
            while not heartbeat_stop.wait(interval):
                try:
                    self.store.heartbeat(job["id"], self.worker_id, job["lease_token"])
                    self.store.touch_worker(self.worker_id, current_job_id=job["id"])
                except DevelopmentJobConflict:
                    lease_lost.set()
                    return
                except Exception:
                    # A transient heartbeat error is retried on the next interval.
                    continue

        heartbeat = threading.Thread(target=keep_lease_alive, name="dev-job-heartbeat", daemon=True)
        heartbeat.start()
        try:
            result = self.executor(job)
            if lease_lost.is_set():
                return "lease_lost"
            if not isinstance(result, dict):
                raise ValueError("executor must return an evidence dictionary")
            completed = self.store.complete(
                job["id"], self.worker_id, job["lease_token"],
                result.get("changed_files"), result.get("tests_passed"),
                result.get("validation_ref"), result.get("result_summary", ""),
            )
            return completed["status"]
        except DevelopmentJobConflict:
            if lease_lost.is_set():
                return "lease_lost"
            raise
        except NonRetryableDevelopmentJobError as error:
            if lease_lost.is_set():
                return "lease_lost"
            failed = self.store.fail(
                job["id"], self.worker_id, job["lease_token"],
                f"{type(error).__name__}: {error}", retryable=False,
            )
            return failed["status"]
        except Exception as error:
            if lease_lost.is_set():
                return "lease_lost"
            failed = self.store.fail(
                job["id"], self.worker_id, job["lease_token"],
                f"{type(error).__name__}: {error}", retryable=True,
            )
            return failed["status"]
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=interval + 1)
            try:
                self.store.touch_worker(self.worker_id, current_job_id=None)
            except Exception:
                pass

    def run_forever(self):
        """Poll until stop() is called; returns after the current job completes."""
        try:
            while not self._stop.is_set():
                status = self.run_once()
                if status is None:
                    self._stop.wait(self.poll_seconds)
        finally:
            self.store.stop_worker(self.worker_id)


    def run_until_idle(self, idle_seconds=60):
        """Process ready jobs until no work arrives for the configured idle window."""
        if isinstance(idle_seconds, bool) or not isinstance(idle_seconds, (int, float)) or idle_seconds < 1:
            raise ValueError("idle_seconds must be at least one second")
        last_activity = time.monotonic()
        processed = 0
        outcomes = {}
        try:
            while not self._stop.is_set() and time.monotonic() - last_activity < idle_seconds:
                status = self.run_once()
                if status is None:
                    remaining = idle_seconds - (time.monotonic() - last_activity)
                    self._stop.wait(min(self.poll_seconds, max(0.05, remaining)))
                    continue
                processed += 1
                outcomes[status] = outcomes.get(status, 0) + 1
                last_activity = time.monotonic()
        finally:
            self.store.stop_worker(self.worker_id)
        return {"processed": processed, "outcomes": outcomes, "summary": self.store.summary()}
