# 프로젝트 진행 상황 (Progress Tracker)

- **프로젝트**: NEXUS STUDIO PRO 통합 후보 PR #415
- **전체 상태**: 완료 (100% - 이번 작업 범위)
- **마지막 업데이트**: Step 7 - 최종 검증·인수인계 완료
- **검증된 workflow/handover 커밋**: `b78ebc8cb9d8a3bd13d7a2016eb4930bd2af0daf`
- **진행 브랜치**: `integration/nexus-aggregate-ui-core-2026-11-20`
- **PR**: https://github.com/justinhblee-prog/shorts/pull/415
- **안전 상태**: PR Draft/open/unmerged. 병합·배포·default branch 변경 없음.

## 1. 워크플로우 체크리스트

- [x] Step 0: 목표·범위·검증 기준 확정 및 `progress.md` 생성
- [x] Step 1: PR, 브랜치, CI, 변경 파일 상태 재확인
- [x] Step 2: 백엔드·Core·Automation 정적/단위 검증 결과 확인
- [x] Step 3: Playwright 대시보드 UI 브라우저 테스트 통과 확인
- [x] Step 4: 복구·의존성 UI 브라우저 테스트 통과 및 스크린샷 산출물 확인
- [x] Step 5: CI font setup 지연 원인 제거 및 재검증
- [x] Step 6: 통합 인수인계 문서와 PR 검증 요약 갱신
- [x] Step 7: 최종 CI, PR 상태, 외부 의존성, 산출물 링크 확인

## 2. 단계별 핵심 산출물 및 데이터 요약

- **Step 0**: 현재 대화의 지속 프로젝트를 바탕으로 목표를 NEXUS STUDIO PRO 통합 후보 PR #415 검증·인수인계로 확정. 외부 실환경은 이번 검증 범위에서 분리.
- **Step 1**: PR #415 open/Draft, 통합 브랜치와 28개 변경 파일 확인. PR은 mergeable=true, 미병합 상태.
- **Step 2**: run [44647755797](https://github.com/justinhblee-prog/shorts/actions/runs/44647755797)에서 `scripts/validate.sh`와 `node --check frontend/app.js` 성공.
- **Step 3**: 동일 run의 `scripts/ui_browser_smoke.mjs` 성공. 인증 대시보드/API, 리뷰 승인·감사 이력, 분석 페이지네이션/CSV, 부분 API 장애 피드백, 키보드·브라우저 이력, 반응형/320px 레이아웃 확인.
- **Step 4**: 동일 run의 `scripts/ui_recovery_browser_smoke.mjs` 성공. UI/Core workstream, 선행 완료 작업, 320px 의존성 보드, 격리 작업 복구, ready 상태 및 immutable audit attribution 확인.
- **브라우저 아티팩트**:
  - 최종 CI 아티팩트 [14589303074](https://github.com/justinhblee-prog/shorts/actions/runs/44647755797/artifacts/14589303074) 업로드 성공. hosted runner에 Noto CJK가 없어 fallback 글꼴로 렌더링된 스크린샷임.
  - 시각 검토용 아티팩트 [14589176582](https://github.com/justinhblee-prog/shorts/actions/runs/44646542482): 데스크톱 1440px, 모바일 320px 이미지 다운로드 후 직접 열어 확인했고 한국어 글리프가 정상 표시됨.
- **Step 5**: APT mirror로 인한 반복 지연을 제거하기 위해 font package 설치를 CI에서 제거하고 빠른 font availability check로 변경. 이후 exact-head run 44647416771 및 44647755797에서 브라우저 테스트 전 단계와 후속 검증이 완료됨.
- **Step 6**: `docs/INTEGRATION_HANDOVER_2026-11-20.md`에 aggregate browser PASS, run/artifact 링크, font screenshot caveat, Windows/Ollama 및 live provider 미검증 범위를 기록. PR #415 본문도 현재 검증 상태에 맞게 갱신.
- **Step 7**: exact tested handover/workflow head `b78ebc8cb9d8a3bd13d7a2016eb4930bd2af0daf`에서 run [44647755797](https://github.com/justinhblee-prog/shorts/actions/runs/44647755797) 전체 17단계 성공 확인. PR #415는 open/Draft/mergeable/unmerged. review thread/review 없음.

## 3. 자율 의사결정 및 이슈 로그

- [Step 0] 템플릿의 목표란은 비어 있어 지속 프로젝트와 현재 작업을 기준으로 PR #415 통합 검증·인수인계로 범위를 확정.
- [Step 0] 기존 UI 유지, Draft 유지, 병합·배포·default branch 변경 금지, 실환경 미검증 항목의 PASS 금지를 안전 제약으로 설정.
- [Step 1] 초기 CI run `44644705431`은 font step에서 정체했고 로그 API 404로 PASS 불인정.
- [Step 2–4] run `44646542482`, `44647416771`, `44647755797`에서 backend validation, frontend syntax, 두 Chromium smoke, artifact upload가 성공.
- [Step 5] APT 설치 timeout 시도 후에도 runner가 정체하여 외부 package mirror 의존성을 제거. availability check만 남긴 최종 workflow에서 run 44647755797 전체 성공.
- [Step 6] handover와 PR 본문을 갱신하고 최신 테스트 근거와 화면 스크린샷의 글꼴 한계를 명확히 기록.
- [Step 7] 최종 exact-head CI 및 PR 상태 확인 완료. 현재 범위의 산출물·문서·검증을 마침.

## 4. 외부 의존성 및 미완료 운영 게이트 (별도 승인/환경 필요)

아래 항목은 이번 hosted CI 작업 범위 밖이며 미검증 상태입니다. 완료율 100%는 위에서 정의한 통합 후보의 코드·문서·hosted validation 범위에 대한 것입니다.

- **BLOCKED**: Windows worker workflow가 default branch에 없으므로 이 unmerged candidate에서 workflow_dispatch 실행 불가.
- **NOT VERIFIED**: Trusted Windows self-hosted runner의 실제 실행.
- **NOT VERIFIED**: 서로 다른 두 Windows job 사이의 LocalAppData tooling/SQLite persistence.
- **NOT VERIFIED**: 실제 Ollama 모델 생성 및 scoped code change/Draft PR 발행 사이클.
- **NOT VERIFIED**: OAuth/provider account, 실제 미디어 렌더링, live YouTube/TikTok publishing.
- 이 항목들은 사용자 승인 또는 default branch 변경/실제 Windows 실행환경 등 외부 조건 없이는 수행할 수 없으므로 PASS로 표시하지 않았습니다.

## 5. 최종 산출물

- 통합 후보 PR: https://github.com/justinhblee-prog/shorts/pull/415
- 인수인계 문서: `docs/INTEGRATION_HANDOVER_2026-11-20.md`
- 멀티플로우 실행계획: `docs/MULTI_FLOW_EXECUTION.md`
- 상태 추적: `progress.md`
- 최종 hosted validation: [44647755797](https://github.com/justinhblee-prog/shorts/actions/runs/44647755797)
- 읽기 쉬운 데스크톱/모바일 화면 증거: [14589176582](https://github.com/justinhblee-prog/shorts/actions/runs/44646542482)



## 23. Default-branch activation dependency audit — 2026-11-20

- Rechecked repository default branch metadata: `main`.
- Confirmed `.github/workflows/nexus-development-job-worker.yml` is absent from `main` (GitHub Contents API returned 404 for that path).
- Confirmed the worker's executable prerequisites are also absent from `main`: `backend/run_development_agent.py`, `backend/development_agent_executor.py`, `backend/recover_development_reviews.py`, `backend/publish_development_reviews.py`, and `backend/tests/test_development_worker_workflow_contract.py`.
- `backend/requirements.txt` exists on `main`, but that alone is insufficient: the workflow's Python entrypoints and contract tests are not present there. Copying only the workflow file to `main` would create a broken activation and is explicitly not the next step.
- Required promotion unit must be dependency-complete and reviewed as one stack: worker workflow + worker/executor/backlog/intake/review-publication modules + seed/data contracts + tests + any required backend dependencies. Before proposing activation, compare every imported module and referenced path against `main`, then run the main-targeted CI suite on the promotion branch.
- No promotion PR, default-branch update, workflow dispatch, merge, or runner execution was performed. This is a verified activation dependency, not a claim that the Windows runner is offline.


## 24. Worker activation dependency closure — 2026-11-20

- 2차 import/call-site 감사를 수행해 누락 범위를 확장했습니다. `main`에는 `development_jobs.py`, `development_job_worker.py`, `development_github_intake.py`, `development_backlog_service.py`, `development_security.py`, `seed_development_jobs.py`, `development_agent_executor.py`, `publish_development_reviews.py`, `recover_development_reviews.py`, `run_development_agent.py` 및 worker workflow가 모두 없습니다.
- import 연결 확인: entrypoint → executor/backlog/intake/store/security/seed; executor → worker/security; backlog → worker/intake; worker → store/security; intake → store; store → security; seed → store; recovery → store/review publisher; review publisher → store.
- workflow contract test도 `main`에 없습니다. worker 전용 unit/regression tests, orchestration design contract, workflow path filters 및 validation script 연계까지 promotion closure에 포함해야 합니다. 테스트 파일명은 실제 branch tree와 CI discovery를 기준으로 확정합니다.
- `backend/requirements.txt`는 `main`에 이미 존재합니다. 현재 확인한 worker import는 표준 라이브러리와 기존 backend dependency set을 사용하므로 promotion 시 dependency diff를 재검토하고 불필요한 전체 requirements 교체를 피합니다.
- 보안 게이트: job-level contents/pull-requests/actions write 권한 최소화, read-only intake token과 PR publication token 분리, Windows runner 격리, LocalAppData 외부 저장, scope allowlist와 symlink 해석 검증, Aider child-process credential stripping, secrets/production data 경로 제외.
- 필수 runner: self-hosted Windows + `nexus-local-ai` label, Actions runner >= 2.327.1, Python >= 3.11, Git Bash, Node >= 18, loopback Ollama, 정확한 `qwen2.5-coder:7b` 모델. `NEXUS_GITHUB_READ_TOKEN`, `NEXUS_APPROVED_SCOPES`, repository GITHUB_TOKEN 권한도 별도 확인해야 합니다.
- Windows 실 runner 실행, LocalAppData 2회 실행 persistence, Ollama 생성 검증은 아직 수행되지 않았습니다. 승인 전 workflow dispatch/예약 활성화/merge/default branch 변경은 하지 않습니다.


## 25. Mainline worker promotion package boundary — 2026-11-20

- main...integration/nexus-aggregate-ui-core-2026-11-20 비교 결과 integration branch는 main보다 1,307 commits ahead / 5 behind이며 worker 외에 production pipeline, queue/scheduler, TikTok/YouTube, recommendation/metrics, frontend UI 등 광범위한 변경을 포함합니다. PR #415도 100 commits이며 base가 main이 아닌 integration branch입니다. 따라서 PR #415 전체를 Windows worker 활성화 목적으로 승격하지 않기로 결정했습니다.
- 별도 main 기반 승격 PR의 최소 runtime 파일 12개: worker workflow, development_agent_executor.py, development_backlog_service.py, development_github_intake.py, development_job_worker.py, development_jobs.py, development_security.py, publish_development_reviews.py, recover_development_reviews.py, run_development_agent.py, seed_development_jobs.py, sync_development_backlog.py.
- 함께 가져갈 worker 전용 테스트 12개: executor, scope normalization, backlog service, GitHub intake, job worker, jobs store, security, workflow contract, review publisher, run entrypoint, seed, backlog sync 테스트.
- API 전용 test_development_job_api_security.py와 test_development_job_recovery_api.py는 standalone CLI worker 필수 항목이 아닙니다. 추후 dashboard API를 승격한다면 backend/app.py, 권한 변경, 해당 API 테스트를 하나의 별도 단위로 검토합니다.
- 공통 검증 조정: backend/requirements.txt에 PyYAML>=6.0,<7.0 추가 필요. main의 scripts/validate.sh가 YAML 파서를 사용하지만 main requirements에는 PyYAML이 없습니다. backend-tests.yml push/PR path filter도 worker workflow 및 contract test가 요구하는 docs/README/.gitignore 변경을 검증하도록 갱신해야 합니다.
- scripts/validate.sh는 main에 이미 있으며 compileall + 전체 backend unittest discovery를 수행합니다. 새 main 기반 브랜치에서 이 명령과 frontend syntax/workflow contract 검증을 수행해야 합니다.
- 승격 제외: aggregate branch의 unrelated production pipeline, queue/scheduler, platform integrations, recommendation/metrics, frontend/dashboard, broad app.py changes.
- 현재 상태: 파일 경계/import graph AUDITED. main 기반 승격 브랜치와 CI는 미생성/미실행. Windows 실 runner, 2회 실행 persistence, Ollama 생성은 NOT VERIFIED. merge/dispatch/schedule/default branch 변경 없음.
# 프로젝트 진행 상황 (Progress Tracker)

- **프로젝트**: NEXUS STUDIO PRO 통합 후보 PR #415
- **전체 상태**: 완료 (100% - 이번 작업 범위)
- **마지막 업데이트**: Step 7 - 최종 검증·인수인계 완료
- **검증된 workflow/handover 커밋**: `b78ebc8cb9d8a3bd13d7a2016eb4930bd2af0daf`
- **진행 브랜치**: `integration/nexus-aggregate-ui-core-2026-11-20`
- **PR**: https://github.com/justinhblee-prog/shorts/pull/415
- **안전 상태**: PR Draft/open/unmerged. 병합·배포·default branch 변경 없음.

## 1. 워크플로우 체크리스트

- [x] Step 0: 목표·범위·검증 기준 확정 및 `progress.md` 생성
- [x] Step 1: PR, 브랜치, CI, 변경 파일 상태 재확인
- [x] Step 2: 백엔드·Core·Automation 정적/단위 검증 결과 확인
- [x] Step 3: Playwright 대시보드 UI 브라우저 테스트 통과 확인
- [x] Step 4: 복구·의존성 UI 브라우저 테스트 통과 및 스크린샷 산출물 확인
- [x] Step 5: CI font setup 지연 원인 제거 및 재검증
- [x] Step 6: 통합 인수인계 문서와 PR 검증 요약 갱신
- [x] Step 7: 최종 CI, PR 상태, 외부 의존성, 산출물 링크 확인

## 2. 단계별 핵심 산출물 및 데이터 요약

- **Step 0**: 현재 대화의 지속 프로젝트를 바탕으로 목표를 NEXUS STUDIO PRO 통합 후보 PR #415 검증·인수인계로 확정. 외부 실환경은 이번 검증 범위에서 분리.
- **Step 1**: PR #415 open/Draft, 통합 브랜치와 28개 변경 파일 확인. PR은 mergeable=true, 미병합 상태.
- **Step 2**: run [44647755797](https://github.com/justinhblee-prog/shorts/actions/runs/44647755797)에서 `scripts/validate.sh`와 `node --check frontend/app.js` 성공.
- **Step 3**: 동일 run의 `scripts/ui_browser_smoke.mjs` 성공. 인증 대시보드/API, 리뷰 승인·감사 이력, 분석 페이지네이션/CSV, 부분 API 장애 피드백, 키보드·브라우저 이력, 반응형/320px 레이아웃 확인.
- **Step 4**: 동일 run의 `scripts/ui_recovery_browser_smoke.mjs` 성공. UI/Core workstream, 선행 완료 작업, 320px 의존성 보드, 격리 작업 복구, ready 상태 및 immutable audit attribution 확인.
- **브라우저 아티팩트**:
  - 최종 CI 아티팩트 [14589303074](https://github.com/justinhblee-prog/shorts/actions/runs/44647755797/artifacts/14589303074) 업로드 성공. hosted runner에 Noto CJK가 없어 fallback 글꼴로 렌더링된 스크린샷임.
  - 시각 검토용 아티팩트 [14589176582](https://github.com/justinhblee-prog/shorts/actions/runs/44646542482): 데스크톱 1440px, 모바일 320px 이미지 다운로드 후 직접 열어 확인했고 한국어 글리프가 정상 표시됨.
- **Step 5**: APT mirror로 인한 반복 지연을 제거하기 위해 font package 설치를 CI에서 제거하고 빠른 font availability check로 변경. 이후 exact-head run 44647416771 및 44647755797에서 브라우저 테스트 전 단계와 후속 검증이 완료됨.
- **Step 6**: `docs/INTEGRATION_HANDOVER_2026-11-20.md`에 aggregate browser PASS, run/artifact 링크, font screenshot caveat, Windows/Ollama 및 live provider 미검증 범위를 기록. PR #415 본문도 현재 검증 상태에 맞게 갱신.
- **Step 7**: exact tested handover/workflow head `b78ebc8cb9d8a3bd13d7a2016eb4930bd2af0daf`에서 run [44647755797](https://github.com/justinhblee-prog/shorts/actions/runs/44647755797) 전체 17단계 성공 확인. PR #415는 open/Draft/mergeable/unmerged. review thread/review 없음.

## 3. 자율 의사결정 및 이슈 로그

- [Step 0] 템플릿의 목표란은 비어 있어 지속 프로젝트와 현재 작업을 기준으로 PR #415 통합 검증·인수인계로 범위를 확정.
- [Step 0] 기존 UI 유지, Draft 유지, 병합·배포·default branch 변경 금지, 실환경 미검증 항목의 PASS 금지를 안전 제약으로 설정.
- [Step 1] 초기 CI run `44644705431`은 font step에서 정체했고 로그 API 404로 PASS 불인정.
- [Step 2–4] run `44646542482`, `44647416771`, `44647755797`에서 backend validation, frontend syntax, 두 Chromium smoke, artifact upload가 성공.
- [Step 5] APT 설치 timeout 시도 후에도 runner가 정체하여 외부 package mirror 의존성을 제거. availability check만 남긴 최종 workflow에서 run 44647755797 전체 성공.
- [Step 6] handover와 PR 본문을 갱신하고 최신 테스트 근거와 화면 스크린샷의 글꼴 한계를 명확히 기록.
- [Step 7] 최종 exact-head CI 및 PR 상태 확인 완료. 현재 범위의 산출물·문서·검증을 마침.

## 4. 외부 의존성 및 미완료 운영 게이트 (별도 승인/환경 필요)

아래 항목은 이번 hosted CI 작업 범위 밖이며 미검증 상태입니다. 완료율 100%는 위에서 정의한 통합 후보의 코드·문서·hosted validation 범위에 대한 것입니다.

- **BLOCKED**: Windows worker workflow가 default branch에 없으므로 이 unmerged candidate에서 workflow_dispatch 실행 불가.
- **NOT VERIFIED**: Trusted Windows self-hosted runner의 실제 실행.
- **NOT VERIFIED**: 서로 다른 두 Windows job 사이의 LocalAppData tooling/SQLite persistence.
- **NOT VERIFIED**: 실제 Ollama 모델 생성 및 scoped code change/Draft PR 발행 사이클.
- **NOT VERIFIED**: OAuth/provider account, 실제 미디어 렌더링, live YouTube/TikTok publishing.
- 이 항목들은 사용자 승인 또는 default branch 변경/실제 Windows 실행환경 등 외부 조건 없이는 수행할 수 없으므로 PASS로 표시하지 않았습니다.

## 5. 최종 산출물

- 통합 후보 PR: https://github.com/justinhblee-prog/shorts/pull/415
- 인수인계 문서: `docs/INTEGRATION_HANDOVER_2026-11-20.md`
- 멀티플로우 실행계획: `docs/MULTI_FLOW_EXECUTION.md`
- 상태 추적: `progress.md`
- 최종 hosted validation: [44647755797](https://github.com/justinhblee-prog/shorts/actions/runs/44647755797)
- 읽기 쉬운 데스크톱/모바일 화면 증거: [14589176582](https://github.com/justinhblee-prog/shorts/actions/runs/44646542482)



## 23. Default-branch activation dependency audit — 2026-11-20

- Rechecked repository default branch metadata: `main`.
- Confirmed `.github/workflows/nexus-development-job-worker.yml` is absent from `main` (GitHub Contents API returned 404 for that path).
- Confirmed the worker's executable prerequisites are also absent from `main`: `backend/run_development_agent.py`, `backend/development_agent_executor.py`, `backend/recover_development_reviews.py`, `backend/publish_development_reviews.py`, and `backend/tests/test_development_worker_workflow_contract.py`.
- `backend/requirements.txt` exists on `main`, but that alone is insufficient: the workflow's Python entrypoints and contract tests are not present there. Copying only the workflow file to `main` would create a broken activation and is explicitly not the next step.
- Required promotion unit must be dependency-complete and reviewed as one stack: worker workflow + worker/executor/backlog/intake/review-publication modules + seed/data contracts + tests + any required backend dependencies. Before proposing activation, compare every imported module and referenced path against `main`, then run the main-targeted CI suite on the promotion branch.
- No promotion PR, default-branch update, workflow dispatch, merge, or runner execution was performed. This is a verified activation dependency, not a claim that the Windows runner is offline.


## 24. Worker activation dependency closure — 2026-11-20

- 2차 import/call-site 감사를 수행해 누락 범위를 확장했습니다. `main`에는 `development_jobs.py`, `development_job_worker.py`, `development_github_intake.py`, `development_backlog_service.py`, `development_security.py`, `seed_development_jobs.py`, `development_agent_executor.py`, `publish_development_reviews.py`, `recover_development_reviews.py`, `run_development_agent.py` 및 worker workflow가 모두 없습니다.
- import 연결 확인: entrypoint → executor/backlog/intake/store/security/seed; executor → worker/security; backlog → worker/intake; worker → store/security; intake → store; store → security; seed → store; recovery → store/review publisher; review publisher → store.
- workflow contract test도 `main`에 없습니다. worker 전용 unit/regression tests, orchestration design contract, workflow path filters 및 validation script 연계까지 promotion closure에 포함해야 합니다. 테스트 파일명은 실제 branch tree와 CI discovery를 기준으로 확정합니다.
- `backend/requirements.txt`는 `main`에 이미 존재합니다. 현재 확인한 worker import는 표준 라이브러리와 기존 backend dependency set을 사용하므로 promotion 시 dependency diff를 재검토하고 불필요한 전체 requirements 교체를 피합니다.
- 보안 게이트: job-level contents/pull-requests/actions write 권한 최소화, read-only intake token과 PR publication token 분리, Windows runner 격리, LocalAppData 외부 저장, scope allowlist와 symlink 해석 검증, Aider child-process credential stripping, secrets/production data 경로 제외.
- 필수 runner: self-hosted Windows + `nexus-local-ai` label, Actions runner >= 2.327.1, Python >= 3.11, Git Bash, Node >= 18, loopback Ollama, 정확한 `qwen2.5-coder:7b` 모델. `NEXUS_GITHUB_READ_TOKEN`, `NEXUS_APPROVED_SCOPES`, repository GITHUB_TOKEN 권한도 별도 확인해야 합니다.
- Windows 실 runner 실행, LocalAppData 2회 실행 persistence, Ollama 생성 검증은 아직 수행되지 않았습니다. 승인 전 workflow dispatch/예약 활성화/merge/default branch 변경은 하지 않습니다.


## 25. Mainline worker promotion package boundary — 2026-11-20

- main...integration/nexus-aggregate-ui-core-2026-11-20 비교 결과 integration branch는 main보다 1,307 commits ahead / 5 behind이며 worker 외에 production pipeline, queue/scheduler, TikTok/YouTube, recommendation/metrics, frontend UI 등 광범위한 변경을 포함합니다. PR #415도 100 commits이며 base가 main이 아닌 integration branch입니다. 따라서 PR #415 전체를 Windows worker 활성화 목적으로 승격하지 않기로 결정했습니다.
- 별도 main 기반 승격 PR의 최소 runtime 파일 12개: worker workflow, development_agent_executor.py, development_backlog_service.py, development_github_intake.py, development_job_worker.py, development_jobs.py, development_security.py, publish_development_reviews.py, recover_development_reviews.py, run_development_agent.py, seed_development_jobs.py, sync_development_backlog.py.
- 함께 가져갈 worker 전용 테스트 12개: executor, scope normalization, backlog service, GitHub intake, job worker, jobs store, security, workflow contract, review publisher, run entrypoint, seed, backlog sync 테스트.
- API 전용 test_development_job_api_security.py와 test_development_job_recovery_api.py는 standalone CLI worker 필수 항목이 아닙니다. 추후 dashboard API를 승격한다면 backend/app.py, 권한 변경, 해당 API 테스트를 하나의 별도 단위로 검토합니다.
- 공통 검증 조정: backend/requirements.txt에 PyYAML>=6.0,<7.0 추가 필요. main의 scripts/validate.sh가 YAML 파서를 사용하지만 main requirements에는 PyYAML이 없습니다. backend-tests.yml push/PR path filter도 worker workflow 및 contract test가 요구하는 docs/README/.gitignore 변경을 검증하도록 갱신해야 합니다.
- scripts/validate.sh는 main에 이미 있으며 compileall + 전체 backend unittest discovery를 수행합니다. 새 main 기반 브랜치에서 이 명령과 frontend syntax/workflow contract 검증을 수행해야 합니다.
- 승격 제외: aggregate branch의 unrelated production pipeline, queue/scheduler, platform integrations, recommendation/metrics, frontend/dashboard, broad app.py changes.
- 현재 상태: 파일 경계/import graph AUDITED. main 기반 승격 브랜치와 CI는 미생성/미실행. Windows 실 runner, 2회 실행 persistence, Ollama 생성은 NOT VERIFIED. merge/dispatch/schedule/default branch 변경 없음.


## 26. Dedicated mainline promotion PR created — 2026-11-20

- Created branch `promotion/nexus-worker-mainline-2026-11-20` directly from `main` and isolated the worker package (28 changed files): 12 runtime/workflow files, 12 focused regression tests, 2 new docs plus existing operator runbook, PyYAML, and backend CI path filters.
- Created Draft PR #416: https://github.com/justinhblee-prog/shorts/pull/416 (base main; head `20d9f522184654a11a75214a9fba81c5adabb660`). No aggregate PR #415 base/head changes.
- Exact main-targeted Actions run: 44649765794 https://github.com/justinhblee-prog/shorts/actions/runs/44649765794. At documentation update time, dependency installation passed and `sh scripts/validate.sh` was running; final result pending.
- PR #416 is Draft/open/unmerged. No workflow dispatch, scheduled activation, secret change, merge, deployment, or default branch modification performed.


## 27. Isolated worker promotion CI result — 2026-11-20

- PR #416 main-based validation runs 44649765794 and 44649800067 completed successfully at exact tested head `20d9f522184654a11a75214a9fba81c5adabb660`. Dependency installation and `sh scripts/validate.sh` passed; the latter runs Python compileall, frontend syntax check where Node is available, and complete backend unittest discovery.
- Follow-up commit `13f9b1308a660e2a1799aba2c5aba39212008217` adds an explicit PyYAML parse step for `.github/workflows/nexus-development-job-worker.yml`. A new Actions run for that exact head has not yet been observed; do not label that last CI-only addition as tested.
- PR #416 remains Draft/open/unmerged; PR #415 remains Draft/open/unmerged. Windows runner, two-run LocalAppData persistence and live Ollama generation remain NOT VERIFIED.
