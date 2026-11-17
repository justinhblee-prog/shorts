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
5. runner 등록 시 추가 라벨 `nexus-local-ai`를 지정하고, 저장소 전용의 제한된 계정/폴더에서 서비스로 실행합니다.
6. runner PC에서 Ollama가 로컬로 접근 가능한지 확인합니다: `ollama list`

## 실행 및 안전
- 워크플로: `.github/workflows/nexus-continuous-codex.yml`
- 수동 실행은 Actions 탭에서 `NEXUS STUDIO PRO local-model iteration` → Run workflow.
- 2시간 주기 예약은 워크플로 파일이 기본 브랜치에 반영된 뒤에만 작동합니다.
- 결과는 Draft PR로만 생성하며 자동 병합하지 않습니다.
- 외부 배포, 실제 SNS 게시, OAuth, 유료 서비스 호출은 금지합니다.
- 처음에는 수동 실행 1회로 모델/runner/권한을 확인한 뒤 예약 실행을 켜십시오.

## 주의
Self-hosted runner는 저장소 코드와 workflow가 PC에서 명령을 실행할 수 있게 합니다. 신뢰할 수 없는 PR의 workflow를 실행하지 말고, 전용 OS 계정과 작업 폴더를 사용하십시오. 무료 모델은 상용 코딩 에이전트보다 성능이 낮을 수 있으므로 모든 Draft PR을 사람이 검토해야 합니다.
