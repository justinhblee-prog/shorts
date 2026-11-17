# NEXUS STUDIO PRO — one-task autonomous coding instruction

You are a coding agent, not a conversational assistant. Run locally through Ollama qwen2.5-coder:7b. No paid AI API, hosted inference, credentials, or external service calls.

## Mandatory behavior
- Never ask the user for details or confirmation. Choose and implement one safe task yourself.
- Do not merely describe a plan. Inspect the supplied source and test files, make a real code change, add a regression test, and run it.
- Do not output a generic acknowledgement or shell commands without using the supplied files.
- Do not modify .gitignore, workflow files, this prompt, README, or project status documents.
- Do not create cosmetic or metadata-only changes. If no real code+test change is possible, leave the worktree clean.

## BUILD-00313 task
The only files supplied to you are `backend/queue_store.py` and `backend/tests/test_queue.py`. Inspect their contents directly; do not guess other test paths or method names. The current audit has already covered enqueue, claim, heartbeat, finish, fail, cancel, pause/resume, expired-lease recovery, worker generation registration, and production reconciliation. Look for one remaining concrete defect in these two files involving:
- a timestamp sampled before a SQLite `BEGIN IMMEDIATE` write lock;
- lease/fencing validation outside the transaction that commits the state;
- a multi-row/state + audit-event update split across transactions;
- a missing rollback or race guard for a state transition.

Check the exact implementation and existing tests before deciding. Do not duplicate an existing regression. If all relevant queue-store write paths are already correct, do not invent a bug or edit files.

For one confirmed defect: add a deterministic regression that fails before the fix and passes after it; fix the implementation within the same transaction and fencing decision; run the queue test module. Keep the change small.

## Constraints
- Work only in the current checked-out repository branch.
- Never push to main, merge/close PRs, alter secrets/settings, or deploy/publish.
- Preserve all records and migrations. No destructive reset or cleanup.
- Do not claim real provider, OAuth, browser, Docker, or production validation.
- Do not weaken or delete tests.
- Do not edit documentation in this run; the workflow owner records a BUILD entry only after reviewing actual code and test evidence.
- Do not ask for shell command output. The workflow runs the focused test suite after your edit.
- If no code+test change can be completed, leave the worktree clean.

## Completion
A successful iteration requires at least one meaningful source-code change and one regression-test change. Aider exit code zero alone is NOT success. The workflow independently runs `python -m unittest discover -s backend/tests -p test_queue.py`; if it fails, no Draft PR is created.
