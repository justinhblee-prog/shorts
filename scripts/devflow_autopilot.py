#!/usr/bin/env python3
"""One-command, bounded coding-agent -> validation -> Draft PR supervisor.

The agent is an external CLI configured by DEVFLOW_AGENT_COMMAND_JSON, e.g.
["codex", "exec", "--full-auto"]. No shell is used to launch it.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / ".devflow" / "tasks.json"
DEFAULT_BASE = "feat/ffmpeg-render-execution-guard-2026-11-20"


def run(argv: list[str], cwd: Path, *, timeout: int = 1800) -> str:
    result = subprocess.run(
        argv, cwd=str(cwd), text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, timeout=timeout, check=False,
        shell=False,
    )
    output = result.stdout or ""
    if result.returncode:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(argv[:5])}\n{output[-12000:]}"
        )
    return output.strip()


def git(cwd: Path, *args: str) -> str:
    return run(["git", *args], cwd)


def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def choose_task(data: dict, task_id: str | None) -> dict:
    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        raise RuntimeError("task manifest has no tasks array")
    candidates = [t for t in tasks if isinstance(t, dict)]
    if task_id:
        matches = [t for t in candidates if t.get("id") == task_id]
        if not matches:
            raise RuntimeError(f"task not found: {task_id}")
        task = matches[0]
        if task.get("status") not in ("ready", "in_progress"):
            raise RuntimeError(f"task is not runnable: {task_id} ({task.get('status')})")
    else:
        runnable = [t for t in candidates if t.get("status") in ("ready", "in_progress")]
        runnable.sort(key=lambda t: (int(t.get("priority", 9999)), str(t.get("id", ""))))
        if not runnable:
            raise RuntimeError("no ready/in-progress task; blocked tasks are not auto-started")
        task = runnable[0]
    by_id = {t.get("id"): t for t in candidates}
    for dependency in task.get("depends_on", []):
        dep = by_id.get(dependency)
        if not dep or dep.get("status") not in ("review_pending", "completed"):
            raise RuntimeError(f"dependency is not review-ready: {dependency}")
    return task


def agent_command() -> list[str]:
    raw = os.environ.get("DEVFLOW_AGENT_COMMAND_JSON", "")
    if not raw:
        raise RuntimeError(
            "DEVFLOW_AGENT_COMMAND_JSON is not configured. Set it to a JSON argv array, "
            "for example [\"codex\", \"exec\", \"--full-auto\"]."
        )
    value = json.loads(raw)
    if not isinstance(value, list) or not value or any(
        not isinstance(x, str) or not x for x in value
    ):
        raise RuntimeError("DEVFLOW_AGENT_COMMAND_JSON must be a non-empty JSON string array")
    executable = shutil.which(value[0])
    if not executable:
        raise RuntimeError(f"coding-agent executable not found on PATH: {value[0]}")
    value[0] = executable
    return value


def task_prompt(task: dict, attempt: int, previous_failure: str = "") -> str:
    return f"""You are implementing one task in the NEXUS STUDIO PRO repository.
Work only in the current Git worktree. Do not modify any other checkout or repository.

Task: {task['id']} — {task['title']}
Scope:
{json.dumps(task.get('scope', []), ensure_ascii=False, indent=2)}
Acceptance criteria:
{json.dumps(task.get('acceptance', []), ensure_ascii=False, indent=2)}
External gates:
{json.dumps(task.get('external_gates', []), ensure_ascii=False, indent=2)}

Instructions:
- Inspect existing code, interfaces, tests and docs before editing.
- Implement the highest-value incomplete acceptance criteria that can be completed locally.
- Add/update focused tests and documentation.
- Run relevant focused tests yourself; do not claim real provider/FFmpeg/production tests unless actually run.
- Do not use secrets, paid provider APIs, public uploads, YouTube publishing, deployment, merge, force-push, or destructive Git commands.
- Keep outputs review_pending; never mark external gates as passed without evidence.
- Do not modify .devflow/tasks.json; the supervisor owns task state.
- Finish with a concise list of changes, commands/tests run, and known blockers.

Attempt: {attempt}
{("Previous validation failure to repair:\\n" + previous_failure) if previous_failure else ""}
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", help="task id; default selects the highest-priority runnable task")
    parser.add_argument("--base", default=os.environ.get("DEVFLOW_BASE", DEFAULT_BASE))
    parser.add_argument("--max-repairs", type=int, default=2)
    parser.add_argument("--agent-timeout", type=int, default=3600)
    args = parser.parse_args()

    if not 0 <= args.max_repairs <= 3:
        raise RuntimeError("--max-repairs must be between 0 and 3")
    if not 60 <= args.agent_timeout <= 7200:
        raise RuntimeError("--agent-timeout must be between 60 and 7200 seconds")
    if git(ROOT, "status", "--porcelain"):
        raise RuntimeError("primary checkout is not clean; refusing to start unattended work")
    if not git(ROOT, "remote", "get-url", "origin"):
        raise RuntimeError("origin remote is not configured")

    data = load_manifest()
    task = choose_task(data, args.task)
    command = agent_command()
    task_id = str(task["id"])
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in task_id).strip("-")
    branch = f"autopilot/{slug}-{time.strftime('%Y%m%d-%H%M%S')}"
    worktree = ROOT.parent / f"{ROOT.name}-worktrees" / f"{slug}-autopilot"
    if worktree.exists():
        raise RuntimeError(f"worktree already exists; inspect or remove manually: {worktree}")
    worktree.parent.mkdir(parents=True, exist_ok=True)

    print(f"[devflow] task={task_id} base={args.base}", flush=True)
    run(["git", "worktree", "add", "-b", branch, str(worktree), args.base], ROOT)
    helper = worktree / "scripts" / "devflow.py"
    prompt_file = worktree.parent / f"{slug}-agent-prompt.md"
    last_failure = ""
    try:
        for attempt in range(1, args.max_repairs + 2):
            prompt_file.write_text(task_prompt(task, attempt, last_failure), encoding="utf-8")
            prompt = prompt_file.read_text(encoding="utf-8")
            print(f"[devflow] invoking coding agent (attempt {attempt})", flush=True)
            result = subprocess.run(
                command + [prompt], cwd=str(worktree), text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                timeout=args.agent_timeout, check=False, shell=False,
            )
            print((result.stdout or "")[-16000:], flush=True)
            if result.returncode:
                last_failure = f"coding agent exited with status {result.returncode}"
                continue
            try:
                validation = run(
                    [sys.executable, str(helper), "validate"],
                    worktree, timeout=2400,
                )
                print(validation, flush=True)
                break
            except (RuntimeError, subprocess.TimeoutExpired) as exc:
                last_failure = str(exc)
                print(f"[devflow] validation failed; asking agent to repair: {last_failure[-5000:]}", flush=True)
        else:
            raise RuntimeError("agent/validation repair budget exhausted; worktree retained for inspection")

        # Mark the task as review-pending in the same commit only after validation passes.
        manifest_path = worktree / ".devflow" / "tasks.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entry = next(t for t in manifest["tasks"] if t.get("id") == task_id)
        entry["status"] = "review_pending"
        entry["automation"] = {
            "branch": branch,
            "base": args.base,
            "validated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "validation": "scripts/devflow.py validate passed",
            "external_gates_remain_open": True,
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        run([sys.executable, str(helper), "finish",
             "--message", f"BUILD: Implement {task_id} via autonomous devflow",
             "--title", f"BUILD: {task['title']}",
             "--base", args.base], worktree, timeout=3600)
        print(f"[devflow] Draft PR workflow finished for {task_id}; branch={branch}", flush=True)
        return 0
    finally:
        try:
            prompt_file.unlink(missing_ok=True)
        except OSError:
            pass


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"devflow-autopilot: {exc}", file=sys.stderr)
        raise SystemExit(2)
