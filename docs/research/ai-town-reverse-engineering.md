# AI Town·Generative Agents 역설계

- 조사일: 2026-08-27
- 범위: 텍스트 기반 이세계 사회 시뮬레이터로 발전시키기 위한 구조 조사
- AI Town revision: `8e05997f2409275669c8344b84a51692e83f3f33`
- Generative Agents revision: `fe05a71d3e4ed7d10bf68aa4eda6dd995ec070f4`
- 논문: Park et al., *Generative Agents: Interactive Simulacra of Human Behavior*, arXiv:2304.03442v2

이 문서는 두 프로젝트에서 실제로 관찰한 구조와 한계를 기록합니다. Aincrad의 설계
결정은 `docs/adr/0003-deterministic-otherworld-social-simulation.md`에서 별도로 다룹니다.
코드를 복사하거나 원 프로젝트의 상표·캐릭터·자산을 재사용하지 않습니다.

## 조사 결론

AI Town은 Smallville 논문의 전체 인지 구조를 TypeScript로 옮긴 구현이 아닙니다.
실제로는 다음 요소를 갖춘 실시간 멀티에이전트 starter kit에 가깝습니다.

- Convex 위에서 동작하는 single-writer game loop
- 인간과 에이전트가 같은 input queue로 명령을 제출하는 구조
- 느린 LLM 작업을 게임 loop 밖에서 실행하고 결과를 input으로 되돌리는 구조
- 2인 대화 lifecycle
- 대화 요약 memory, vector retrieval, importance, reflection 일부
- PixiJS 기반 실시간 위치·대화 투영

반면 논문의 핵심인 환경 관찰 memory, 계층적 일일 일정, 상황에 따른 재계획,
관계에 기반한 행동 선택은 AI Town 최신 조사 revision에도 완전하게 구현되어 있지 않습니다.

## 1. Engine과 상태 권한

AI Town engine document에는 `currentTime`, `lastStepTs`, `processedInputNumber`,
`running`, `generationNumber`가 있습니다. generation number는 중복 engine action의 commit을
막는 optimistic lease입니다.

`convex/engine/abstractGame.ts`의 한 step은 다음 순서입니다.

1. monotonic input number 순서로 아직 처리하지 않은 input을 읽습니다.
2. 현재 simulation timestamp까지 도착한 input을 처리합니다.
3. concrete game의 `tick()`을 호출합니다.
4. tick timestamp를 증가시키며 wall clock을 따라잡습니다.
5. world와 input result를 하나의 mutation으로 저장합니다.
6. generation number가 달라졌다면 stale writer의 commit을 거부합니다.

`convex/aiTown/game.ts`의 tick phase는 player, pathfinding, position, conversation,
agent, position-history 기록 순서입니다. 저장 시 이름과 달리 작은 causal diff를 저장하지
않고 world document 전체를 교체합니다. `HistoricalObject`는 hash replay가 아니라 1초 간격
저장 사이의 움직임을 client에서 부드럽게 보간하기 위한 lossy buffer입니다.

### 비동기 operation 왕복

AI Town에서 LLM 작업은 tick을 직접 막지 않습니다.

1. `Agent.tick()`이 operation ID를 만들고 `inProgressOperation`을 authoritative state에
   기록합니다.
2. world save 이후 Convex action으로 LLM 또는 embedding 작업을 실행합니다.
3. 결과는 `finish...` input으로 engine queue에 다시 들어갑니다.
4. engine handler가 현재 operation ID와 일치할 때만 결과를 적용합니다.
5. timeout 또는 stale result는 폐기됩니다.

이 구조는 외부 provider가 world table을 직접 쓰지 못하게 한다는 점에서 유용합니다.
다만 AI Town의 timeout은 operation을 조용히 지우므로, 모든 주민이 시간마다 정확히 하나의
행동을 제출해야 하는 Aincrad에는 그대로 적용할 수 없습니다.

## 2. 실제 Agent loop

`convex/aiTown/agent.ts`의 `Agent.tick()`은 대부분 deterministic state machine과 timer로
구성됩니다. 현재 operation 대기, 활동 선택, 대화 기억, 초대 수락, 상대에게 접근,
대화 메시지 생성, 대화 종료를 우선순위대로 처리합니다.

실제 자율 행동 범위는 README 인상보다 제한적입니다.

- 비대화 상태의 activity는 독서, 공상, 정원 가꾸기 중 무작위 선택입니다.
- 이동 목적지는 무작위 tile입니다.
- 대화 상대는 cooldown과 위치를 기준으로 선택합니다.
- AI agent의 초대 수락은 `0.8` 확률 roll입니다.
- `plan`은 갱신·분해되는 일정이 아니라 character fixture의 한 줄 목표입니다.
- 대화는 두 사람만 지원합니다.
- 환경을 관찰해 observation memory를 만드는 경로는 없습니다.

조사 revision에는 대화 상대 distance 계산이 상대가 아니라 초대자의 position을 넣는 것으로
보이는 결함도 있어, 정렬 결과가 의도한 nearest-player 선택을 보장하지 않습니다.

## 3. 대화와 memory

대화 상태는 invited, walking-over, participating으로 진행됩니다. 거리, 초대 timeout,
message cooldown, 최대 메시지 수, 최대 대화 시간이 규칙으로 제한됩니다. LLM은 대화 시작,
계속, 작별 문장을 생성하지만 membership 전이와 위치 변경은 engine input handler가 수행합니다.

대화가 끝나면 두 agent가 각각 다음 pipeline을 실행합니다.

1. transcript를 일인칭 memory로 요약합니다.
2. LLM이 importance 0–9를 평가합니다.
3. description embedding을 저장합니다.
4. retrieval 시 vector relevance, recency, importance를 합산합니다.
5. 최근 memory importance 합이 threshold를 넘으면 세 reflection을 생성합니다.

이것은 논문의 relevance·recency·importance 구조를 실제로 구현합니다. 다만 importance parse
실패 시 `5`를 사용하고 reflection JSON 실패를 조용히 삼키며, provider 결과가 memory와 이후
대화에 영향을 주므로 deterministic replay는 제공하지 않습니다.

`relationship` memory variant는 schema에는 있으나 조사 revision에서 생성하는 write path를
찾지 못했습니다. `participatedTogether`는 함께 대화한 시점과 conversation ID를 기록하지만,
신뢰·호감·갈등 같은 방향성 관계 상태는 아닙니다.

## 4. Smallville 원본과 차이

Stanford 원본의 persona loop는 `perceive → retrieve → plan → reflect → execute`입니다.
주요 구조는 다음과 같습니다.

- spatial event를 관찰해 associative memory에 기록
- relevance·recency·importance로 기억 검색
- 하루 일정을 만들고 시간·분 단위 action으로 재귀 분해
- 다른 persona 또는 사건을 만나면 기존 일정을 반응적으로 재계획
- 누적 importance가 threshold를 넘으면 질문과 insight를 만들고 근거 memory를 연결
- 대화와 행동을 현재 위치·일정에 결합

AI Town은 대화 memory와 reflection 일부를 구현했지만, 이 전체 loop를 복제하지 않습니다.
따라서 AI Town만 port하면 논문에서 보인 파티 조직, 일정 조율, 관계 확산이 자동으로 생기지
않습니다.

## 5. Determinism과 replay 한계

AI Town은 causal replay를 제공하지 않습니다.

- simulation path에 `Date.now()`와 seed 없는 `Math.random()`이 있습니다.
- input의 `received` wall-clock timestamp로 어느 tick에 포함될지가 달라질 수 있습니다.
- world state를 replace-in-place하고 오래된 input을 vacuum합니다.
- project comment도 replay를 원한다면 snapshot 또는 전체 input 보존이 필요하다고 설명합니다.
- LLM summary, importance, reflection과 embedding 결과가 후속 대화에 영향을 줍니다.
- engine 중단 시간은 재시작 시 simulation하지 않고 건너뜁니다.

Aincrad의 logical hour, seeded rule channel, canonical JSONL, SHA-256 chain, full-payload strict
replay가 이 부분에서는 더 강한 기반입니다.

## 6. Frontend와 persistence

AI Town frontend는 Convex reactive query로 world state와 messages를 구독하고 PixiJS로 tile,
sprite, 이동, typing, 대화를 표시합니다. 위치 history 압축은 60fps canvas와 1Hz database
save 사이를 보간하기 위한 해법입니다.

Aincrad의 Textual UI에는 sprite interpolation이 필요하지 않습니다. 대신 같은 원칙 중
다음 하나는 유효합니다. 대량의 대화 문장과 해설은 canonical simulation state와 분리하고,
canonical event에는 참여자·장소·시간·행동·관계 변화·근거만 기록할 수 있습니다. 단,
사용자에게 사실로 제시하는 지속 정보는 항상 canonical event로 재구성 가능해야 합니다.

## 7. 라이선스와 재사용 방침

- AI Town은 MIT License입니다.
- Stanford repository는 code에 대해 별도 license 조건과 asset별 attribution 조건을
  명시합니다.

Aincrad는 architecture pattern만 독립적으로 다시 구현합니다. source code, prompt fixture,
character persona, map, sprite, name, music 또는 world asset을 복사하지 않습니다. 독자 세계관
**The Glass Frontier**와 기존 규칙 경계를 유지합니다.

## 8. 조사에서 얻은 기술적 선택지

### 채택 후보

- single-writer authority
- ordered input과 per-intent result
- 대화 membership lifecycle
- operation ID로 stale async result 거부
- 참여 관계 graph의 event-sourced 재해석
- record → retrieve → reflect pipeline의 형태

### 수정이 필요한 후보

- generation fence: always-on distributed engine이 아니라 run resume·중복 apply가 실제로 생기는
  persistence boundary에서만 검토
- async LLM: canonical 행동을 기다리지 않고 deterministic fallback 또는 projection prefetch로만 사용
- memory ranking: rule-assigned importance와 event evidence를 사용하고 core에서 vector DB를 요구하지 않음
- planning: free-text plan이 아니라 rules-owned drive·schedule·candidate intent로 구성
- dialogue: 문장은 비권위 projection, 구조적 대화 결과만 canonical event

### 배제

- wall-clock simulation
- seed 없는 확률
- provider output의 직접 state mutation
- required vector database
- whole-world replace persistence
- input vacuum에 의존하는 history
- Pixi·sprite·music runtime
- free-text identity를 rules modifier로 사용
