# 개발·검증·전달 규칙

## 이벤트·저장 계약

- 이벤트 JSON은 canonical serialization을 사용한다.
- JSONL은 연속 `seq`와 SHA-256 `prev_event_hash`/`event_hash` 체인을 유지한다.
- 기존 이벤트 로그는 기본적으로 덮어쓰지 않는다. 명시적 `--force`만 원자 교체한다.
- versioned run은 schema와 rules/content revision을 함께 고정한다. 새 write는 schema v4/rules v3와
  current package world를 사용하고, schema v3/rules v2 strict replay는
  `glassfrontier_world_rules_v2.json` snapshot만 재구성에 사용한다. loader는 trusted revision allowlist만
  받아 같은 fail-closed validator를 거치며 임의 resource/path를 받지 않는다.
- 동적 파티 replay는 시간별 정확한 파티 행동 집합과 합류·이탈을 재구성한다.
- history는 symlink/path escape를 거부하고 canonical JSON, monotonic 회차 번호,
  엄격한 hourly/daily_summary/character_end schema를 유지한다.
- 손상, 누락, 순서 오류를 조용히 건너뛰거나 자동 복구하지 않는다.
- 터미널에 표시되는 모든 외부/저장 문자열은 제어문자를 무력화한다.

## 개발 절차

1. 관련 정의와 모든 사용처를 먼저 읽는다.
2. 실패하는 테스트를 먼저 작성하고 RED를 실제로 확인한다.
3. 최소 구현으로 GREEN을 확인한다.
4. 변경 범위의 테스트 후 전체 품질 gate를 실행한다.
5. 독립 fail-closed review 전에는 완료·안전·push를 주장하지 않는다.

필수 명령은 저장소 루트 `AGENTS.md`의 quality gate를 따른다. CLI 또는 저장 계약을
바꾸면 실제 `simulate -> events.jsonl -> replay --verify-hash`와 `history list/show` smoke를
추가로 실행한다. wheel/package resource를 바꾸면 fresh isolated environment에 wheel을
설치하고 `aincrad simulate`까지 실행한다.

## 커밋·원격 전달

- 기능·책임별 작은 논리 commit과 Conventional Commit 형식을 사용한다.
- 한 commit에는 하나의 설명 가능한 목적과 이를 검증하는 tests를 함께 둔다.
- schema와 consumer처럼 단독으로 깨지는 변경은 같은 commit에 둔다.
- 관련 없는 formatting, rename, drive-by refactor를 섞지 않는다.
- `build/`, `dist/`, `*.egg-info`, 실행 log, local history, `.env`, secret을 commit하지 않는다.
- 사용자 요청 없이 amend, rebase, force-push, history rewrite를 하지 않는다.
- 이 개인 테스트 단계에서는 전체 local gate와 독립 review를 통과한 논리 commit을
  `main`에 직접 push할 수 있다.
- remote CI는 push 뒤의 별도 증거다. 성공 확인 전에는 전달 완료를 주장하지 않고,
  실패하면 추가 push를 멈추고 원인을 수정·재검증한다.

## 문서 동기화

행동, CLI option, 세계관 ID, 저장 schema, 검증 명령이 바뀌면 `README.md`,
`docs/architecture.md`, 관련 정본 문서, fixture, tests를 같은 작업에서 확인한다.
구현되지 않은 기능을 현재 기능처럼 문서화하지 않는다.
