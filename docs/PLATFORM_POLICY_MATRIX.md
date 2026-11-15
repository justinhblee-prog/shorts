# Platform Policy Preflight Matrix

**Version:** 0.2  
**Policy pack:** `2026-11-15.2`  
**Checked:** 2026-11-15  
**Scope:** YouTube Shorts and TikTok short-form production

This matrix is an operational risk screen, not legal advice, platform approval, a monetization guarantee, or a complete moderation system. The engine evaluates operator-supplied declarations and evidence references; it does not inspect rendered video/audio bytes, thumbnails, captions, or the full channel history.

## Official source register

| Platform | Policy area | Official source |
|---|---|---|
| YouTube | Spam, fake engagement, automated/repetitive content | https://support.google.com/youtube/answer/2801973 |
| YouTube | Inauthentic and reused content / monetization | https://support.google.com/youtube/answer/1311392 |
| YouTube | Realistic altered or synthetic media disclosure | https://support.google.com/youtube/answer/14328491 |
| YouTube | Advertiser-friendly content | https://support.google.com/youtube/answer/6162278 |
| TikTok | AI-generated content and realistic media disclosure | https://support.tiktok.com/en/using-tiktok/creating-videos/ai-generated-content |
| TikTok | Community Guidelines | https://www.tiktok.com/community-guidelines/en/ |

Re-check these sources at upload time and after platform policy updates. Rules can differ by country, product surface, monetization program, and content category.

## Decision levels

- **blocked:** an explicit prohibited/high-risk flag or denied asset-rights declaration was supplied. The job must not enter production.
- **review_required:** required declarations or evidence are missing. A human review note alone cannot override entries in `approval_blockers`.
- **ready_for_human_review:** required declarations are present. This is not approval; a human must still inspect the actual script and media and make the approval decision.

### Non-overridable approval blockers

- Visual, audio, or likeness rights are not explicitly cleared.
- Synthetic-media status is unknown.
- Realistic AI-generated/altered content lacks the disclosure acknowledgement for each selected platform:
  - YouTube: `platform_disclosures.youtube_altered_content` and an explicit `youtube_contains_synthetic_media` classification.
  - TikTok: `platform_disclosures.tiktok_ai_generated_content`.
- For YouTube, the API boolean must reflect whether the content contains realistic altered or synthetic material; generic AI generation alone is not enough to infer the value.

The acknowledgement is an operator attestation. It does not itself apply the platform label. The upload/publishing workflow must still apply the platform's actual disclosure setting.

## Risk review declarations

| Risk flag | Required evidence/action |
|---|---|
| `health_or_medical_claims` | Source-backed human review; avoid unsupported diagnosis/treatment claims |
| `financial_or_investment_claims` | Evidence notes; no guaranteed returns or unsupported performance claims |
| `current_events_or_news` | HTTPS source URL(s), date/context verification |
| `third_party_clips_or_music` | Asset-level rights and platform music permissions |
| `reused_or_compiled_content` | Document substantial original commentary, analysis, or educational value |
| `repetitive_or_mass_produced` | Review channel-level repetition and meaningful variation |
| `sponsored_or_affiliate_content` | Confirm commercial relationship disclosure |
| `minors_appear` | Child-safety/privacy review and permissions |
| `regulated_goods_or_services` | Regional restrictions and age/platform rules |
| `sensitive_personal_data` | Data minimization, consent, and lawful-use review |

The hard-block flags include known unauthorized assets, non-consensual likeness, deceptive impersonation, prohibited content, fake engagement/platform evasion, child-safety violations, scams/fraud, and private personal-data exposure.

## Data contract

Production briefs may carry:

- `platforms`: selected targets, defaulting to YouTube and TikTok.
- `rights`: `visuals_cleared`, `audio_cleared`, `likeness_authorized`.
- `synthetic_media_status`: `none`, `ai_assisted_nonrealistic`, `ai_generated`, `realistic_alteration`, or `unknown`.
- `platform_disclosures`: platform-specific AI disclosure acknowledgements.
- `youtube_contains_synthetic_media`: required boolean realism classification for YouTube AI-generated content; set true for realistic altered/synthetic content and false only when it is not realistic A/S content.
- `policy_flags`: explicit hard-block flags.
- `risk_flags`: elevated-review categories.
- `claim_evidence_notes`, `source_urls`, `transformative_contribution`, `commercial_relationship_disclosed`, and `child_safety_review_confirmed`.

The generated policy report is stored with the script artifact and included in the review snapshot. A policy-blocked job is stopped before the first AI provider call. A review report with approval blockers cannot be approved, even if the reviewer supplies a comment.

## Current limitations and next controls

1. The preflight is metadata-based. Automated frame/audio/transcript scanning and asset-level copyright matching are not implemented.
2. Rights, consent, and factuality declarations are not independently verified.
3. YouTube Data API v3 supports `status.containsSyntheticMedia` on `videos.insert` and `videos.update`; the YouTube upload branch now maps the explicit policy classification to this field and blocks unresolved classifications. See https://developers.google.com/youtube/data/reference/rest/v3/videos and https://developers.google.com/youtube/v3/revision_history.
4. TikTok Content Posting API documents `is_aigc` for Direct Post and labels the post when true. The private Direct Post adapter maps the approved classification to this field, enforces `SELF_ONLY`, and tracks status. Live developer-app audit, creator authorization and account-level label verification remain pending. See https://developers.tiktok.com/doc/content-posting-api-reference-direct-post.
5. Monetization eligibility is channel- and content-level. A per-video checklist cannot certify YouTube Partner Program eligibility.
6. Regional legal review is still required for privacy, publicity/likeness, health, financial, advertising, and regulated-goods topics.
7. Public publishing remains disabled by default. YouTube upload remains private-only and requires explicit human approval. TikTok Direct Post is restricted to `SELF_ONLY`, requires per-post operator consent, and uses server-side OAuth tokens encrypted at rest.

## Validation

Unit tests cover explicit blocking, unknown/denied rights, platform-specific realistic-AI disclosure, selected-platform scoping, high-impact claim evidence, news source requirements, invalid flag rejection, and non-overridable approval blockers. CI results must be recorded after this branch's workflow completes.
