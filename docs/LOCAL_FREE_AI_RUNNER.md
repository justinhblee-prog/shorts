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
4. Python **3.11 이상**, Node.js **18 이상**, Git for Windows(Git Bash 포함)를 설치합니다. workflow는 `scripts/validate.sh` 실행을 위해 `bash.exe` 또는 `sh.exe`를 찾습니다.
5. GitHub 저장소의 Settings → Actions → Runners → New self-hosted runner에서 Windows x64 안내에 따라 runner를 설치합니다.
6. runner 등록 시 추가 라벨 `nexus-local-ai`를 지정합니다.
7. GitHub runner 서비스는 Ollama가 설치·실행되는 것과 **동일한 Windows 사용자 계정**으로 실행합니다. 다른 계정(예: LocalSystem)으로 서비스를 실행하면 사용자 세션의 Ollama 프로세스와 PATH를 보지 못할 수 있습니다.
8. runner 서비스 계정에서 `ollama list`와 `Invoke-RestMethod http://127.0.0.1:11434/api/tags`가 모두 성공하는지 확인합니다. workflow는 `qwen2.5-coder:7b` 태그를 정확히 확인합니다. Ollama 포트 11434를 외부 네트워크에 공개하지 마십시오.
9. development-job worker는 SQLite 상태를 `%LOCALAPPDATA%\NexusStudioPro\shorts\development.sqlite3`에 보관합니다. 이 폴더를 runner 정리 작업으로 삭제하지 마십시오. 현재 설계는 하나의 신뢰된 Windows runner 계정을 전제로 합니다.

### Python 패키지 격리
- 각 workflow 실행은 checkout workspace 안에 임시 `.nexus-backend-venv`와 `.nexus-aider-venv`를 별도로 생성합니다.
- Backend requirements와 Aider를 서로 다른 가상환경에 설치해 의존성 충돌을 줄이고 PC의 전역 Python/사용자 패키지를 변경하지 않습니다.
- 이 두 가상환경은 매 실행 때 새로 만들어지며 checkout 정리 대상입니다. `.gitignore`에 등록되어 worker의 clean-worktree 검사에 나타나지 않습니다. 영속 개발 잡 DB는 별도로 LocalAppData에 남습니다.
- 사전 점검에서 Python 3.11+, Git Bash/sh, Node.js 18+, Ollama API 및 정확한 모델 태그를 확인합니다.

## 실행 및 안전
- 기본 로컬 모델 반복 워크플로: `.github/workflows/nexus-continuous-codex.yml` (`NEXUS STUDIO PRO local-model iteration`).
- 의존성 기반 개발 작업 워커: `.github/workflows/nexus-development-job-worker.yml` (`NEXUS development job worker`). 두 워크플로 모두 기본 브랜치에 반영된 뒤에만 예약 실행됩니다.
- 수동 실행은 Actions 탭에서 해당 워크플로를 선택하고 Run workflow를 누릅니다.
- 2시간 주기 예약은 워크플로 파일이 기본 브랜치에 반영된 뒤에만 작동합니다.
- 결과는 Draft PR로만 생성하며 자동 병합하지 않습니다.
- 외부 배포, 실제 SNS 게시, OAuth, 유료 서비스 호출은 금지합니다.
- 처음에는 수동 실행 1회로 모델/runner/권한을 확인한 뒤 예약 실행을 켜십시오.

## 주의
Self-hosted runner는 저장소 코드와 workflow가 PC에서 명령을 실행할 수 있게 합니다. 신뢰할 수 없는 PR의 workflow를 실행하지 말고, 전용 OS 계정과 작업 폴더를 사용하십시오. 무료 모델은 상용 코딩 에이전트보다 성능이 낮을 수 있으므로 모든 Draft PR을 사람이 검토해야 합니다.


## 개발 잡 완료 판정 (BUILD-00317)
- 모델 변경과 로컬 검증이 끝나도 개발 잡은 즉시 completed가 되지 않고 review_pending 상태로 남습니다.
- Draft PR 생성 후 별도 검증 단계가 GitHub API에서 PR 상태, Draft 여부, head/base 브랜치, 정확한 head SHA와 변경 파일 목록을 읽어 확인합니다.
- 검증된 PR URL과 head SHA가 영속 DB에 기록된 경우에만 개발 잡이 completed가 되고 종속 작업이 풀립니다.
- PR 생성 또는 검증이 실패하면 review_pending 상태를 유지합니다. CI 성공이나 실제 Windows/Ollama 실행으로 간주하지 않습니다.


### Windows runner 사전 점검 (BUILD-00320)
- 개발 모드에서는 Python 3.11+, Git Bash 또는 POSIX sh, Node.js 18+, Ollama API 응답, `qwen2.5-coder:7b` 정확한 태그를 먼저 검사합니다.
- 도구가 누락되면 AI 작업을 시작하기 전에 명확한 오류로 중단합니다.
- Aider 실행 경로는 `NEXUS_AIDER_EXECUTABLE`로 전달하며, backend 가상환경의 Python과 혼합하지 않습니다.
