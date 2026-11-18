# NEXUS STUDIO PRO — 무료 로컬 AI 개발 실행기

## 비용 정책
- OpenAI API, Codex API, 기타 유료 추론 API 키를 사용하지 않습니다.
- 모델 추론은 소유자가 직접 관리하는 PC의 Ollama에서 수행합니다.
- GitHub Actions의 호스팅 러너가 아니라 `nexus-local-ai` 라벨의 self-hosted runner가 필요합니다.
- PC 전원과 네트워크가 켜져 있고 GitHub runner 서비스가 실행 중일 때만 작업합니다. PC가 꺼져 있으면 예약 실행은 대기/실패할 수 있습니다.
- Ollama 모델 다운로드와 PC 전력/하드웨어 비용은 별도일 수 있습니다.

## 준비 환경 (Windows 예시)
1. Ollama를 설치하고 터미널에서 실행합니다.
2. 모델을 내려받습니다: `ollama pull qwen2.5-coder:7b`
3. 모델 응답 확인: `ollama run qwen2.5-coder:7b`
4. GitHub 저장소의 Settings → Actions → Runners → New self-hosted runner에서 Windows x64 안내에 따라 runner를 설치합니다.
5. runner 등록 시 추가 라벨 `nexus-local-ai`를 지정합니다.
6. GitHub runner 서비스는 Ollama가 설치·실행되는 것과 **동일한 Windows 사용자 계정**으로 실행합니다. 다른 계정(예: LocalSystem)으로 서비스를 실행하면 사용자 세션의 Ollama 프로세스와 PATH를 보지 못할 수 있습니다.
7. runner 서비스 계정에서 `ollama list`와 `Invoke-RestMethod http://127.0.0.1:11434/api/tags`가 모두 성공하는지 확인합니다. Ollama 포트 11434를 외부 네트워크에 공개하지 마십시오.
8. development-job worker는 SQLite 상태를 `%LOCALAPPDATA%\NexusStudioPro\shorts\development.sqlite3`에, PR 게시 재시도용 소스 스냅샷을 `%LOCALAPPDATA%\NexusStudioPro\shorts\artifacts`에 보관합니다. 두 폴더를 runner 정리 작업으로 삭제하지 마십시오. 현재 설계는 하나의 신뢰된 Windows runner 계정을 전제로 합니다.
9. PR 생성이 실패한 경우 다음 실행에서 저장된 스냅샷을 복구합니다. 원본 파일 해시가 바뀌었거나 아카이브가 손상되면 파일을 덮어쓰지 않고 작업을 중단합니다.

## 실행 및 안전
- 기본 로컬 모델 반복 워크플로: `.github/workflows/nexus-continuous-codex.yml` (`NEXUS STUDIO PRO local-model iteration`).
- 의존성 기반 개발 작업 워커: `.github/workflows/nexus-development-job-worker.yml` (`NEXUS development job worker`). 두 워크플로 모두 기본 브랜치에 반영된 뒤에만 예약 실행됩니다.
- 수동 실행은 Actions 탭에서 해당 워크플로를 선택하고 Run workflow를 누릅니다.
- 2시간 주기 예약은 워크플로 파일이 기본 브랜치에 반영된 뒤에만 작동합니다.
- 결과는 Draft PR로만 생성하며 자동 병합하지 않습니다. 작업 상태는 PR URL과 정확한 PR head SHA가 기록되기 전까지 `review_pending`으로 유지됩니다.
- 외부 배포, 실제 SNS 게시, OAuth, 유료 서비스 호출은 금지합니다.
- 처음에는 수동 실행 1회로 모델/runner/권한을 확인한 뒤 예약 실행을 켜십시오.

## 주의
Self-hosted runner는 저장소 코드와 workflow가 PC에서 명령을 실행할 수 있게 합니다. 신뢰할 수 없는 PR의 workflow를 실행하지 말고, 전용 OS 계정과 작업 폴더를 사용하십시오. 무료 모델은 상용 코딩 에이전트보다 성능이 낮을 수 있으므로 모든 Draft PR을 사람이 검토해야 합니다.
