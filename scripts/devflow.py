#!/usr/bin/env python3
"""Git-CLI development flow helper. No merge, deploy, or secret mutation."""
from __future__ import annotations
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

def run(args: list[str], cwd: Path, *, capture: bool = False) -> str:
    result = subprocess.run(args, cwd=str(cwd), text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None, check=False)
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip() if capture else ""
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(args)} {detail}")
    return (result.stdout or "").strip() if capture else ""

def repo_root(start: Path) -> Path:
    return Path(run(["git", "rev-parse", "--show-toplevel"], start, capture=True)).resolve()

def slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:48]
    if not value:
        raise ValueError("task id must contain letters or digits")
    return value

def clean(path: Path) -> bool:
    return not run(["git", "status", "--porcelain"], path, capture=True)

def secret_candidates(path: Path) -> list[str]:
    patterns = (".env", ".env.*", "*.pem", "*.key", "id_rsa", "id_ed25519",
                "*.p12", "*.pfx", "credentials.json", "secrets.json")
    found = []
    for item in path.rglob("*"):
        if not item.is_file() or any(x in item.parts for x in (".git", ".venv", "node_modules")):
            continue
        relative = str(item.relative_to(path)).replace("\\", "/")
        if relative in (".env.example", ".env.sample"):
            continue
        if any(item.match(pattern) for pattern in patterns):
            found.append(relative)
    return found

def validate(root: Path) -> None:
    run(["git", "diff", "--check"], root)
    shell = shutil.which("bash") or shutil.which("sh")
    if not shell:
        raise RuntimeError("bash/sh not found; install Git for Windows or use the configured Linux runner")
    run([shell, "scripts/validate.sh"], root)

def cmd_start(args: argparse.Namespace) -> None:
    root = repo_root(Path.cwd())
    if not clean(root):
        raise RuntimeError("primary checkout is not clean; commit/stash changes first")
    task = slug(args.task)
    branch = args.branch or f"devflow/{task}"
    parent = root.parent / f"{root.name}-worktrees"
    target = parent / task
    if target.exists():
        raise RuntimeError(f"worktree path already exists: {target}")
    parent.mkdir(parents=True, exist_ok=True)
    run(["git", "worktree", "add", "-b", branch, str(target), args.base], root)
    print(json.dumps({"task": args.task, "branch": branch, "worktree": str(target),
                      "base": args.base}, ensure_ascii=False, indent=2))
    print("Run the coding agent inside this worktree only; leave the primary checkout untouched.")

def cmd_validate(args: argparse.Namespace) -> None:
    validate(repo_root(Path.cwd()))
    print("Validation passed: git diff --check + scripts/validate.sh")

def cmd_finish(args: argparse.Namespace) -> None:
    root = repo_root(Path.cwd())
    if clean(root):
        raise RuntimeError("no uncommitted changes; refusing empty completion")
    found = secret_candidates(root)
    if found:
        raise RuntimeError("possible secret files block staging: " + ", ".join(found[:20]))
    validate(root)
    run(["git", "add", "-A"], root)
    run(["git", "diff", "--cached", "--check"], root)
    if not run(["git", "diff", "--cached", "--name-only"], root, capture=True):
        raise RuntimeError("nothing staged")
    run(["git", "commit", "-m", args.message], root)
    branch = run(["git", "branch", "--show-current"], root, capture=True)
    if not branch or branch == "HEAD":
        raise RuntimeError("detached HEAD; refusing push")
    run(["git", "push", "--set-upstream", "origin", branch], root)
    gh = shutil.which("gh")
    if not gh:
        print("Pushed branch. GitHub CLI unavailable; open a Draft PR manually.")
        return
    title = args.title or args.message
    body = args.body or ("## Summary\n- Implements the task in an isolated Git worktree.\n\n"
        "## Validation\n- scripts/validate.sh passed locally before commit.\n\n"
        "## Safety\n- Draft review required. No merge or deployment performed.")
    run([gh, "pr", "create", "--draft", "--base", args.base,
         "--title", title, "--body", body], root)
    print("Pushed and opened a Draft PR. Merge/deploy remain human-controlled.")

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start", help="create isolated Git worktree and task branch")
    start.add_argument("task")
    start.add_argument("--base", default="feat/engineering-orchestrator-2026-11-20")
    start.add_argument("--branch")
    start.set_defaults(func=cmd_start)
    val = sub.add_parser("validate", help="run repository validation in this worktree")
    val.set_defaults(func=cmd_validate)
    finish = sub.add_parser("finish", help="validate, commit, push and open a Draft PR")
    finish.add_argument("--message", required=True)
    finish.add_argument("--title")
    finish.add_argument("--body")
    finish.add_argument("--base", default="feat/engineering-orchestrator-2026-11-20")
    finish.set_defaults(func=cmd_finish)
    args = parser.parse_args()
    try:
        args.func(args)
        return 0
    except (RuntimeError, ValueError) as exc:
        print(f"devflow: {exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
