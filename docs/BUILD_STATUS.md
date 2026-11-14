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

Health, finance and crime/event content require source verification and non-sensational claims.

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
- Idempotency key on enqueue.
- Job event history and worker registry.
- Operator cancellation and expired-lease recovery APIs.
- Successful worker completion moves a job to review_pending; this milestone has no public publish transition.
- Unit tests cover idempotency, exclusive and concurrent claims, retry, stale worker fencing, cancellation and lease recovery.
- **Validation blocked:** GitHub Actions jobs are failing before checkout/steps. Python tests have not executed in a real runtime. Do not mark this build complete.

## BUILD-00002 — global trend ingestion

- Google News RSS provider for KR, US, JP and GB with locale parameters.
- Official Hacker News Firebase API provider using top-stories and item endpoints.
- Persistent `trend_signals` table with source URL deduplication, publication and collection timestamps.
- Preserve source-provided Hacker News score/comment counts; unavailable search-volume and video-view metrics remain null.
- API: POST `/api/trends/collect`; GET `/api/trends`.
- Provider and persistence unit tests added.
- **Validation pending:** live source requests and test execution have not been verified.

## BUILD-00004 — profitability scoring and prioritization

- Transparent low/high scenario calculator for views, RPM, ads, affiliate/sponsor revenue and production costs.
- Monetization eligibility gate forces estimated ad revenue to zero when not eligible.
- Requires an attributable forecast source; all outputs are labeled estimates, never actual revenue.
- Explainable 100-point priority model: margin 35%, ROI 25%, evidence 20%, strategic fit 10%, production feasibility 10%.
- Persists scored opportunities in SQLite. API: POST `/api/opportunities/score`, GET `/api/opportunities`.
- Unit tests cover range validation, monetization gate, scenario math and persistence; not executed yet.

## BUILD-00003 — competitor/channel intelligence

- YouTube Data API v3 provider for channel search, channel statistics and recent public video statistics.
- Stores channel snapshots and video counters in SQLite.
- API: GET `/api/competitors/search?q=...`; GET `/api/competitors/{channel_id}`; GET `/api/competitors`.
- Requires `YOUTUBE_DATA_API_KEY`; no key is committed to the repository.
- Search API calls consume quota (search.list is typically 100 quota units); direct channel IDs are preferred when available.
- Subscriber/view counts are point-in-time provider snapshots, not growth rates, view velocity, RPM or revenue.
- Unit tests use a fake transport; they are not a substitute for live API validation.

## Validation — current truth

- Source and test files are committed to main.
- GitHub Actions has repeatedly reported failed jobs with no step summaries and no downloadable logs. The runner has not reached checkout, dependency installation or unittest execution.
- The test suite has **not** passed or failed on code behavior; it has not executed.
- No production worker, PostgreSQL, external AI generation, OAuth, rendering or YouTube publishing has been validated.
- Build status reflects code committed, not successful production operation.

## Next actions

1. Resolve GitHub Actions runner/job initialization and execute the complete Python 3.11+ test suite.
2. Fix any runtime failures and verify BUILD-00001 concurrency, retry and lease-recovery behavior.
3. Validate Google News RSS and Hacker News live ingestion for all supported regions.
4. Configure a restricted YouTube Data API key and validate BUILD-00003 quota-aware channel/video retrieval.
5. Add data freshness, collection scheduling and source failure observability; then connect opportunity scoring to observed trend and competitor evidence.

## Versioning

- v0.1: initial repository and queue foundation.
- v0.11: minor improvements.
- v0.2: major integrated milestone.
