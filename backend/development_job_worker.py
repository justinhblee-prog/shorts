"""Small worker runtime for dependency-aware engineering jobs.

The executor is injected by the trusted runner; this module never executes
arbitrary commands from a job record.
"""
import os
import threading
import time

from development_jobs import DevelopmentJobConflict
from development_security import redact_sensitive_text


class NonRetryableDevelopmentJobError(Exception):
    """An execution failure that must be quarantined rather than retried."""


class DevelopmentJobWorker:
    def __init__(self, store, worker_id, executor, poll_seconds=5, require_execution_verifier=False):
        if not callable(executor):
            raise ValueError("executor must be callable")
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise ValueError("worker_id is required")
        if isinstance(poll_seconds, bool) or not isinstance(poll_seconds, (int, float)) or poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        self.store = store
        self.worker_id = worker_id.strip()
        self.hostname = os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME")
        self.executor = executor
        self.poll_seconds = poll_seconds
        self.require_execution_verifier = bool(require_execution_verifier)
        self._stop = threading.Event()

    def stop(self):
        """Request graceful shutdown after the current job."""
        self._stop.set()

    def run_once(self):
        """Claim and execute at most one eligible job; return its resulting status."""
        self.store.touch_worker(self.worker_id, hostname=self.hostname)
        job = self.store.claim_ready(self.worker_id)
        if job is None:
            return None
        self.store.touch_worker(self.worker_id, hostname=self.hostname, current_job_id=job["id"])

        lease_lost = threading.Event()
        heartbeat_stop = threading.Event()
        interval = max(1, min(30, self.store.lease_seconds // 3))

        def cancel_for_lease_loss():
            lease_lost.set()
            cancel = getattr(self.executor, "cancel", None)
            if callable(cancel):
                try:
                    cancel()
                except Exception:
                    pass

        def keep_lease_alive():
            while not heartbeat_stop.wait(interval):
                try:
                    self.store.heartbeat(job["id"], self.worker_id, job["lease_token"])
                    if not self.store.heartbeat_worker(self.worker_id, job["id"]):
                        return
                except DevelopmentJobConflict:
                    # A rejected fencing token is definitive lease loss.
                    cancel_for_lease_loss()
                    return
                except Exception:
                    # A heartbeat persistence/transport failure makes ownership uncertain.
                    cancel_for_lease_loss()
                    return

        heartbeat = threading.Thread(target=keep_lease_alive, name="dev-job-heartbeat", daemon=True)
        heartbeat.start()
        try:
            result = self.executor(job)
            if lease_lost.is_set():
                return "lease_lost"
            if not isinstance(result, dict):
                raise ValueError("executor must return an evidence dictionary")
            claimed_files = result.get("changed_files")
            verifier = getattr(self.executor, "verify_execution_evidence", None)
            if self.require_execution_verifier and not callable(verifier):
                raise NonRetryableDevelopmentJobError(
                    "trusted executor does not provide worktree change verification"
                )
            verified_files = claimed_files
            if callable(verifier):
                verified_files = verifier(job, result)
                if not isinstance(verified_files, list) or not verified_files or not all(
                    isinstance(path, str) and path.strip() for path in verified_files
                ):
                    raise NonRetryableDevelopmentJobError(
                        "worktree verification did not return meaningful changed files"
                    )
                normalize = lambda values: sorted(
                    {path.replace("\\\\", "/") for path in values}
                )
                if not isinstance(claimed_files, list) or normalize(verified_files) != normalize(claimed_files):
                    raise NonRetryableDevelopmentJobError(
                        "executor changed_files do not match the current Git worktree"
                    )
            result_summary = result.get("result_summary", "")
            if not isinstance(result_summary, str):
                result_summary = str(result_summary)
            safe_summary = redact_sensitive_text(result_summary, limit=4000)
            validation_ref = result.get("validation_ref")
            if isinstance(validation_ref, str):
                validation_ref = redact_sensitive_text(validation_ref, limit=1000)
            completed = self.store.mark_review_pending(
                job["id"], self.worker_id, job["lease_token"],
                verified_files, result.get("tests_passed"),
                validation_ref, safe_summary,
            )
            return completed["status"]
        except DevelopmentJobConflict:
            # The durable evidence gate rejected this worker's fence. Treat it
            # as lease loss rather than failing the entire runner invocation.
            lease_lost.set()
            return "lease_lost"
        except NonRetryableDevelopmentJobError as error:
            if lease_lost.is_set():
                return "lease_lost"
            failed = self.store.fail(
                job["id"], self.worker_id, job["lease_token"],
                redact_sensitive_text(f"{type(error).__name__}: {error}", limit=4000), retryable=False,
            )
            return failed["status"]
        except Exception as error:
            if lease_lost.is_set():
                return "lease_lost"
            failed = self.store.fail(
                job["id"], self.worker_id, job["lease_token"],
                redact_sensitive_text(f"{type(error).__name__}: {error}", limit=4000), retryable=True,
            )
            return failed["status"]
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=interval + 1)
            try:
                self.store.touch_worker(self.worker_id, hostname=self.hostname, current_job_id=None)
            except Exception:
                pass

    def run_forever(self):
        """Poll for work, then return after one claimed job so the workspace can be recycled."""
        try:
            while not self._stop.is_set():
                status = self.run_once()
                if status is None:
                    self._stop.wait(self.poll_seconds)
                else:
                    break
        finally:
            self.store.stop_worker(self.worker_id)


    def run_until_idle(self, idle_seconds=60):
        """Process at most one claimed job per workspace, then leave the runner idle."""
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
                # Any attempted job can leave partial or validated changes in
                # the shared worktree. Never claim another job in this runner
                # cycle; the next workflow checkout owns workspace cleanup.
                break
        finally:
            self.store.stop_worker(self.worker_id)
        return {"processed": processed, "outcomes": outcomes, "summary": self.store.summary()}
