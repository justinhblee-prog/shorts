"""Idempotent initial engineering-job graph for the NEXUS development control plane."""

from development_jobs import DevelopmentJobStore


DEVELOPMENT_JOBS = (
    {
        "id": "DEV-ORCH-005",
        "title": "실제 Git diff와 검증 증거 기반 완료 판정 강화",
        "description": "Worker가 전달한 변경 파일 목록을 신뢰하지 않고 Git worktree의 실제 diff, 테스트 실행 결과, CI 증거를 확인한 뒤 완료 처리합니다.",
        "priority": 50,
        "scope": ["backend/development_jobs.py", "backend/development_job_worker.py"],
        "acceptance": [
            "changed_files exactly matches git diff and tracked/untracked files",
            "test command exit code is zero and evidence reference is recorded",
            "no-op and test-only runs cannot complete a job",
        ],
        "source_ref": "docs/DEVELOPMENT_JOB_ORCHESTRATION.md#safety-and-truthfulness-gates",
        "dependencies": [],
    },
    {
        "id": "DEV-ORCH-007",
        "title": "GitHub 이슈·PR·Actions 읽기 전용 백로그 동기화",
        "description": "열린 이슈, Draft PR, Actions 실행을 읽기 전용으로 수집하고 중복·의존성을 식별해 개발 잡으로 정규화합니다.",
        "priority": 60,
        "scope": ["backend/development_github_intake.py", "backend/tests/test_development_github_intake.py"],
        "acceptance": [
            "GitHub data is read-only and least-privilege",
            "pull requests are not counted as issues or completed product jobs",
            "source references and deduplication keys are persisted",
        ],
        "source_ref": "docs/DEVELOPMENT_JOB_ORCHESTRATION.md#product-backlog-intake",
        "dependencies": [],
    },
    {
        "id": "DEV-ORCH-009",
        "title": "기본 브랜치 예약 실행 및 Draft PR 자동 발행",
        "description": "기본 브랜치에서만 스케줄이 작동하도록 워크플로를 연결하고, 실행 가능한 잡을 worker에 배정해 실제 변경이 있을 때만 Draft PR을 생성합니다.",
        "priority": 70,
        "scope": [".github/workflows/nexus-development-job-worker.yml", "backend/run_development_agent.py", "backend/development_backlog_service.py"],
        "acceptance": [
            "scheduled workflow is present on the default branch before claiming background continuation",
            "trusted runner and local Ollama model are verified",
            "only meaningful tested diffs produce Draft PRs; never auto-merge",
        ],
        "source_ref": "docs/DEVELOPMENT_JOB_ORCHESTRATION.md#next-implementation-step",
        "dependencies": ["DEV-ORCH-005", "DEV-ORCH-007"],
    },
    {
        "id": "DEV-ORCH-010",
        "title": "실제 Ollama Worker 연속 실행 종단 검증",
        "description": "실제 runner에서 잡 등록부터 claim, 실행, heartbeat, 테스트, Draft PR, 다음 잡 해제까지 한 사이클을 증거로 검증합니다.",
        "priority": 80,
        "scope": [".github/workflows/nexus-development-job-worker.yml", "backend/development_job_worker.py"],
        "acceptance": [
            "a real product-source diff is created by the configured local model",
            "regression tests pass and the Draft PR is created",
            "a dependent next job becomes ready without chat input",
            "no secrets, paid model APIs, or automatic merges are used",
        ],
        "source_ref": "docs/DEVELOPMENT_JOB_ORCHESTRATION.md#safety-and-truthfulness-gates",
        "dependencies": ["DEV-ORCH-009"],
    },
)


def seed_development_jobs(store: DevelopmentJobStore):
    """Insert missing stable job IDs and dependency edges without overwriting progress."""
    for definition in DEVELOPMENT_JOBS:
        if store.get(definition["id"]) is None:
            store.create(
                title=definition["title"],
                description=definition["description"],
                priority=definition["priority"],
                scope=definition["scope"],
                acceptance=definition["acceptance"],
                source_ref=definition["source_ref"],
                job_id=definition["id"],
            )
    for definition in DEVELOPMENT_JOBS:
        for dependency_id in definition["dependencies"]:
            store.add_dependency(definition["id"], dependency_id)
    return [store.get(definition["id"]) for definition in DEVELOPMENT_JOBS]
