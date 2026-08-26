# Aincrad

고정된 세계 규칙 위에서 여러 자율 모험가의 판단·기억·협업을 관찰하는 한국어 우선 터미널 샌드박스입니다.

> **프로젝트 상태:** 첫 결정론적 프로토타입. 현재 이름은 작업명이며, 기존 상용 작품의 설정·캐릭터·자산을 복제하지 않는 독자 세계관을 지향합니다.

## 핵심 원칙

- **AI는 제안하고 엔진은 판정합니다.** 에이전트는 구조화된 행동만 제출합니다.
- **모든 상태 변경은 이벤트로 남습니다.** 원인과 결과를 재생하고 검증할 수 있습니다.
- **재현성을 우선합니다.** 같은 초기 상태·시드·행동열은 같은 결과를 만듭니다.
- **필수 검증은 오프라인입니다.** 외부 LLM이나 네트워크 없이 테스트할 수 있습니다.

## 첫 프로토타입 범위

- 자율 모험가 3명
- 마을 1개, 사냥터 1개, 3층 던전
- 이동, 휴식, 채집, 거래, 대기
- 작업·일화·사실·사회·전략 기억
- JSONL 이벤트 로그와 해시 체인 검증
- 날짜·시간별 한국어 터미널 관찰

## 설치

Python 3.11 이상과 [uv](https://docs.astral.sh/uv/)가 필요합니다.

```bash
uv sync --extra dev
```

## 실행

```bash
uv run aincrad simulate --seed 42 --days 7 --headless --output runs/demo
uv run aincrad replay runs/demo/events.jsonl --verify-hash
```

기존 이벤트 로그는 증거 보존을 위해 자동으로 덮어쓰지 않습니다. 같은 출력 경로를
의도적으로 교체할 때만 `simulate`에 `--force`를 추가하세요. `replay`는 기본적으로
스키마만 검사하며, 해시 체인 무결성까지 확인하려면 `--verify-hash`를 사용합니다.

구현 중인 CLI의 최신 옵션은 다음 명령으로 확인할 수 있습니다.

```bash
uv run aincrad --help
```

## 검증

```bash
uv run pytest
uv run ruff check .
uv run mypy src
```

## 구조

```text
src/aincrad/domain/       순수 도메인 모델과 규칙
src/aincrad/simulation/   시간과 행동 오케스트레이션
src/aincrad/agents/       관찰, 정책, 기억
src/aincrad/persistence/  이벤트 로그, 검증, 재생
src/aincrad/tui/          터미널 투영
content/                  독자 세계관 콘텐츠
fixtures/                 결정론적 테스트 입력
```

## 문서

- [아키텍처](docs/architecture.md)
- [ADR-0001: 결정론적 코어와 AI 정책 분리](docs/adr/0001-deterministic-core-and-agent-boundary.md)
- [기여 가이드](CONTRIBUTING.md)

## 라이선스

MIT
