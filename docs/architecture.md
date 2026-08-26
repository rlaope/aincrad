# 아키텍처

## 목표

Aincrad는 세계·전투·경제 규칙의 권위와 AI 모험가의 비결정적 판단을 분리합니다. 사용자는 날짜와 시간별 사건, 모험가 상태, 선택 이유와 결과를 터미널에서 관찰합니다.

## 데이터 흐름

```text
Actor Perception -> User/Baseline Policy -> ActionIntent --+
StoryPerception -> Story Director -> StoryIntent -----------+-> Validator/Resolver
                                                            -> DomainEvent
                                                            -> Event Store / Replay
                                                            -> History / Terminal Projection
```

## 경계

- `domain`은 모델 SDK, 네트워크, 프롬프트를 import하지 않습니다.
- `agents`는 읽기 전용 관찰을 받고 행동 의도만 반환합니다.
- Story Director는 폐쇄적이고 versioned인 `StoryIntent`만 제안하며 세계 상태를 직접 바꾸지 않습니다.
- story validator/resolver만 catalog 후보를 검증하고 quest/party 상태를 변경합니다.
- `persistence`는 사건을 정규화해 JSONL로 저장하고 해시 체인을 검증합니다.
- `tui`는 사건과 투영 상태를 읽기만 합니다.
- 일반 NPC는 첫 버전에서 독립 AI가 아닌 규칙 기반 서비스입니다.
- TUI는 방향키·W/S·Enter를 사용하며 raw terminal, alternate screen, cursor를 예외에도 복원합니다.

## 시간

화면은 한 시간 단위로 사건을 묶습니다. 엔진은 행동 완료 시점을 처리하는 논리 시간으로 동작하며 현실 시간 대기나 항상 실행되는 서버를 요구하지 않습니다.

## 재현성

- 난수는 실행 시드에서 파생합니다.
- 같은 초기 상태, 규칙 버전, 시드, 행동열은 같은 사건과 최종 상태를 생성해야 합니다.
- actor RNG는 seed/tick/actor channel에서 독립적으로 파생해 proposal 도착 순서에 의존하지 않습니다.
- v2 로그는 초기 world/seed/주인공 identity, actor proposal, StoryIntent와 resolution을 저장하고,
  `run_init`/`run_end`의 완료 tick 수·final tick·world digest commitment로 tail truncation을 거부합니다.
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

세계 수직 절편은 내부 시설 5곳이 있는 마을 1개, 사냥터 1개, 10단계 던전과
보스방입니다. 한 tick은 세계 시간 1시간이며 현재 라이브 파티에서 수집된 행동을 같은
tick에서 일괄 판정한 뒤 시계가 한 번 진행됩니다. 전투·보스 처치·퀘스트 보상은 이 시간
배치 커널 위에 추가합니다.
