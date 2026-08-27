# Aincrad Agent Guide

이 문서는 이 저장소에서 작업하는 모든 코딩 에이전트의 정본 지침입니다.
`CLAUDE.md` 같은 도구별 파일은 이 문서를 대체하지 않고 보충만 합니다.

## 프로젝트 개요

Aincrad는 고정된 세계 규칙 위에서 AI 모험가의 판단·기억·협업과 낯선 사회를 조사하고
사용자가 시간별 행동에 개입할 수 있는 Python 3.11+ 한국어 터미널
이세계 사회 시뮬레이터입니다. 현재 이름은 작업명입니다. 기존 상용 작품의 캐릭터, 고유 설정,
명칭, 자산을 복제하지 말고 독자 세계관 **The Glass Frontier**를 유지합니다.
공개 배포 전에 `Aincrad` 명칭과 부유성/층 구조의 IP·브랜딩을 별도로 검토합니다.

## 절대 경계

- AI/사용자는 `ActionIntent`만 선택합니다. 세계 상태와 결과는 규칙 엔진만 변경합니다.
- AI에는 `Perception`으로 관찰 가능한 정보만 제공합니다. 숨겨진 세계 상태를 전달하지 않습니다.
- 선택적 외부 AI는 이동 전 물리·사회 해설 projection만 만들며 합법 행동, 추천 순서,
  세계 상태, 이벤트, history, replay hash를 변경하지 않습니다.
- 인간 identity profile은 versioned run metadata이며 `WorldState`와 rules modifier가 아닙니다.
- 내부 chain-of-thought를 저장하거나 출력하지 않습니다. `reason_code`와 근거 이벤트를 사용합니다.
- 같은 초기 상태, 규칙 버전, seed, 행동열은 같은 이벤트 로그와 최종 상태를 만들어야 합니다.
- 외부 LLM·네트워크 없이 모든 필수 테스트와 replay가 동작해야 합니다.
- 일반 NPC는 LLM 에이전트가 아니라 결정론적 규칙 기반 서비스입니다.
- 상태 변경은 이벤트로 남기고 replay가 규칙 엔진 결과와 전체 payload를 검증해야 합니다.
- pickle, `eval`/`exec`, 임의 코드 실행, 실제 네트워크 호출을 코어에 추가하지 않습니다.
- 비밀값, 인증 정보, 개인 경로를 소스·fixture·로그·문서에 기록하지 않습니다.

## 시간·파티·성장 규칙

- 1 tick은 세계 시간 1시간입니다.
- 한 시간에는 현재 살아 있는 파티원 모두가 정확히 한 행동을 제출합니다.
- 모든 행동은 같은 tick에서 일괄 판정되고 세계 시계는 한 번만 증가합니다.
- 시작 화면에서 전사·궁수·마법사·탱커 중 주인공 한 명을 선택합니다.
- 라이브 파티는 주인공 한 명으로 시작하며 결정론적 사건으로 동료가 합류·이탈합니다.
- fixture의 모험가 3명은 콘텐츠 후보 데이터이며 라이브 시작 파티 3명을 뜻하지 않습니다.
- HP/MP는 항상 0과 최대치 사이입니다.
- EXP 곡선은 명시적이고 완만해야 하며 최대 레벨은 100입니다.
- 사망은 영구적입니다. 죽은 인물은 행동·회복·MP 소비·EXP 획득을 할 수 없습니다.
- 선택된 주인공이 사망하면 해당 회차의 이야기를 종료하고 `character_end`를 한 번 기록합니다.

## 세계관 정본

세계 ID는 `glassfrontier`, 제목은 **The Glass Frontier**입니다.
콘텐츠 정본은 `fixtures/glassfrontier_world.json`이며 loader/validator와 반드시 함께 변경합니다.

### Emberfall

따뜻한 shard spring 주변에 세워진 등불 마을입니다.

- `emberfall-shop` — **Cinderstock Exchange**: 장비·보급품 거래
- `emberfall-inn` — **The Quiet Wick**: HP/MP 회복과 보관
- `emberfall-quest-hall` — **Wayfinder Assembly**: 의뢰 등록·완료
- `emberfall-plaza` — **Prismwake Square**: 공지와 길 안내
- `emberfall-tavern` — **The Copper Comet**: 식사와 검증된 소문

각 시설에는 `controller="rules"`인 규칙 기반 NPC가 정확히 하나 있어야 합니다.

### Mossreach Wilds

비에 젖은 유리빛 구릉의 사냥터입니다. Emberfall과 Starless Vault 입구를 연결합니다.

### The Starless Vault

`vault-1`부터 `vault-10`까지 연속된 10단계 던전입니다.
`vault-10`은 **Chamber of the Null Cartographer** 보스방입니다.

- boss ID: `null-cartographer`
- transition ID: `aurora-lift-floor-2`
- 다음 월드 층: `2`

던전 단계, 연결, 보스방, 보상, 전이 ID를 바꿀 때 fixture, runtime scenario,
life-event catalog, validator, replay 테스트를 함께 갱신합니다.

## 코드 구조

- `src/aincrad/domain/` — 순수 모델, 행동 규칙, 성장·생명주기
- `src/aincrad/simulation/` — 시간 배치, runtime 사건, 초기 시나리오
- `src/aincrad/agents/` — 읽기 전용 perception, policy, memory
- `src/aincrad/content/` — fixture loader, NPC 서비스, life-event catalog
- `src/aincrad/persistence/` — canonical JSONL, SHA-256 체인, strict replay
- `src/aincrad/history/` — 시간·일·회차·인물 결말 append-only 기록
- `src/aincrad/tui/` — 제어문자를 무력화하는 80열 한국어 투영
- `fixtures/` — 독자 세계관의 결정론적 콘텐츠 정본
- `tests/` — unit, property, integration, replay, history, e2e 검증

의존 방향은 `domain`이 가장 안쪽입니다. `domain`에서 CLI, TUI, 네트워크,
모델 SDK를 import하지 않습니다.

## 이벤트·저장 규칙

- 이벤트 JSON은 canonical serialization을 사용합니다.
- JSONL은 연속 `seq`와 SHA-256 `prev_event_hash`/`event_hash` 체인을 유지합니다.
- 기존 이벤트 로그는 기본적으로 덮어쓰지 않습니다. 명시적 `--force`만 원자 교체합니다.
- replay는 저장된 intent와 사건을 규칙 엔진에 재적용하고 전체 event payload를 비교합니다.
- 동적 파티 replay는 시간별 정확한 파티 행동 집합과 합류·이탈을 재구성해야 합니다.
- 히스토리는 symlink/path escape를 거부하고 canonical JSON, 영구 monotonic 회차 번호,
  엄격한 hourly/daily_summary/character_end schema를 유지합니다.
- 손상, 누락, 순서 오류를 조용히 건너뛰거나 자동 복구하지 않습니다.
- 터미널에 표시되는 모든 외부/저장 문자열은 제어문자를 무력화해야 합니다.

## 개발 절차

1. 관련 정의와 모든 사용처를 먼저 읽습니다.
2. 실패하는 테스트를 먼저 작성하고 RED를 실제로 확인합니다.
3. 최소 구현으로 GREEN을 확인합니다.
4. 변경 범위의 테스트 후 전체 품질 게이트를 실행합니다.
5. 독립 fail-closed 리뷰가 통과하기 전에는 완료·안전·푸시를 주장하지 않습니다.

필수 명령:

```bash
uv sync --extra dev --locked
uv run pytest -q
uv run ruff check .
uv run mypy src
uv lock --check
git diff --check
uv build
```

CLI 또는 저장 계약을 바꾸면 실제 `simulate -> events.jsonl -> replay --verify-hash`와
`history list/show` 스모크 테스트를 추가로 실행합니다.

## 커밋 규칙

- 기능·책임별 작은 논리 커밋을 만듭니다. 큰 혼합 커밋을 만들지 않습니다.
- Conventional Commit 형식을 사용합니다: `feat:`, `fix:`, `test:`, `docs:`, `refactor:`, `chore:`.
- 한 커밋에는 하나의 설명 가능한 목적과 그 목적을 검증하는 테스트를 함께 넣습니다.
- schema와 이를 소비하는 코드처럼 단독으로 깨지는 변경은 같은 커밋에 묶습니다.
- 관련 없는 포맷팅, rename, drive-by refactor를 섞지 않습니다.
- 생성물 `build/`, `dist/`, `*.egg-info`, 실행 로그, 로컬 히스토리를 커밋하지 않습니다.
- 비밀값이나 `.env`를 커밋하지 않습니다.
- 사용자가 요청하지 않은 amend, rebase, force-push, history rewrite를 하지 않습니다.
- 이 개인 테스트 단계에서는 로컬 전체 테스트·Ruff·mypy·diff check와 독립 리뷰가
  통과한 논리 커밋을 `main`에 직접 푸시할 수 있습니다.
- 원격 CI는 `main` 푸시 뒤의 사후 검증입니다. 성공을 확인하기 전에는 전달 완료를
  주장하지 않으며, 실패하면 추가 푸시를 멈추고 원인을 수정·재검증합니다.

권장 분리 예시:

1. `feat(content): expand Glass Frontier locations and events`
2. `feat(domain): add character progression and party lifecycle`
3. `feat(simulation): add hourly party runtime and strict replay`
4. `feat(history): persist secure playthrough timelines`
5. `docs: add project and agent guidance`

## 문서 동기화

행동, CLI 옵션, 세계관 ID, 저장 schema, 검증 명령이 바뀌면 같은 작업에서
`README.md`, `docs/architecture.md`, fixture, 테스트, 이 문서를 확인합니다.
문서에는 구현되지 않은 기능을 현재 기능처럼 쓰지 않습니다.
