# 기여 가이드

## 개발 환경

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run mypy src
```

## 원칙

- 기능은 실패하는 테스트를 먼저 작성하는 TDD로 개발합니다.
- AI 정책은 `Perception -> ActionIntent`만 수행하며 세계 상태를 직접 변경하지 않습니다.
- 상태 변경은 도메인 엔진과 추적 가능한 이벤트를 통해서만 일어납니다.
- 외부 모델 호출 없이 모든 필수 테스트를 실행할 수 있어야 합니다.
- 공개 세계관·명칭은 독자적인 표현을 사용합니다.
