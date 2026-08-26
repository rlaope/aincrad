from __future__ import annotations

import unicodedata
from datetime import UTC, datetime

from aincrad.tui.renderer import (
    AdventurerView,
    EventView,
    RunSummary,
    render_simulation,
)


def display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1 for char in text)


def test_renderer_projects_korean_time_events_status_and_summary_within_80_columns() -> None:
    events = (
        EventView(
            occurred_at=datetime(2026, 8, 26, 0, 5, tzinfo=UTC),
            kind="전투 승리",
            message="레아가 매우 긴 이름의 필드 보스를 물리치고 희귀 아이템을 획득했습니다.",
        ),
    )
    adventurers = (
        AdventurerView("Rhea Vale", "Emberfall", 87, 40, "휴식 중"),
    )
    summary = RunSummary(seed=7, days=2, event_count=1, status="완료")

    rendered = render_simulation(events, adventurers, summary, width=80)

    assert "2026-08-26" in rendered
    assert "09:05 KST" in rendered
    assert "전투 승리" in rendered
    assert "모험가 상태" in rendered
    assert "Rhea Vale" in rendered
    assert "HP 87" in rendered
    assert "Lv.1" in rendered
    assert "EXP 0" in rendered
    assert "실행 요약" in rendered
    assert "시드 7" in rendered
    assert "2일" in rendered
    assert all(display_width(line) <= 80 for line in rendered.splitlines())


def test_renderer_is_deterministic_for_identical_inputs() -> None:
    event = EventView(datetime(2026, 8, 26, tzinfo=UTC), "이동", "마을에 도착")
    adventurer = AdventurerView("Tovin Reed", "Emberfall", 100, 20, "대기")
    summary = RunSummary(seed=11, days=1, event_count=1, status="완료")

    first = render_simulation((event,), (adventurer,), summary)
    second = render_simulation((event,), (adventurer,), summary)

    assert first == second


def test_renderer_neutralizes_terminal_control_sequences() -> None:
    event = EventView(
        datetime(2026, 8, 26, tzinfo=UTC),
        "이동\x1b]52;c;YXR0YWNr\x07",
        "위조\x1b[2J메시지\n다음 줄",
    )
    adventurer = AdventurerView("Rhea\rVale", "Emberfall", 100, 20, "대기\t중")
    rendered = render_simulation(
        (event,), (adventurer,), RunSummary(1, 1, 1, "완료\x1b[0m")
    )

    assert "\x1b" not in rendered
    assert "\x07" not in rendered
    assert "\r" not in rendered
    assert "\t" not in rendered
    assert "메시지\n다음 줄" not in rendered
