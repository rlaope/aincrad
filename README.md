# Aincrad

고정된 세계 규칙 위에서 AI 모험가의 판단·기억·협업과 낯선 사회를 조사하는
한국어 우선 이세계 사회 시뮬레이터입니다.

> **프로젝트 상태:** 첫 결정론적 프로토타입. 현재 이름은 작업명이며, 기존 상용 작품의 설정·캐릭터·자산을 복제하지 않는 독자 세계관을 지향합니다.

## 핵심 원칙

- **AI는 제안하고 엔진은 판정합니다.** 에이전트는 구조화된 행동만 제출합니다.
- **모든 상태 변경은 이벤트로 남습니다.** 원인과 결과를 재생하고 검증할 수 있습니다.
- **재현성을 우선합니다.** 같은 초기 상태·시드·행동열은 같은 결과를 만듭니다.
- **필수 검증은 오프라인입니다.** 외부 LLM이나 네트워크 없이 테스트할 수 있습니다.

## 첫 프로토타입 범위

- 시작 시 전사·궁수·마법사·탱커 중 주인공 1명 선택
- 주인공 표시 이름은 사용자가 정하며 replay용 내부 ID `hero`와 분리
- 탐구 성향·위험 태도·핵심 가치·관계 성향을 선택해 회차별 조사 관점을 구성
- 파티는 주인공 1명으로 시작하며 동료 합류·이탈 이벤트 계약 지원
- 마을 1개와 내부 시설 5종, 사냥터 1개, 10단계 던전과 보스방
- 매시간 사용자는 주인공만 조작하고 동료는 자신의 관찰 정보로 행동한 뒤 일괄 판정
- 행동 화면의 마지막 항목에서 `AI 판단에 맡기기` 지원
- 지역·시설·던전 이름은 플레이 화면에서 자연스러운 한국어 표시명으로 제공
- 이동은 물리적 조건과 사회적 의미가 설명된 추천 최대 3곳과 `기타 목적지`로 압축
- 홈의 `해설 AI`에서 오프라인 규칙 해설이나 사용자 인증 Hermes/Kimi를 선택
- 한 시간 판정 뒤 각 인물의 실제 행동·장소·피해·회복·성장을 사건 기반 서사로 표시
- 중앙 Story Director가 관찰 가능한 환경에서 퀘스트·영입·이탈 proposal을 제안
- 이동, 휴식, 채집, 거래, 대기
- 작업·일화·사실·사회·전략 기억
- JSONL 이벤트 로그와 해시 체인 검증
- 날짜·시간별 한국어 터미널 관찰
- HP/MP, 완만한 EXP 곡선, 최대 100레벨, 영구 사망 모델
- 시간별·일별·회차별 append-only 히스토리 저장과 조회

일반 NPC의 자율 일정·관계·대화는 아직 구현 범위가 아닙니다. 다음 단계에서는 AI Town과
Generative Agents에서 검증된 사회 구조를 wall-clock·비결정적 runtime째 옮기지 않고,
현재의 한 시간 batch와 strict replay 위에 규칙 기반 주민 사회로 구현합니다. 조사 결과는
[`docs/research/ai-town-reverse-engineering.md`](docs/research/ai-town-reverse-engineering.md),
채택한 방향과 단계별 gate는
[`ADR-0003`](docs/adr/0003-deterministic-otherworld-social-simulation.md)에 있습니다.

## 설치

Python 3.11 이상과 [uv](https://docs.astral.sh/uv/)가 필요합니다.

```bash
# 저장소 루트에서 한 번만 실행
uv tool install --editable .
```

개발 환경과 검증 도구까지 설치하려면 별도로 `uv sync --extra dev --locked`를
실행합니다.

## 실행

```bash
# 기본 TUI: 방향키 또는 W/S로 이동하고 Enter로 선택
aincrad
```

`aincrad`를 입력하면 Textual이 관리하는 full-screen 홈 화면이 열립니다. `새 모험`을
선택하면 직업·표시 이름과 네 가지 인간 정체성 관점을 정한 뒤 주인공의 시간별 행동을
고릅니다. TUI는 실제
터미널 폭에 맞춘 단일 패널 안에서 선택 항목과 한국어 지역명, 시간·HP/MP·레벨·파티
상태를 표시합니다. 선택 뒤에는 살아 있는 파티원 전원의 행동을 먼저 일괄 판정하고
이벤트와 히스토리를 기록한 다음, 누가 무엇을 했고 어떤 결과가 났는지 한 시간의 장면으로
보여줍니다. 이 장면을 읽은 뒤 다음 시간을 진행하거나 저장하고 홈으로 돌아갈 수 있습니다.
이동 화면은 결정론적으로 추천한 목적지 최대 세 곳과 전체 합법 경로를 여는 `기타 목적지`만
표시합니다. 각 목적지는 현재 장소와 HP/MP에 근거한 물리적 조건과, 선택한 정체성에 따른
사회 조사 관점을 함께 설명합니다. 홈의 `해설 AI`에서 `Kimi ultrafast`를 선택하면 설치된
Hermes의 기존 인증을 사용해 설명만 보강합니다. 실행 파일 부재, 인증 실패, timeout,
과대·비정상 응답은 즉시 로컬 규칙 해설로 대체되며 세계 판정과 replay에는 영향을 주지 않습니다.
`AI 판단에 맡기기`는 현재 HP·MP·위치·자원·갈 수 있는 길만 비교하는 결정론적 baseline
policy에 주인공의 이번 행동 선택을 위임합니다. `히스토리`에서는 같은 키보드 화면으로 회차 목록과 상세 기록을
조회합니다. 기본 히스토리는 `runs/history`, 홈에서 생성한 replay 로그는
`runs/playthroughs`에 회차별로 보존됩니다. 인자 없는 실행은 TTY가 필요하며, 파이프나
자동화 환경에서는 숫자 prompt로 전환하지 않고 `simulate --headless` 사용법을 안내합니다.

자동 실행·재생·경로 지정이 필요하면 하위 명령을 사용합니다.

```bash
# 이름과 직업을 지정해 한 시간 자동 실행 + 1회차 저장
aincrad simulate --seed 42 --hours 1 --headless --class warrior \
  --hero-name 한별 --history-root runs/history

# 회차 목록과 상세 페이지
aincrad history list --history-root runs/history
aincrad history show 1 --history-root runs/history

# AI 정책으로 7일 자동 실행하고 이벤트 로그 저장
aincrad simulate --seed 42 --days 7 --headless --class mage \
  --history-root runs/history --output runs/demo
aincrad replay runs/demo/events.jsonl --verify-hash
```

기존 이벤트 로그는 증거 보존을 위해 자동으로 덮어쓰지 않습니다. 같은 출력 경로를
의도적으로 교체할 때만 `simulate`에 `--force`를 추가하세요. `replay`는 기본적으로
스키마만 검사하며, 해시 체인 무결성까지 확인하려면 `--verify-hash`를 사용합니다.

현재 던전 1~10단계와 보스방은 이동 가능한 세계 구조와 콘텐츠 메타데이터까지
구현되어 있습니다. 퀘스트 제안·완료와 동료 합류·이탈은 고정 시간표가 아니라 현재
장소, 관찰된 행동, 관계 점수, 콘텐츠 catalog에서 생성된 Story proposal을 규칙 엔진이
검증해 처리합니다. 확정 actor proposal, StoryIntent, 수락·거부 결과는 완료 tick 수와
최종 world digest를 약정하는 `run_end` 포함 v3 해시 체인 로그에 저장됩니다. v3의
`run_init`은 검증된 identity profile을 포함하고, 기존 v2 로그는 변경 없이 계속 replay됩니다.
외부 AI 문장은 tick, hash, history에 저장하지 않습니다. replay는
AI policy나 Story Director를 다시 호출하지 않습니다. 성장,
던전 위험, 영구 사망도 결정론적 runtime과 replay에 연결되어 있습니다. 실제 전투 명령,
보스 처치 판정 및 퀘스트 보상은 다음 구현 단계입니다.

구현 중인 CLI의 최신 옵션은 다음 명령으로 확인할 수 있습니다.

```bash
aincrad --help
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
src/aincrad/commentary/   이동 전 해설과 선택적 Hermes/Kimi adapter
src/aincrad/persistence/  이벤트 로그, 검증, 재생
src/aincrad/history/      시간·일·회차별 영구 기록
src/aincrad/tui/          터미널 투영
content/                  독자 세계관 콘텐츠
fixtures/                 결정론적 테스트 입력
```

## 문서

- [아키텍처](docs/architecture.md)
- [ADR-0001: 결정론적 코어와 AI 정책 분리](docs/adr/0001-deterministic-core-and-agent-boundary.md)
- [ADR-0002: Textual 기반 full-screen TUI](docs/adr/0002-textual-full-screen-tui.md)
- [기여 가이드](CONTRIBUTING.md)

## 라이선스

MIT
