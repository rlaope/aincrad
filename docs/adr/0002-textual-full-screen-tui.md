# ADR-0002: Textual 기반 full-screen TUI

- 상태: 채택
- 결정일: 2026-08-27

## 맥락

기존 대화형 화면은 문자열 frame을 만든 뒤 `tty.setraw()`와 ANSI escape sequence를
직접 사용해 출력했습니다. Python의 `tty.setraw()`는 입력 처리뿐 아니라 출력의
`OPOST`/`ONLCR`도 비활성화합니다. 그 결과 LF가 다음 행의 첫 열로 돌아가지 않아 실제
terminal에서 frame 행이 오른쪽으로 누적 이동할 수 있었습니다. 수동 renderer는 focus,
viewport, resize, CJK 폭, alternate-screen lifecycle도 애플리케이션이 직접 소유하게 해
기능 테스트가 통과해도 실제 화면 품질을 보장하기 어려웠습니다.

Textual, prompt_toolkit, Urwid, curses를 다음 기준으로 비교했습니다.

- cursor-addressed diff compositor와 full-screen lifecycle
- widget focus, scroll, resize 및 좁은 viewport
- 한국어/CJK 입력과 terminal-cell 폭
- 실제 PTY 및 headless UI 테스트 가능성
- 기존 deterministic simulation, replay, history와의 분리

동일한 한국어 메뉴를 사용한 실제 PTY spike에서 Textual과 prompt_toolkit 모두
80×24·40×12·live resize를 처리했습니다. Textual은 terminal attributes를 정확히
복원했고 Pilot, terminal resize, SVG screenshot을 일급 테스트 API로 제공했습니다.
prompt_toolkit은 더 낮은 수준의 layout 조립이 필요했고 spike 종료 뒤 attributes가
원본과 일치하지 않았습니다. curses와 Urwid는 필요한 widget/design/snapshot 계층을 더
많이 직접 구현해야 했습니다.

## 결정

인자 없는 TTY 실행은 Textual 8.x의 widget tree와 diff compositor를 사용합니다.

- Textual main loop가 raw input, alternate screen, cursor, focus, scroll, resize를 소유합니다.
- menu, name input, history detail은 `ListView`, `Input`, `VerticalScroll` 기반 widget screen입니다.
- deterministic simulation은 worker thread에서 실행합니다.
- worker는 `choose`, `input_text`, `show_text` interaction boundary로만 UI 결정을 요청합니다.
- 외부·저장 문자열은 기존 canonical sanitizer를 거친 뒤 markup을 비활성화해 표시합니다.
- `simulate --headless`, replay, history subcommand와 event/hash 계약은 Textual app과 독립적으로
  유지합니다.
- Textual은 `>=8.2,<9`로 제한해 major-version UI API 변경을 lock 갱신 시 명시적으로 검토합니다.

## 결과

### 장점

- 실제 terminal frame 좌표와 diff redraw를 검증된 compositor에 위임합니다.
- focus·scroll·narrow viewport·resize 동작을 widget state로 유지합니다.
- Pilot와 VT100 cell reconstruction을 함께 사용해 semantic UI와 실제 PTY를 검증할 수 있습니다.
- simulation의 결정론과 terminal lifecycle 책임이 분리됩니다.

### 비용

- Textual과 Rich 계열 runtime dependency가 추가됩니다.
- synchronous simulation과 async UI 사이에 bounded worker bridge가 필요합니다.
- Textual major upgrade마다 CSS, event, test API 호환성을 검토해야 합니다.

## 검증

- Pilot: menu selection, Korean name input, 40-column/80-column resize
- 실제 subprocess+PTY: keyboard flow, alternate-screen 복원, exact termios 복원
- VT100 cell reconstruction: 40-column panel bounds, CJK replacement 없음, resize 뒤 selection 유지
- 전체 offline simulation/replay/history test suite
