# 아키텍처

## 목표

Aincrad는 AI 기반 이세계 사회 조사 시뮬레이터입니다. 세계·전투·경제 규칙의 권위와
AI 모험가 및 해설자의 비결정적 판단을 분리하고, 사용자는 낯선 환경과 사회의 물리적 조건,
관계, 시간별 사건과 결과를 터미널에서 관찰합니다.

현재 runtime의 일반 NPC는 규칙 기반 시설 서비스입니다. 목표 사회 모델은 named resident가
일정·drive·grounded memory·방향성 관계·구조화된 encounter를 갖는 형태이며, AI Town runtime을
port하지 않고 기존 logical-hour kernel 위에 단계적으로 추가합니다. canonical model과 도입
순서는 `docs/adr/0003-deterministic-otherworld-social-simulation.md`, 근거 조사는
`docs/research/ai-town-reverse-engineering.md`를 따릅니다.

## 데이터 흐름

```text
Actor Perception -> User/Baseline Policy -> ActionIntent --+
StoryPerception -> Story Director -> StoryIntent -----------+-> Validator/Resolver
                                                            -> DomainEvent
                                                            -> Event Store / Replay
                                                            -> History / Terminal Projection
Persisted result + world/identity/recent events -> AI Storyteller -> Terminal Projection only
```

## 경계

- `domain`은 모델 SDK, 네트워크, 프롬프트를 import하지 않습니다.
- `agents`는 읽기 전용 관찰을 받고 행동 의도만 반환합니다.
- Story Director는 폐쇄적이고 versioned인 `StoryIntent`만 제안하며 세계 상태를 직접 바꾸지 않습니다.
- story validator/resolver만 catalog 후보를 검증하고 quest/party 상태를 변경합니다.
- `persistence`는 사건을 정규화해 JSONL로 저장하고 해시 체인을 검증합니다.
- `tui`는 사건과 투영 상태를 읽기만 합니다.
- 일반 NPC는 첫 버전에서 독립 AI가 아닌 규칙 기반 서비스입니다.
- `commentary`는 이동 하위 화면의 물리·사회 안내만 만들고 합법 목적지 집합과 순서를 바꾸지 않습니다.
- `storytelling`은 판정·progression·Story resolution·history append 뒤 확정된 결과와 공개 세계관,
  run identity, 관계, 파티, 최근 canonical 장면을 받아 자유로운 한국어 prose를 만듭니다. 외부 문장은
  실행마다 달라도 되는 untrusted projection이며 state/event/history/hash에 들어가지 않습니다.
  Hermes subprocess는 direct argv, bounded stdin/stdout/stderr/time/process group, environment allowlist,
  strict JSON과 sanitization을 사용하고 모든 실패를 확정 사건 기반 로컬 서사로 대체합니다.
- 대화형 TUI는 Textual의 widget tree와 diff compositor를 사용합니다. Textual이 raw input,
  alternate screen, cursor, focus, resize를 소유하고 종료·예외에도 terminal 상태를 복원합니다.
  simulation은 worker thread에서 결정론적으로 실행되며 `choose`/`input_text` interaction
  boundary를 통해서만 Textual main loop에 선택을 요청합니다. headless/replay/history CLI는
  full-screen app과 독립적으로 동작합니다.
- 마을 root는 단일 `관찰` 장소가 아니라 내부 시설을 직접 고르는 hub로 투영합니다. 시설 진입은
  canonical `MOVE`를 유지하고, 마을 밖 경로만 별도 이동 추천 화면으로 보냅니다.
- 플레이어에게 보이는 지역명은 canonical location ID와 분리된 한국어 projection입니다.
  한 시간의 서사는 모든 actor intent의 일괄 판정, progression, Story resolution, history append가
  끝난 뒤 확정된 `DomainEvent`와 최종 상태만 읽어 생성하며 세계 상태를 다시 변경하지 않습니다.
  서사는 전용 Textual screen에서 한 글자씩 재생되고 문장부호마다 추가 pause를 둡니다.
  재생 중 Enter는 전체 표시, 표시 완료 후 Enter는 닫기이며, 그 뒤에만 다음 시간 진행 여부를 묻습니다.

## 시간

화면은 한 시간 단위로 사건을 묶습니다. 엔진은 행동 완료 시점을 처리하는 논리 시간으로 동작하며 현실 시간 대기나 항상 실행되는 서버를 요구하지 않습니다.

## 재현성

- 난수는 실행 시드에서 파생합니다.
- 같은 초기 상태, 규칙 버전, 시드, 행동열은 같은 사건과 최종 상태를 생성해야 합니다.
- actor RNG는 seed/tick/actor channel에서 독립적으로 파생해 proposal 도착 순서에 의존하지 않습니다.
- v3 로그는 초기 world/seed/주인공 표시 정보와 enum-coded human identity profile,
  actor proposal, StoryIntent와 resolution을 저장하고,
  `run_init`/`run_end`의 완료 tick 수·final tick·world digest commitment로 tail truncation을 거부합니다.
- strict replay는 JSON 정수 field에 `type(value) is int`를 요구해 Python에서 `true == 1`인
  언어 특성이 canonical scalar type 검증을 우회하지 못하게 합니다.
- v2 validator는 별도 strict branch로 유지되며 기존 로그를 rewrite하거나 자동 migration하지 않습니다.
- 새 v3 실행은 rules version 2를 기록합니다. committed v2/rules version 1은 location affordance와
  legacy EXP semantics를 격리한 replay-only branch에서 재적용합니다.
- human identity는 `WorldState`나 rules modifier가 아니라 hash-covered `run_init`과 history
  metadata입니다. 해설의 관점만 바꾸며 목적지 집합·추천 순서·판정을 바꾸지 않습니다.
- replay는 policy나 Story Director를 재호출하지 않고 저장된 proposal을 규칙 엔진에 다시 적용해
  전체 action event와 story resolution payload를 비교합니다.

## 초기 범위

콘텐츠 fixture와 `create_initial_world()`는 콘텐츠 검증과 시나리오 테스트를 위한 후보 모험가 3명을
제공합니다. 실제 라이브 실행은 캐릭터 선택 뒤 선택된 영웅 1명만으로 새 파티와 실행
상태를 구성합니다. 이후 동료 영입·이탈에 따라 라이브 파티 구성은 달라질 수 있으므로,
매 tick마다 정확히 세 명이 행동한다고 가정하지 않습니다.

사용자가 정한 표시 이름은 terminal/history용 데이터이며 파티와 replay는 안정적인 내부 ID
`hero`를 사용합니다. 한 시간에는 사용자가 주인공 행동을 직접 선택하거나 baseline policy에
위임하고, 살아 있는 동료는 각자의 `Perception`으로 자동 행동합니다. 모든 actor intent를 먼저
수집해 한 번 일괄 판정한 뒤 Story Director가 관찰 가능한 결과와 환경 facts에서 후보 하나를
선택합니다. resolver가 exact candidate membership, quest 전이, 관계 임계값, 파티 정원과 생존을
검증한 뒤에만 quest/party 상태를 변경합니다.

현재 Story 환경 규칙은 Wayfinder Assembly에서의 quest offer와 Mossreach에서 성공한 주인공
채집을 objective evidence로 사용합니다. 이는 고정된 줄거리 순서가 아니라 catalog와 명시적
관찰 facts에서 생성되는 결정론적 baseline입니다. 영구 사망과 boss facts는 Director의 재량
proposal 밖에 있으며 코어 규칙이 소유합니다.

세계 수직 절편은 내부 시설 5곳이 있는 마을 1개, 사냥터 1개, 10단계 던전과 보스방입니다.
각 장소는 fixture-backed 합법 행동 catalog를 갖고 시설 거래·숙박·의뢰·공지·식사·소문,
사냥터 사냥·채집·정찰·야영, 던전 정찰·수색·전투·보스 도전을 제공합니다. 전투와 보스 도전은
canonical 피해와 영구 사망을 판정합니다. 보스 처치·전이와 의뢰 완료 보상은 아직 미구현입니다.
