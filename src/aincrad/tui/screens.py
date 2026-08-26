from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from aincrad.tui.renderer import sanitize_terminal_text

_DEFAULT_HINT = "↑/↓ 또는 W/S로 이동 · Enter로 선택"


def _character_width(character: str) -> int:
    if unicodedata.combining(character):
        return 0
    return 2 if unicodedata.east_asian_width(character) in {"F", "W"} else 1


def _wrap_display(text: str, width: int) -> list[str]:
    lines: list[str] = []
    current: list[str] = []
    used = 0
    for character in text:
        character_width = _character_width(character)
        if current and used + character_width > width:
            lines.append("".join(current))
            current = []
            used = 0
        current.append(character)
        used += character_width
    lines.append("".join(current))
    return lines


@dataclass(frozen=True, slots=True)
class MenuChoice:
    """One immutable choice in a terminal menu projection."""

    label: str
    description: str = ""


def render_menu(
    title: str,
    choices: Sequence[MenuChoice],
    selected_index: int,
    *,
    hint: str = _DEFAULT_HINT,
    allow_back: bool = False,
    width: int = 80,
) -> str:
    """Render a deterministic, non-numeric Korean menu without terminal I/O."""
    if not choices:
        raise ValueError("choices must not be empty")
    if not 0 <= selected_index < len(choices):
        raise ValueError("selected_index out of range")
    if width < 40:
        raise ValueError("width must be at least 40")

    safe_hint = sanitize_terminal_text(hint)
    if allow_back:
        safe_hint = f"{safe_hint} · Esc로 뒤로"
    lines = [*_wrap_display(sanitize_terminal_text(title), width), ""]
    for index, choice in enumerate(choices):
        prefix = "> " if index == selected_index else "  "
        label = sanitize_terminal_text(choice.label)
        description = sanitize_terminal_text(choice.description)
        suffix = f" — {description}" if description else ""
        choice_lines = _wrap_display(f"{label}{suffix}", width - 2)
        lines.append(f"{prefix}{choice_lines[0]}")
        lines.extend(f"  {line}" for line in choice_lines[1:])
    lines.append("")
    lines.extend(_wrap_display(safe_hint, width))
    return "\n".join(lines) + "\n"
