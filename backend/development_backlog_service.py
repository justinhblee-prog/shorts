"""Coordinator joining read-only GitHub intake to the development worker.

The executor is deliberately injected by a trusted runner; issue text is never
executed as shell commands. Each cycle syncs the bounded GitHub snapshot first,
then lets the fenced worker process eligible jobs.
"""
from __future__ import annotations

import threading
from typing import Any

from development_job_worker import DevelopmentJobWorker
from development_github_intake import sync_github_backlog


class DevelopmentBacklogService:
    def __init__(
        self,
        store: Any,
        github_client: Any,
        owner: str,
        repository: str,
        executor: Any,
        worker_id: str,
        approved_scopes: dict[str, list[str]] | None = None,
        poll_seconds: float = 30,
        idle_seconds: float = 2,
    ):
        if not callable(executor):
            raise ValueError("trusted executor must be callable")
        if not isinstance(poll_seconds, (int, float)) or isinstance(poll_seconds, bool) or poll_seconds < 1:
            raise ValueError("poll_seconds must be at least one second")
        if not isinstance(idle_seconds, (int, float)) or isinstance(idle_seconds, bool) or idle_seconds < 1:
            raise ValueError("idle_seconds must be at least one second")
        self.store = store
        self.github_client = github_client
        self.owner = owner
        self.repository = repository
        self.executor = executor
        self.worker_id = worker_id
        self.approved_scopes = approved_scopes or {}
        self.poll_seconds = poll_seconds
        self.idle_seconds = idle_seconds
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run_cycle(self) -> dict[str, Any]:
        intake = sync_github_backlog(
            self.store, self.github_client, self.owner, self.repository,
            approved_scopes=self.approved_scopes,
        )
        worker = DevelopmentJobWorker(
            self.store, self.worker_id, self.executor, poll_seconds=self.poll_seconds,
        )
        execution = worker.run_until_idle(idle_seconds=self.idle_seconds)
        return {"intake": intake, "execution": execution}

    def run_forever(self):
        """Run sync/worker cycles until stop() is requested."""
        cycles = 0
        last_result = None
        while not self._stop_event.is_set():
            last_result = self.run_cycle()
            cycles += 1
            # A claimed attempt may leave unvalidated changes in the shared
            # checkout. Never start another cycle against that same worktree.
            execution = last_result.get("execution", {}) if isinstance(last_result, dict) else {}
            if execution.get("processed", 0) > 0:
                break
            if not self._stop_event.is_set():
                self._stop_event.wait(self.poll_seconds)
        return {"cycles": cycles, "last_result": last_result}
