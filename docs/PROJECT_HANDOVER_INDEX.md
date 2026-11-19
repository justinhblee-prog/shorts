# NEXUS STUDIO PRO — 인수인계 문서 인덱스

- 문서 버전: v0.1
- 기준일: 2026-11-20 (KST)
- 저장소: https://github.com/justinhblee-prog/shorts
- 기준 브랜치: `integration/flow-status-and-ownership-2026-11-20`
- 문서 작업 브랜치: `docs/nexus-project-handover-2026-11-20`
- 상태: 초기 인수인계 기준선 작성 중. 기존 PR을 병합하거나 배포하지 않음.

## 목적

이 문서 세트는 제품 기획부터 요구사항, UX/UI, 시스템 설계, 개발, 테스트, 배포 준비까지 프로젝트를 다른 개발자·기획자·운영자에게 넘길 수 있는 단일 기준 자료입니다. 실제 코드와 CI 증거를 기준으로 유지하며, 미구현·미검증 항목을 완료로 표현하지 않습니다.

## 문서 구성

| 문서 | 내용 | 업데이트 조건 |
|---|---|---|
| [제품 기획 및 요구사항](PRODUCT_AND_REQUIREMENTS.md) | 제품 목적, 고객/운영자, 핵심 가치, 기능 범위, 정책, 성공 지표, 미결정 사항 | 제품 방향·범위·우선순위 변경 시 |
| [시스템 및 UX 설계](SYSTEM_ARCHITECTURE.md) | 현재 구조, 데이터 흐름, UI 구조, 모듈 경계, 보안·외부 연동 설계 | API·DB·UI·인프라 구조 변경 시 |
| [개발·검증·릴리스 인수인계](DEVELOPMENT_AND_VALIDATION.md) | 브랜치/PR 규칙, 멀티 Flow, 테스트 기준, 현재 PR 및 검증 현황, 실행 방법 | 모든 개발 작업 완료/실패/차단 시 |
| [기존 기술 핸드오버](HANDOVER.md) | BUILD 단계별 기술 이력 | Core 기능 구현 및 운영 조건 변경 시 |
| [병렬 워크스트림 현황](WORKSTREAMS.md) | lane 소유권, PR 의존성, 작업 현황 | 워크스트림 시작·종료·의존성 변경 시 |
| [작업 오케스트레이션](DEVELOPMENT_JOB_ORCHESTRATION.md) | job 상태 전이, 병렬 실행·완료 게이트 | 자동 개발/worker 동작 변경 시 |
| [개발 상태](BUILD_STATUS.md) | 제품·Core 개발 이력과 검증 근거 | 기능 상태 및 검증 결과 변경 시 |

## 인수인계 원칙

1. 코드가 기준이며 문서는 코드와 일치해야 합니다.
2. 상태는 `설계`, `구현`, `자동 테스트 통과`, `브라우저 검증`, `실환경 검증`, `운영 확인`을 구분합니다.
3. 이전 커밋의 테스트 결과를 최신 커밋의 증거로 재사용하지 않습니다.
4. Mock·fixture 테스트는 외부 서비스 실연동 성공을 의미하지 않습니다.
5. Draft PR은 승인 없이 병합하지 않습니다. 배포·공개 게시·실제 과금 행위는 별도 승인과 운영 확인이 필요합니다.
6. 매 변경 시 기준일, 관련 PR/commit, 변경 내용, 테스트, 남은 위험, 다음 작업을 기록합니다.
7. 문서끼리 내용이 충돌하면 실제 코드·최신 CI 결과를 확인한 뒤 정정하고, 오래된 설명은 삭제하거나 과거 기록으로 명시합니다.

## 최신 확인 기준선

- 통합 후보: PR #407 — [Modern analytics dashboard with audited quarantine recovery](https://github.com/justinhblee-prog/shorts/pull/407), Draft/unmerged.
- PR #407 source head `b9b375a3ea9f95ef7ab4b18210ec43f474824fb4` passed hosted run [44586621312](https://github.com/justinhblee-prog/shorts/actions/runs/44586621312): **879 tests**, frontend syntax, authenticated dashboard with all 19 modules connected, analytics Chromium smoke, quarantine recovery Chromium smoke.
- This candidate includes UI-00013/00014 visual system, UI-00015–00017 analytics pagination/semantics, Core/Policy controls and Engineering quarantine recovery workspace.
- Actual browser visual review found and corrected missing Korean font fallback and full-page screenshot scroll positioning. The final artifact [14559944009](https://github.com/justinhblee-prog/shorts/actions/runs/44586621312/artifacts/14559944009) contains desktop 1440px and mobile 320px screenshots with readable Korean text, visible desktop rail, and API connected state.
- API contract closure: restored bounded `GET /api/publishing/overview`; implemented audited provider-attempt reconciliation endpoint; activated two previously undiscovered API security tests by moving the unittest main guard to the file end.
- PR #407 source head `0bcc4cfaa7d8b88f89b43c2984bebdb188bec87e` passed [workflow 44588685235](https://github.com/justinhblee-prog/shorts/actions/runs/44588685235): 880 tests, frontend syntax, both Chromium browser suites, and artifact upload. The source includes authenticated-principal binding for provider reconciliation and a regression test rejecting spoofed operator IDs. Backend README was subsequently clarified in commit `77333d264a123d80c87e6ca13f1edfc0282be06a`; exact-head run [44589059999](https://github.com/justinhblee-prog/shorts/actions/runs/44589059999) passed 880 tests and both browser suites. Final artifact: [14564045600](https://github.com/justinhblee-prog/shorts/actions/runs/44589059999/artifacts/14564045600).
- Handover docs are maintained on Draft PR #396. All PRs remain unmerged; no production deployment, real OAuth/provider publishing, or live production recovery is claimed.

## 변경 이력

- 2026-11-20: 최초 인수인계 문서 세트 v0.1 작성. 저장소의 기존 제품 설명, WORKSTREAMS, HANDOVER, Orchestration, backend README 및 PR #395 상태를 기준으로 정리.
