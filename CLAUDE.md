# Claude Code Instructions

작업을 시작하기 전에 저장소 루트의 [`AGENTS.md`](AGENTS.md)를 전부 읽고 따릅니다.
`AGENTS.md`가 프로젝트·세계관·아키텍처·검증·커밋 규칙의 정본입니다.
이 파일과 충돌하면 `AGENTS.md`를 우선합니다.

## Claude 전용 작업 규칙

- 계획을 장황하게 설명하기보다 관련 정의와 사용처를 먼저 조사합니다.
- 구현 전에 실패 테스트를 작성하고 실제 RED를 확인합니다.
- AI가 세계 상태를 직접 바꾸는 코드를 만들지 않습니다.
- fixture, runtime scenario, life-event catalog의 ID를 추측하지 말고 정본 파일에서 확인합니다.
- 내부 추론이나 chain-of-thought를 코드·로그·히스토리에 저장하지 않습니다.
- 변경은 기능별 작은 Conventional Commit으로 분리합니다.
- 커밋 전에 `AGENTS.md`의 전체 검증 명령을 실행합니다.
- 로컬 독립 리뷰가 통과하기 전에는 푸시하지 않습니다. 원격 CI는 푸시 후 확인하며,
  성공 전에는 전달 완료를 주장하지 않습니다.
- 사용자가 명시적으로 요청하지 않으면 amend, rebase, force-push를 하지 않습니다.

## 빠른 시작

```bash
uv sync --extra dev --locked
uv run pytest -q
uv run ruff check .
uv run mypy src
```

대화형 확인:

```bash
uv run aincrad simulate --seed 42 --hours 1 --history-root runs/history
uv run aincrad history list --history-root runs/history
```
