from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from aincrad.domain.display import character_width, safe_terminal_text
from aincrad.tui.layout import (
    clip_display,
    display_width,
    pad_display,
    wrap_display,
)

_KST = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True)
class EventView:
    occurred_at: datetime
    kind: str
    message: str


@dataclass(frozen=True)
class AdventurerView:
    name: str
    location: str
    hp: int
    mp: int
    activity: str
    level: int = 1
    exp: int = 0
    character_class: str = ""


@dataclass(frozen=True)
class RunSummary:
    seed: int
    days: int
    event_count: int
    status: str


def _char_width(character: str) -> int:
    return character_width(character)


def _display_width(text: str) -> int:
    return display_width(text)


def sanitize_terminal_text(text: str) -> str:
    """Neutralize controls, including Unicode format and bidi characters."""

    return safe_terminal_text(text)


def _safe_text(text: str) -> str:
    return sanitize_terminal_text(text)


def _clip(text: str, width: int) -> str:
    return clip_display(text, width)


def _pad(text: str, width: int) -> str:
    return pad_display(text, width)


def _wrap(text: str, width: int) -> list[str]:
    return wrap_display(text, width)


def _section(title: str, width: int) -> str:
    prefix = f"── {title} "
    return prefix + "─" * max(0, width - _display_width(prefix))


def render_simulation(
    events: tuple[EventView, ...],
    adventurers: tuple[AdventurerView, ...],
    summary: RunSummary,
    *,
    width: int = 80,
) -> str:
    """Render one deterministic Korean simulation projection without terminal I/O."""
    if width < 40:
        raise ValueError("width must be at least 40")

    lines = [_section("이벤트", width)]
    if not events:
        lines.append("(이벤트 없음)")
    first_date = events[0].occurred_at.astimezone(_KST).date() if events else None
    for event in events:
        local_time = event.occurred_at.astimezone(_KST)
        day_number = (local_time.date() - first_date).days + 1 if first_date else 1
        heading = (
            f"{day_number}일차 | {local_time:%Y-%m-%d} {local_time:%H:%M} KST | "
            f"{_safe_text(event.kind)}"
        )
        lines.extend(_wrap(heading, width))
        lines.extend(f"  {part}" for part in _wrap(_safe_text(event.message), width - 2))

    lines.extend(["", _section("모험가 상태", width)])
    columns: tuple[int, ...]
    rows: list[tuple[str, ...]]
    if width >= 74:
        columns = (10, 8, 14, 7, 7, 10, width - 74)
        rows = [("이름", "직업", "위치", "HP", "MP", "성장", "활동")]
        rows.extend(
            (
                _safe_text(adventurer.name),
                _safe_text(adventurer.character_class),
                _safe_text(adventurer.location),
                f"HP {adventurer.hp}",
                f"MP {adventurer.mp}",
                f"Lv.{adventurer.level} EXP {adventurer.exp}",
                _safe_text(adventurer.activity),
            )
            for adventurer in adventurers
        )
    else:
        columns = (6, 6, 5, 5, width - 34)
        rows = [("이름/직업", "위치", "HP", "MP", "성장")]
        rows.extend(
            (
                _safe_text(f"{adventurer.name}/{adventurer.character_class}"),
                _safe_text(adventurer.location),
                f"HP {adventurer.hp}",
                f"MP {adventurer.mp}",
                f"Lv.{adventurer.level} EXP {adventurer.exp}",
            )
            for adventurer in adventurers
        )
    for row in rows:
        lines.append(
            " | ".join(
                _pad(value, column) for value, column in zip(row, columns, strict=True)
            )
        )
    if not adventurers:
        lines.append("(모험가 없음)")

    lines.extend(["", _section("실행 요약", width)])
    summary_line = (
        f"시드 {summary.seed} | {summary.days}일 | 이벤트 {summary.event_count}건 | "
        f"상태 {_safe_text(summary.status)}"
    )
    lines.extend(_wrap(summary_line, width))
    return "\n".join(lines) + "\n"
