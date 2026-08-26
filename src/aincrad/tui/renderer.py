from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

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
    return 2 if unicodedata.east_asian_width(character) in {"F", "W"} else 1


def _display_width(text: str) -> int:
    return sum(_char_width(character) for character in text)


def sanitize_terminal_text(text: str) -> str:
    """Neutralize controls, including Unicode format and bidi characters."""

    return "".join(
        character
        if character.isprintable() and unicodedata.category(character)[0] != "C"
        else "�"
        for character in text
    )


def _safe_text(text: str) -> str:
    return sanitize_terminal_text(text)


def _clip(text: str, width: int) -> str:
    if _display_width(text) <= width:
        return text
    if width <= 1:
        return "…"[:width]
    result: list[str] = []
    used = 0
    for character in text:
        character_width = _char_width(character)
        if used + character_width > width - 1:
            break
        result.append(character)
        used += character_width
    return "".join(result) + "…"


def _pad(text: str, width: int) -> str:
    clipped = _clip(text, width)
    return clipped + " " * (width - _display_width(clipped))


def _wrap(text: str, width: int) -> list[str]:
    if not text:
        return [""]
    lines: list[str] = []
    current: list[str] = []
    used = 0
    for character in text:
        if character == "\n":
            lines.append("".join(current))
            current, used = [], 0
            continue
        character_width = _char_width(character)
        if current and used + character_width > width:
            lines.append("".join(current).rstrip())
            current, used = [], 0
        current.append(character)
        used += character_width
    lines.append("".join(current).rstrip())
    return lines


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
