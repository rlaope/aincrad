# ADR-0003: 결정론적 이세계 사회 시뮬레이션

- 상태: 채택
- 결정일: 2026-08-27
- 근거 조사: `docs/research/ai-town-reverse-engineering.md`

## 맥락

현재 Aincrad는 한 명의 주인공과 동적 파티가 매시간 행동하고, rules-owned Story Director가
퀘스트·합류·이탈 사건을 제안하는 결정론적 모험 시뮬레이터입니다. 일반 NPC는 시설별 규칙
서비스이며, 독립적인 일정·기억·관계·대화 lifecycle을 가진 주민 actor는 아직 아닙니다.

목표 제품은 AI Town이나 Generative Agents처럼 여러 주체가 일하고, 이동하고, 만나고,
기억하고, 관계를 바꾸며 사용자가 그 사회를 관찰·개입할 수 있는 **텍스트 기반 이세계 사회
시뮬레이터**입니다. 다만 AI Town의 wall-clock loop, seed 없는 확률, provider-dependent memory,
replace-in-place persistence를 가져오면 Aincrad의 offline 실행, logical hour, event sourcing,
strict hash replay를 잃습니다.

## 결정

AI Town runtime을 port하지 않습니다. Aincrad의 한 시간 batch kernel과 event log 위에
Smallville식 사회 인지 구조를 rules-owned model로 다시 구현합니다.

> 주민과 사용자는 intent를 제출하고, 규칙 엔진만 상태와 결과를 변경합니다. 기억·관계·계획은
> canonical event에 근거해야 하며, 외부 AI는 bounded proposal 또는 projection만 만듭니다.

### 제품 정체성

Aincrad는 실시간 sprite town이 아니라 **조사 가능한 이세계 사회**입니다.

- 화면의 중심은 지도 animation이 아니라 시간별 장면, 주민의 현재 목적, 관계 변화,
  소문·정보 흐름과 그 원인입니다.
- 사용자는 주인공으로 참여하면서도 사회 전체의 변화를 관찰합니다.
- 시스템은 “무슨 일이 일어났는가”뿐 아니라 “어떤 사건과 기억 때문에 이런 선택을 했는가”를
  canonical evidence로 설명할 수 있어야 합니다.
- LLM이 꺼져도 같은 사회 규칙과 모든 필수 기능이 동작합니다.

## Canonical model

다음 정보만 rules state 또는 hash-covered event의 권위가 될 수 있습니다.

### Resident profile

콘텐츠 fixture가 제공하는 versioned, enum-coded profile입니다.

- 직업과 소속
- 생활 거점과 활동 가능 장소
- 규칙 기반 drive 가중치
- 공개 가치·성향 tag
- 사회 행동 capability

긴 persona prose는 선택적 projection 자료이며 legality나 score modifier가 아닙니다. 기존
`CharacterIdentityProfile`은 resident profile과 합치지 않습니다. 그것은 인간 사용자의 조사·해설
관점을 기록하는 run metadata입니다.

### Resident state

- 생존·활성 상태
- 현재 위치
- 현재 drive와 bounded need
- 현재 schedule slot
- 진행 중인 canonical commitment
- 관찰 가능한 지식 reference

모든 수치는 명시적 범위와 deterministic update rule을 가집니다.

### Relationship edge

관계는 `(observer_id, subject_id)` 방향 edge입니다. 초기 버전은 다음 bounded integer 축만
사용합니다.

- familiarity: 얼마나 자주 직접 접촉했는가
- affinity: 호감과 반감
- trust: 말과 행동을 믿는 정도
- obligation: 빚·약속·책임
- tension: 갈등과 경계

관계 변화 event는 이전 값, delta, 이후 값, reason code와 하나 이상의 evidence event ID를
포함합니다. LLM 문장이나 감정 분석 결과로 관계 수치를 변경하지 않습니다.

### Social encounter

대화는 free-form transcript가 아니라 먼저 구조화된 encounter로 판정합니다.

- 초대, 수락, 거절
- 접근, 참여, 이탈
- 정보 요청·공유
- 도움 요청·약속
- 거래 제안
- 갈등·화해

참여자, 장소, tick, topic code, speech-act sequence, outcome, 관계 변화가 canonical입니다.
한국어 대사는 이 구조에서 만든 projection이며 world-state authority가 아닙니다.

### Grounded memory

기존 `MemoryRecord`와 `MemoryStore`를 확장합니다. 모든 memory는 owner, kind, created tick,
근거 event ID를 유지합니다. 추가할 canonical metadata는 다음과 같습니다.

- rule-assigned importance
- subject·location·topic reference
- deterministic expiry 또는 decay class
- reflection인 경우 근거 memory ID

검색은 먼저 exact subject/topic, recency, rule-assigned importance를 사용하는 pure function으로
구현합니다. embedding과 vector database는 core dependency가 아닙니다. Reflection은 evidence가
있는 여러 memory를 rules template으로 압축하며, 새로운 사실을 만들어서는 안 됩니다.

### Drive와 schedule

Smallville의 free-form 일일 계획을 그대로 저장하지 않습니다.

- 콘텐츠가 일·휴식·식사·거래·탐구·사회화 같은 drive와 가능한 시간대를 정의합니다.
- 매일 시작 시 rules engine이 logical time, 장소 운영시간, commitment, need를 사용해 schedule
  slot을 생성합니다.
- 매시간 현재 perception과 사건으로 candidate intent를 만듭니다.
- 사건에 반응한 재계획도 versioned reason code를 가진 canonical schedule event입니다.

## 한 시간 social loop

한 tick은 계속 세계 시간 한 시간입니다. 같은 tick의 상태를 순차적으로 몰래 읽어 이득을
얻는 actor가 없도록 다음 순서를 고정합니다.

1. **Snapshot** — tick 시작 WorldState와 actor set을 고정합니다.
2. **Perception** — 각 actor에게 그 snapshot에서 관찰 가능한 정보와 grounded memory만 줍니다.
3. **Candidates** — rules가 actor별 합법 행동·이동·사회 intent 후보를 생성합니다.
4. **Selection** — 사용자, baseline policy 또는 허용된 optional provider가 후보 하나를 제안합니다.
5. **Freeze** — 살아 있고 활성인 모든 required actor의 intent가 정확히 하나인지 canonical actor
   order로 검증합니다. 누락·malformed·timeout은 actor별 deterministic fallback intent가 됩니다.
6. **Resolution** — 이동·시설·생존·encounter conflict를 명시된 phase와 seed-derived channel로
   일괄 판정합니다.
7. **Derivation** — 판정 event만 읽어 relationship·grounded memory·daily social aggregate를
   canonical event로 확정합니다.
8. **Clock** — 같은 `tick/next_tick` 계약을 가진 batch의 final state에서 세계 시계를 정확히
   한 번 증가시킵니다.
9. **Persist** — action, encounter, relationship, schedule, memory event와 final state commitment를
   한 tick record로 저장합니다.
10. **Projection** — 저장까지 끝난 결과, 세계관, identity, 관계, 파티, 최근 canonical 사건만
    선택적 AI storyteller에 주어 한국어 장면·대화·해설을 자유롭게 렌더링합니다. prose는 실행마다
    달라도 되며 장면을 닫은 뒤에만 다음 tick 선택으로 넘어갑니다.

기존 “현재 살아 있는 파티원 모두가 한 행동” 규칙은 유지합니다. 주민 actor 확대 단계에서는
별도의 required resident actor set을 같은 batch에 추가합니다. 시설 service NPC 전부를 무조건
agent화하지 않고, 사회적 상태가 필요한 named resident만 actor로 승격합니다.

## Optional AI 경계

### Async operation token

외부 provider 작업을 prefetch하거나 background로 실행할 때 결과는 다음 값에 결합합니다.

- run ID
- target tick
- actor ID
- operation kind
- candidate-set digest

현재 token과 정확히 일치하지 않는 late/stale 결과는 폐기합니다. local synchronous terminal
run에는 distributed generation fence를 추가하지 않습니다. 다중 writer 또는 crash-resume가 실제
runtime 요구가 될 때만 generation lease를 persistence ADR로 별도 검토합니다.

### AI가 할 수 있는 일

- 합법 후보 중 하나를 proposal로 선택
- 확정 encounter의 한국어 대사를 생성
- grounded memory를 읽기 쉬운 문장으로 표현
- 시간별·일별 사회 장면을 서술
- 사용자의 조사 관점에 맞춰 정보 강조

AI proposal을 canonical 행동으로 사용하는 mode에서는 engine이 exact candidate membership과
operation token을 검증하고 **선택된 intent 자체를 event log에 저장**합니다. Replay는 provider를
재호출하지 않고 저장된 intent를 재적용합니다.

### AI가 할 수 없는 일

- candidate에 없는 행동·대상 추가
- WorldState, 관계 score, memory importance, schedule 또는 outcome 직접 변경
- 숨겨진 state 읽기
- event payload·history·hash에 provider prose 삽입
- malformed output을 임의로 복구
- provider 실패 때문에 required actor action을 누락

모든 외부 출력은 기존 commentary boundary처럼 bounded I/O, timeout, process-group cleanup,
environment allowlist, strict schema, terminal sanitization과 deterministic fallback을 적용합니다.

## Dialogue와 persistence

canonical log에는 speech act와 outcome을 기록하고 provider prose는 기록하지 않습니다.
로컬 template 대사는 canonical facts에서 언제든 재생성할 수 있습니다. 선택적 provider 대사를
사용자가 다시 보고 싶다면 hash chain 밖의 명시적 non-authoritative projection cache에 저장할 수
있지만, cache 손실·변경은 replay 결과와 history fact를 바꾸지 않아야 합니다.

`history why` 계열 기능은 relationship, memory, schedule change, rumor, quest 상태에서 evidence
edge를 따라 `run_init` 또는 fixture fact까지 역추적합니다. 근거가 끊긴 derived fact는 저장하거나
표시하지 않습니다.

## Textual 관찰 UX

현재 full-screen Textual 기반과 한국어 projection을 유지합니다. 사회 기능은 다음 화면으로
확장합니다.

- **한 시간 장면** — 먼저 확정된 주요 행동과 사회 encounter를 책의 한 장면처럼 표시
- **주민 관찰** — 위치, 공개 목적, 최근 행동, 현재 알 수 있는 관계만 표시
- **관계망** — 수치만 나열하지 않고 최근 변화와 evidence scene을 함께 표시
- **사회 일지** — 일별 만남, 약속, 갈등, 소문 이동과 집단 변화를 요약
- **왜?** — 선택·관계·소문의 causal chain을 event 단위로 탐색
- **개입** — 공지 게시, 의뢰 후원, 선물, 만남 제안 등 engine이 정의한 intervention만 제출

40-column에서는 한 화면에 한 주민 또는 한 장면만 보여주고, 80-column에서는 장면과 근거 panel을
함께 보여줍니다. canonical ID와 raw score는 일반 play 화면에서 숨기고 inspect/debug mode에서만
노출합니다.

## 현재 staged slice의 처리

### 유지

- 네 차원의 enum-coded human identity와 v3 metadata
- committed v2 replay compatibility
- Textual full-screen, 40×24·80×24 responsive flow
- 추천 최대 세 곳과 `기타 목적지`
- 장소별 fixture-backed action과 achievement-only EXP
- simulation-first, post-persist 자유 AI turn narrative
- bounded Hermes/Kimi storyteller와 deterministic local fallback

### 수정·확장

- movement commentary는 이동 하위 안내로 유지하고, post-turn `storytelling` boundary가
  dialogue·social digest·시간별 장면을 담당합니다.
- identity는 rules modifier가 아니라 어떤 사회 신호를 해설에서 강조할지 정하는 lens로만 씁니다.
- action screen 앞뒤에 주민·관계·사회 장면 관찰 흐름을 추가합니다.

### 배제

현재 staged 기능 중 이 방향 때문에 즉시 폐기할 것은 없습니다. 다만 staged slice만으로
“AI Town형 사회가 구현됐다”고 설명해서는 안 됩니다.

## 단계별 roadmap

### Stage 1 — Offline autonomous society kernel

- named resident 8명 이상
- deterministic drive·schedule·candidate policy
- encounter lifecycle와 방향성 relationship event
- grounded social memory와 rules reflection
- 7일 headless simulation과 시간별 사회 장면

Acceptance:

- 같은 fixture·seed·intent sequence를 세 번 실행한 JSONL이 byte-identical
- `replay --verify-hash`가 최종 state와 전체 payload를 검증
- 모든 relationship delta와 reflection에 evidence가 존재
- 필수 suite에서 network·LLM 호출 0건
- 8명·7일 simulation이 개발 machine에서 10초 이내
- script에 직접 고정하지 않은 multi-resident encounter가 하루 평균 하나 이상 발생

### Stage 2 — Observer intervention과 causal inspection

- versioned `InterventionIntent`
- 공지·의뢰 후원·선물·만남 제안
- rumor·commitment·social daily summary
- `history why` evidence traversal
- TUI 주민·관계·사회 일지

Acceptance:

- 현재 관계·약속·소문·quest fact가 완전한 evidence chain을 반환
- intervention run도 hash replay가 동일
- 기존 v2/v3 log는 rewrite 없이 그대로 replay
- 좁은 화면과 80-column에서 keyboard·focus·CJK·resize·PTY·visual gate 통과

### Stage 3 — Optional AI social projection

- resolved encounter 대화 생성
- grounded memory와 daily digest의 표현
- 선택적으로 합법 social candidate 중 하나를 제안
- operation token과 candidate digest 검증

Acceptance:

- provider off에서 모든 필수 기능·test·replay 통과
- projection-only mode는 provider on/off의 canonical event와 hash가 동일
- proposal mode replay는 provider 없이 저장 intent로 동일
- timeout·malformed·oversized·unsafe output이 bounded local fallback으로 종료
- provider prose가 canonical tick/history payload에 없음

## 결과

### 장점

- AI Town형 창발적 만남을 Aincrad의 stricter replay 모델 안에서 만들 수 있습니다.
- 사회 변화가 LLM 분위기가 아니라 사건과 관계 근거로 설명됩니다.
- 외부 provider가 없어도 product가 작동합니다.
- Textual은 pixel map을 흉내 내지 않고 causal observation에 특화됩니다.

### 비용

- 자유 문장보다 먼저 social intent·relationship·memory schema를 설계해야 합니다.
- 대화 문장과 canonical 사실을 분리하는 projection/cache 계층이 필요합니다.
- 모든 주민 actor를 한 번에 도입하지 않고 fixture·scheduler·replay version을 함께 확장해야 합니다.
- deterministic conflict resolution과 사회 행동 후보가 많아질수록 property test가 중요해집니다.

## 재검토 조건

- local hourly kernel이 목표 주민 수에서 실제 성능 병목으로 측정될 때 actor partition 또는 Rust
  core를 검토합니다.
- crash-resume나 concurrent writer가 제품 요구가 될 때 generation lease를 별도 ADR로 검토합니다.
- deterministic lexical retrieval이 품질 병목으로 확인될 때 optional embedding index를 projection
  cache로 검토하되 core dependency로 만들지 않습니다.
