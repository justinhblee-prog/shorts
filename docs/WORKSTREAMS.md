# NEXUS STUDIO PRO — Workstreams (2026-11-20)

**Repository:** https://github.com/justinhblee-prog/shorts  
**Integration candidate:** PR #407 — Modern analytics dashboard + audited quarantine recovery  
**Candidate head:** `77333d264a123d80c87e6ca13f1edfc0282be06a`  
**Status:** exact-head hosted CI PASS (880 tests + repository validation + frontend syntax + analytics/recovery Chromium smoke); Draft/unmerged.

| Lane | Scope | Current evidence | Next action |
|---|---|---|---|
| UI / Dashboard | Analytics history, responsive navigation, development-job monitor, quarantine recovery controls | PR #407 exact-head browser smoke passed; all 19 modules connected; artifact 14564045600 | Review visual artifact and dependency-preserving diff |
| Core / Policy | Durable queue, worker fencing, policy validation, synthetic-media disclosure, intake isolation | Included from aligned PR #406 stack; combined PR #407 exact-head CI passed | Review integration diff and API compatibility |
| Analytics | YouTube/TikTok history, freshness, bounded queries, pagination/export | PR #407 exact-head tests and Chromium smoke passed | Validate against real provider data after credentials/operator approval |
| Engineering automation | Persistent job graph, safe scopes, local Aider/Ollama executor, Draft PR evidence gate | Hosted regressions pass; real Windows runner cycle not proven | Windows preflight, persistent DB proof, real Ollama cycle |
| QA / Integration | Backend suite, frontend syntax, analytics and recovery Chromium smoke | 880 tests; all hosted exact-head checks passed | Preserve exact-head gate on every subsequent change |
| Release / Operations | OAuth, provider publishing, storage/media staging, production deployment | Not validated in live environment | Keep blocked until explicit operator-approved integration tests |

## Execution constraints

1. Keep independent file scopes parallel; serialize shared schemas, migrations, central API contracts and workflow changes.
2. Every job requires meaningful code, regression coverage, exact-head validation and review evidence.
3. Draft PRs only. No auto-merge, deployment, secret mutation, public publishing, destructive migration or paid-provider call.
4. Hosted CI, local runner validation, provider validation and production validation are separate evidence classes.
5. Do not report background continuation when no runner/workflow execution has actually occurred.

See [INTEGRATION_HANDOVER_2026-11-20.md](INTEGRATION_HANDOVER_2026-11-20.md) for full evidence and ordered gates.
