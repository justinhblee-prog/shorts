#!/usr/bin/env python3
"""Dispatch independent manifest tasks to isolated devflow worktrees in parallel."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / ".devflow" / "tasks.json"
SUPERVISOR = ROOT / "scripts" / "devflow_autopilot.py"


def select_parallel_tasks(data: dict, limit: int) -> list[dict]:
    policy_limit = int(data.get("policy", {}).get("max_parallel_worktrees", 1))
    if limit < 1 or limit > min(policy_limit, 3):
        raise RuntimeError(f"parallel limit must be between 1 and {min(policy_limit, 3)}")
    tasks = [task for task in data.get("tasks", []) if isinstance(task, dict)]
    by_id = {task.get("id"): task for task in tasks}
    candidates = []
    for task in tasks:
        if task.get("status") not in ("ready", "in_progress"):
            continue
        if any(
            not by_id.get(dep) or by_id[dep].get("status") != "completed"
            for dep in task.get("depends_on", [])
        ):
            continue
        candidates.append(task)
    candidates.sort(key=lambda task: (int(task.get("priority", 9999)), str(task.get("id", ""))))

    selected: list[dict] = []
    claimed_scopes: set[str] = set()
    for task in candidates:
        scopes = {str(scope).strip().casefold() for scope in task.get("scope", []) if str(scope).strip()}
        # Unknown scope is conservatively exclusive: it can only run alone.
        if not scopes and selected:
            continue
        if any(not item.get("scope") for item in selected):
            continue
        if scopes & claimed_scopes:
            continue
        selected.append(task)
        claimed_scopes.update(scopes)
        if len(selected) >= limit:
            break
    if not selected:
        raise RuntimeError("no dependency-ready tasks with non-conflicting declared scopes")
    return selected


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=str(ROOT), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=900, check=False, shell=False,
    )
    if result.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {(result.stdout or '')[-4000:]}")
    return (result.stdout or "").strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-parallel", type=int, default=None)
    parser.add_argument("--base", default=None)
    args = parser.parse_args()
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    default_limit = int(data.get("policy", {}).get("max_parallel_worktrees", 1))
    limit = args.max_parallel if args.max_parallel is not None else default_limit
    selected = select_parallel_tasks(data, limit)
    base = args.base or os.environ.get("DEVFLOW_BASE", "feat/ffmpeg-render-execution-guard-2026-11-20")
    if git("status", "--porcelain"):
        raise RuntimeError("primary checkout is not clean; refusing parallel execution")
    git("fetch", "origin", "--prune")
    try:
        base_sha = git("rev-parse", "--verify", f"refs/remotes/origin/{base}")
    except RuntimeError:
        base_sha = git("rev-parse", "--verify", base)
    child_env = os.environ.copy()
    child_env["DEVFLOW_RESOLVED_BASE_SHA"] = base_sha

    print("[devflow-parallel] selected: " + ", ".join(task["id"] for task in selected), flush=True)
    results = {}
    with ThreadPoolExecutor(max_workers=len(selected)) as pool:
        futures = {
            pool.submit(
                subprocess.run,
                [sys.executable, str(SUPERVISOR), "--task", str(task["id"]), "--base", base],
                cwd=str(ROOT), text=True, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, timeout=21600, check=False, shell=False,
                env=child_env,
            ): task for task in selected
        }
        for future in as_completed(futures):
            task = futures[future]
            try:
                result = future.result()
                results[task["id"]] = result.returncode
                print(f"\n===== {task['id']} exit={result.returncode} =====\n{result.stdout or ''}", flush=True)
            except Exception as exc:
                results[task["id"]] = 2
                print(f"\n===== {task['id']} failed: {exc} =====", flush=True)

    failed = [task_id for task_id, code in results.items() if code != 0]
    print("[devflow-parallel] " + ("failed: " + ", ".join(failed) if failed else "all dispatched flows completed"), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"devflow-parallel: {exc}", file=sys.stderr)
        raise SystemExit(2)
