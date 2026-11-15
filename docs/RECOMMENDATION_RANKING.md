# Recommendation Ranking v0.2

## Purpose and boundary

The recommendation score is an **editorial topic-prioritization heuristic** for choosing which collected trend a brand should investigate and produce. It is not a claim to reproduce YouTube or TikTok's private recommendation systems, and it is not a view, revenue, or virality forecast.

The ranking output must be reviewed by an operator. Platform policy eligibility is evaluated separately against the completed production brief before provider generation and again at publish time.

## Score formula (0–100)

| Component | Maximum | Rule |
|---|---:|---|
| Freshness | 40 | Linear decay from 40 to 0 over 168 hours, using only the publisher's \`published_at\` timestamp |
| Brand fit | 40 | Weighted profile-term coverage across keywords, vertical, brand name, positioning and audience; explicit excluded terms zero the fit |
| Source provenance | 10 | Source label 3, HTTPS source URL 3, valid publisher timestamp 4 |
| Topic distinctiveness | 10 | \`10 × (1 − max Jaccard similarity)\` against other candidates in the same ranking batch |

Missing or invalid \`published_at\` is treated as **unverified freshness** and receives zero freshness points. \`collected_at\` is never substituted for publisher time, because a newly collected old article must not appear fresh.

Region and language are eligibility filters. Region matching is case-insensitive. Language matching uses the language family (\`en-US\` and \`en-GB\` both match \`en\`). If a brand has no configured region/language restrictions, that dimension is unrestricted.

## Evidence that is displayed but does not affect score

- Competitor view counters are limited to the stored sample of up to ten recently collected channels and up to thirty recent videos per channel. They are not market-wide demand, saturation, view velocity or revenue.
- Historical brand performance and topic-matched video measurements are shown for review only. They do not alter score until a held-out evaluation proves that the adjustment improves outcomes without leakage or overfitting.
- Comparable cohorts remain context-only. Brand, region, topic overlap, publication-age and duration are kept as separate dimensions.

## Known evidence gaps

- Search volume and market-wide Shorts/TikTok demand are not measured.
- Competitor sample coverage is limited and may be biased by the selected channels.
- Recommendation-system weights and eligibility rules on YouTube and TikTok are proprietary and can change.
- A high editorial score does not imply platform policy approval, monetization eligibility, audience satisfaction, or guaranteed revenue.

## Validation and future calibration

The unit tests cover timestamp provenance, freshness decay, region/language matching, explicit brand exclusions, duplicate-topic distinctiveness, and the rule that historical performance cannot silently change the ranking score.

Do not tune weights using the same observations used to claim success. Before any score adjustment:
1. Capture recommendation impressions, human selection/skip decisions and reasons.
2. Link published outcomes to the original recommendation and platform/brand/region.
3. Compare a time-based holdout against the current formula.
4. Report sample size, coverage, confidence intervals and policy-block rate.
5. Keep a rollbackable algorithm version and require human approval before production weight changes.
