# NEXUS STUDIO PRO — Development Status

**Baseline:** v0.1  
**Repository:** https://github.com/justinhblee-prog/shorts  
**Updated:** 2026-11-15

## Business objective

Automate a profitable short-form video operation: global topic discovery → evidence-backed opportunity scoring → script/voice/video production → human review → publishing → measured revenue and cost analysis → strategy improvement.

Business success is measured by verified net revenue, ROI, content throughput, and operating cost. Forecasts remain estimates. Public publishing requires explicit human approval.

## Brand portfolio

1. Brain Glitch — neuroscience and psychology
2. Silent Signals — relationships and nonverbal psychology
3. Unseen Truth — history and hidden context
4. Dark Files Global — space, deep sea, mysteries
5. 99% Missed — everyday knowledge and productivity
6. Money Glitch — economics and finance
7. Secret Vault 24 — corporate and economic secrets
8. Future Leak — AI and future technology
9. 30Sec Shift — health, sleep and longevity
10. Why Nobody Tells — social and business insights

## Build roadmap

| ID | Scope | State |
|---|---|---|
| BUILD-00001 | Durable queue and Worker Lease | Source implemented; execution validation blocked |
| BUILD-00002 | Global trend ingestion | Provider/API/tests implemented; live and runtime validation pending |
| BUILD-00003 | Competitor/channel intelligence | Provider/API/tests implemented; API-key and runtime validation pending |
| BUILD-00004 | Profitability scoring and prioritization | Scenario calculator/API/tests implemented; runtime validation pending |
| BUILD-00005 | AI script, voice and video pipeline | Not started |
| BUILD-00006 | Ten-brand operations | Not started |
| BUILD-00007 | Review and approval workflow | Human-review gate designed; integration pending |
| BUILD-00008 | YouTube publishing and tracking | Not started |
| BUILD-00009 | Revenue, cost and ROI analytics | Not started |
| BUILD-00010 | AI performance analysis and strategy updates | Not started |
| BUILD-00011 | Scheduling and recovery operations | Not started |
| BUILD-00012 | Integrated validation and deployment | Not started |

## BUILD-00001 — durable queue and Worker Lease

- SQLite durable queue with WAL, foreign keys, busy timeout and safe connection cleanup.
- Serialized claim transactions using BEGIN IMMEDIATE.
- Worker lease expiry and UUID fencing token.
- Heartbeat, completion, failure, retryable re-claim and terminal retry handling.
- Idempotency key on enqueue; event history and worker registry.
- Operator cancellation and expired-lease recovery APIs.
- Successful worker completion moves a job to review_pending; this milestone has no public publish transition.
- Tests cover idempotency, exclusive/concurrent claims, retry, stale worker fencing, cancellation and lease recovery.
- **Not complete:** runtime tests have not executed.

## BUILD-00002 — global trend ingestion

- Google News RSS provider for KR, US, JP and GB.
- Official Hacker News Firebase API provider using top-stories and item endpoints.
- Persistent `trend_signals` table with source URL deduplication and timestamps.
- Preserve provider metrics only; unavailable search-volume and video-view metrics remain null.
- API: POST `/api/trends/collect`; GET `/api/trends`.
- Provider and persistence unit tests committed; live and runtime validation pending.

## BUILD-00003 — competitor/channel intelligence

- YouTube Data API v3 channel search, channel statistics and recent public video statistics.
- Stores channel snapshots and video counters in SQLite.
- API: GET `/api/competitors/search?q=...`; GET `/api/competitors/{channel_id}`; GET `/api/competitors`.
- Requires runtime secret `YOUTUBE_DATA_API_KEY`; no key is committed.
- Search.list typically consumes 100 quota units; prefer known channel IDs.
- Counters are snapshots, not growth rates, view velocity, RPM or revenue.
- Fake-transport tests committed; live API validation pending.

## BUILD-00004 — profitability scoring

- Transparent low/high scenario model for forecast views, RPM, ad/affiliate/sponsor revenue and operating costs.
- Monetization eligibility gate sets ad revenue to zero when the channel is not eligible.
- A forecast source is mandatory; outputs are explicitly labeled estimates.
- Explainable priority score: margin 35%, ROI 25%, evidence quality 20%, strategic fit 10%, production feasibility 10%.
- SQLite persistence and API: POST `/api/opportunities/score`; GET `/api/opportunities`.
- Unit tests committed; runtime validation pending.

## Validation — current truth

- Code and tests are committed to the private repository main branch.
- Latest observed GitHub Actions run: https://github.com/justinhblee-prog/shorts/actions/runs/43654067499
- GitHub job metadata reported `runner_id=0`, empty runner name, and `steps=[]`; the job failed before checkout or dependency installation. This is an environment/runner initialization failure, not evidence of a Python test failure.
- The suite has not passed or failed on code behavior; it has not executed in a real Python runtime.
- No production worker, PostgreSQL, external AI generation, OAuth, rendering or YouTube publishing has been validated.
- Do not claim real earnings, real monetization or a complete automated business cycle.

## Next actions

1. Resolve GitHub Actions runner allocation / repository Actions availability.
2. Run `pip install -r backend/requirements.txt` and `python -m unittest discover -s tests -v` from `backend/` on Python 3.11+.
3. Fix failures and validate queue concurrency, lease recovery, trend ingestion and competitor data.
4. Connect observed trend and competitor evidence into the opportunity scoring inputs.
5. Continue with BUILD-00005 only after the business data foundations are validated.

## Versioning

- v0.1: initial repository and queue foundation.
- v0.11: minor improvements.
- v0.2: major integrated milestone.
