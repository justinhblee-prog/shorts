# NEXUS STUDIO PRO — 개발·검증·릴리스 인수인계

- 문서 버전: v0.1
- 기준일: 2026-11-20 (KST)
- 저장소: https://github.com/justinhblee-prog/shorts
- 기준 작업 기준선: `integration/flow-status-and-ownership-2026-11-20`
- 문서 브랜치: `docs/nexus-project-handover-2026-11-20`

## 1. 개발 환경과 실행

### 권장 로컬 실행

저장소 루트에서:

```bash
cp .env.example .env
# .env에 실제 비밀값을 직접 입력하고 절대 커밋하지 않습니다.
docker compose build
docker compose up -d
docker compose ps
```

대시보드 기본 주소: `http://localhost:8502/`

헬스 확인:
```bash
curl -fsS http://localhost:8502/api/health
```

검증:
```bash
sh scripts/validate.sh
node --check frontend/app.js
```

실제 Compose 서비스명, 환경변수, provider 계약은 `compose.yaml`, `.env.example`, `backend/README.md`를 기준으로 확인합니다. 이 인수인계 문서에 예시로 적힌 실행만으로 외부 공급자 연결이나 운영 환경 검증이 완료되는 것은 아닙니다.

### 필수 보안 주의
- `.env`, OAuth token, API key, review token, encryption key를 Git에 올리지 않습니다.
- 개인별 API credential 사용 시 role map을 명시하고 최소 권한으로 설정합니다.
- production 데이터베이스·OAuth·플랫폼 계정에 접근하기 전 승인된 환경인지 확인합니다.
- 복원 명령은 대상 경로와 사전 백업을 확인한 뒤 명시적으로 승인합니다.

## 2. 저장소 주요 경로

| 경로 | 책임 |
|---|---|
| `frontend/index.html` | 대시보드 화면 구조 |
| `frontend/app.js` | API 연동 및 UI 동작 |
| `frontend/cyber-magic*.css` | 대시보드 스타일·반응형 |
| `backend/app.py` | FastAPI app 및 endpoint |
| `backend/*.py` | 도메인 서비스, queue, worker, scheduler, providers, policy |
| `backend/tests/` | Backend 회귀·계약 테스트 |
| `scripts/validate.sh` | 기본 저장소 검증 |
| `scripts/ui_browser_smoke.mjs` | Playwright Chromium UI smoke |
| `compose.yaml` | 컨테이너 서비스 구성 |
| `docs/WORKSTREAMS.md` | lane ownership 및 PR 의존성 |
| `docs/DEVELOPMENT_JOB_ORCHESTRATION.md` | 작업 상태·병렬 실행 규칙 |
| `docs/BUILD_STATUS.md`, `docs/HANDOVER.md` | Core 구현 이력과 기술 핸드오버 |

## 3. 멀티 Flow 개발 운영

### Workstream 소유권
- **UI:** `frontend/**`, UI 테스트, UI 문서.
- **Core:** `backend/**`, DB schema/migration, worker/scheduler/provider runtime.
- **Policy:** policy engine 및 승인·정책 테스트.
- **QA:** 독립 diff/CI/로그 검토. 수정은 해당 소유 lane과 조정.
- **Integration:** API 계약, 교차 계층 테스트, release readiness.

### 실행 규칙
1. 독립 파일·모듈은 병렬 작업으로 진행할 수 있습니다.
2. 동일 branch 또는 동일 파일 쓰기는 직렬화합니다.
3. stacked PR은 base → child 순서를 보존하고 child를 단독 병합하지 않습니다.
4. API 계약이 없으면 UI mock success를 만들지 않고 Core 계약 작업을 등록합니다.
5. 다음 작업은 dependency graph의 선행 조건을 만족하는 가장 중요한 미완료 항목에서 선택합니다.
6. 심각한 보안·비용·데이터 손실·외부 계약 이슈가 아니면 사소한 장애로 전체 Flow를 멈추지 않습니다.
7. 사용자가 승인하지 않은 PR 병합, 배포, 공개 게시, 실제 과금은 수행하지 않습니다.

### 완료 게이트
- [ ] 실제 diff가 작업에서 선언한 파일 범위와 일치
- [ ] 변경 경로가 허용된 scope 안에 있음
- [ ] 집중 회귀 테스트 통과
- [ ] `scripts/validate.sh` 통과
- [ ] UI 변경이면 frontend syntax 및 관련 브라우저 smoke 통과
- [ ] 최신 정확한 PR head에 대한 CI 결과 통과
- [ ] 보안·데이터 무결성·하위 호환성 diff review 완료
- [ ] 문서에 commit, PR, 테스트, CI URL, 한계, 후속 의존성 기록
- [ ] 사람의 검토 전 Draft 상태 유지

## 4. 현재 UI 스택과 상태 (2026-11-20)

| PR | 작업 | 의존성 | 상태 |
|---|---|---|---|
| #392 | UI-00013 cinematic dashboard foundation | UI 기반 | Draft, unmerged |
| #394 | UI-00014 professional design system | #392 | Draft, unmerged |
| #395 | UI-00015 analytics history pagination | #394 | Draft, unmerged |

### UI-00015 세부
- PR: https://github.com/justinhblee-prog/shorts/pull/395
- Branch: `ui/ui-00015-analytics-history-pagination`
- 최신 head: `6afe85c0e31cb0a478fe1159c10d303f75800535`
- 변경: analytics history 테이블을 25행씩 페이지네이션. 기존 최대 200행 표시 상한 유지. 차트/전체 데이터 집계와 cursor 기반 CSV 전체 내보내기는 독립 유지.
- 추가 브라우저 테스트: 25행 렌더링, 1→2→1 이동, 첫 페이지 이전 버튼 비활성, 320px 모바일 pagination 가로 범위 및 이동, 전체 502행 CSV 다운로드.

### 최신 검증 근거
- 정확한 최신 head에서 `scripts/validate.sh` 통과 기록이 PR 설명에 반영되어 있음.
- Compose build, service startup/readiness, scheduled backup, isolated restore: run [44568430260](https://github.com/justinhblee-prog/shorts/actions/runs/44568430260) 통과.
- Browser run [44568430230](https://github.com/justinhblee-prog/shorts/actions/runs/44568430230): 확인 당시 job `135716506349`의 Korean font fallback 설치 단계가 in_progress였고 Playwright 설치·Chromium 설치·browser smoke·artifact upload는 pending. 따라서 최신 head의 browser/mobile 결과는 미확인.
- 이전 head에서 desktop smoke/CSV 성공 및 스크린샷 생성 기록이 있지만, 이를 최신 head의 검증 증거로 간주하지 않습니다.
- 최신 browser run이 종료되면 job status/logs와 artifact를 확인하고, mobile 320px 화면을 직접 열어 검토해야 합니다.
- PR #395는 #394에 스택되어 있으므로 Draft 유지. #394와 독립적으로 merge하지 않습니다.

## 5. 다음 우선 작업

1. UI-00015 run 44568430230 재확인. 장시간 font install이면 job log를 확인하고 CI 병목을 수정하되, 브라우저 검증을 생략한 채 성공 처리하지 않습니다.
2. 성공 시 artifact를 내려받아 데스크톱·모바일 이미지를 검토하고 PR 설명 및 WORKSTREAMS/Orchestration 문서를 정확히 갱신합니다.
3. 실패 시 실제 실패 단계와 로그를 근거로 수정하고 새 head에서 전체 검증을 반복합니다.
4. UI stack 이후 Core/Policy stack의 dependency와 정확한 head CI를 다시 대조합니다.
5. Integration lane에서 API 계약·권한·migration·browser workflow의 교차 계층 검증을 진행합니다.
6. 실제 공급자 생성, OAuth, YouTube/TikTok 게시, Windows self-hosted worker, 운영 DB migration, 오프사이트 복원은 별도 실환경 gate로 남깁니다.

## 6. 검증 분류

| 분류 | 의미 | 완료 판정 |
|---|---|---|
| Static/source | 정적 검사, syntax, source assertion | 코드 구조만 확인 |
| Unit/contract | fixture/mock 기반 자동 테스트 | 애플리케이션 로직 확인 |
| Compose integration | 실제 컨테이너 build/start/readiness/backup/restore 테스트 | 해당 CI 환경의 통합 동작 확인 |
| Browser smoke | Chromium에서 실제 UI 상호작용·viewport 확인 | 테스트한 화면·head 범위만 확인 |
| External live | 실제 OAuth/provider/platform API/계정 실행 | 해당 계정·권한·환경에서만 확인 |
| Production operations | 운영 트래픽·백업 복구·장애 대응·비용 확인 | 실제 운영 증거 필요 |

CI 통과는 live provider 성공, 실제 수익, 게시 정책 승인, 운영 준비 완료를 의미하지 않습니다.

## 7. 문서 업데이트 규칙

각 개발 작업이 종료되거나 상태가 바뀌면 다음을 업데이트합니다.
- `docs/WORKSTREAMS.md`: lane 상태, PR 번호, base/head, 의존성
- `docs/DEVELOPMENT_JOB_ORCHESTRATION.md`: Flow graph, 완료/차단 gate
- `docs/BUILD_STATUS.md` 또는 `docs/HANDOVER.md`: Core 구현 및 검증 근거
- `docs/PRODUCT_AND_REQUIREMENTS.md`: 제품 범위/요구사항 변경 시
- `docs/SYSTEM_ARCHITECTURE.md`: 구조/API/DB/UI/보안 변경 시
- `docs/PROJECT_HANDOVER_INDEX.md`: 새 문서 및 최신 기준선 반영

모든 업데이트는 기존 내용을 무조건 덮어쓰지 말고, 현재 상태와 과거 기록을 구분합니다. PR/commit/run URL과 정확한 SHA를 기록합니다. 아직 확인하지 못한 결과는 “대기”, “미확인”, “차단”으로 명시합니다.

## 변경 이력

- 2026-11-20: 최초 작성. 현재 PR #395 및 run 44568430230/44568430260 상태를 기준으로 작성.
