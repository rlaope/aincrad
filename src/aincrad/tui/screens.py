from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from aincrad.tui.layout import (
    MIN_TERMINAL_WIDTH,
    clip_display,
    pad_display,
    panel,
    wrap_display,
)
from aincrad.tui.renderer import sanitize_terminal_text

_DEFAULT_HINT = "↑↓ / W S 이동 · Enter 선택"


@dataclass(frozen=True, slots=True)
class MenuChoice:
    """One immutable choice in a terminal menu projection."""

    label: str
    description: str = ""


def render_status_context(
    *,
    day: int,
    hour: int,
    location: str,
    hp: int,
    max_hp: int,
    mp: int,
    max_mp: int,
    level: int,
    party_size: int,
    width: int,
) -> tuple[str, ...]:
    """Project the fixed decision context for action and continue screens."""

    safe_location = sanitize_terminal_text(location)
    hp_value = f"!{hp}" if max_hp > 0 and hp * 4 <= max_hp else str(hp)
    time_location = f"{day}일차 {hour:02d}:00 · {safe_location}"
    vitals = (
        f"HP {hp_value}/{max_hp} · MP {mp}/{max_mp} · "
        f"Lv.{level} · 파티 {party_size}명"
    )
    if width < 56:
        return (time_location, vitals)
    return (f"{time_location} · {vitals}",)


def _safe_wrapped(text: str, width: int) -> list[str]:
    return wrap_display(sanitize_terminal_text(text), width)


def render_menu(
    title: str,
    choices: Sequence[MenuChoice],
    selected_index: int,
    *,
    subtitle: str = "",
    context: Sequence[str] = (),
    hint: str = _DEFAULT_HINT,
    allow_back: bool = False,
    width: int = 80,
    height: int | None = None,
) -> str:
    """Render one deterministic branded Korean menu without terminal I/O."""

    if not choices:
        raise ValueError("choices must not be empty")
    if not 0 <= selected_index < len(choices):
        raise ValueError("selected_index out of range")
    if width < MIN_TERMINAL_WIDTH:
        raise ValueError("width must be at least 40")
    if width > 100:
        raise ValueError("width must not exceed 100")
    if height is not None and height < 8:
        return render_text_screen(
            "터미널 높이를 8행 이상으로 늘려 주세요",
            (),
            hint="",
            width=width,
            height=height,
        )

    content_width = width - 4
    prefix = _safe_wrapped(title, content_width)
    if subtitle:
        prefix.extend(_safe_wrapped(subtitle, content_width))
    if context:
        prefix.append("")
        for item in context:
            prefix.extend(_safe_wrapped(item, content_width))
    prefix.append("")

    choice_blocks: list[list[str]] = []
    for index, choice in enumerate(choices):
        label = sanitize_terminal_text(choice.label)
        marker = "◆ " if index == selected_index else "  "
        wrapped_label = wrap_display(label, content_width - 2)
        block = [marker + wrapped_label[0]]
        block.extend("  " + line for line in wrapped_label[1:])
        if index == selected_index and choice.description:
            description = sanitize_terminal_text(choice.description)
            wrapped_description = wrap_display(description, content_width - 4)
            block.append("  ↳ " + wrapped_description[0])
            block.extend("    " + line for line in wrapped_description[1:])
        choice_blocks.append(block)

    safe_hint = sanitize_terminal_text(hint)
    if allow_back:
        safe_hint = f"{safe_hint} · Esc 뒤로"
    hint_lines = wrap_display(safe_hint, content_width) if safe_hint else []
    if height is None:
        visible_blocks = choice_blocks
        suffix = ["", *hint_lines]
    else:
        body_budget = height - 4
        selected_block = choice_blocks[selected_index]
        reserved_selected = min(len(selected_block), body_budget)
        suffix_budget = max(0, body_budget - reserved_selected)
        if suffix_budget == 0:
            suffix = []
        elif suffix_budget == 1:
            suffix = hint_lines[:1]
        else:
            suffix = ["", *hint_lines[: suffix_budget - 1]]
        selected_budget = max(1, body_budget - len(suffix))
        if len(selected_block) > selected_budget:
            selected_block = selected_block[:selected_budget]
        prefix_budget = max(0, body_budget - len(suffix) - len(selected_block))
        prefix = prefix[:prefix_budget]
        remaining = body_budget - len(prefix) - len(suffix) - len(selected_block)
        first = selected_index
        last = selected_index + 1
        visible_blocks = [selected_block]
        while remaining > 0:
            added = False
            if first > 0 and len(choice_blocks[first - 1]) <= remaining:
                first -= 1
                visible_blocks.insert(0, choice_blocks[first])
                remaining -= len(choice_blocks[first])
                added = True
            if last < len(choice_blocks) and len(choice_blocks[last]) <= remaining:
                visible_blocks.append(choice_blocks[last])
                remaining -= len(choice_blocks[last])
                last += 1
                added = True
            if not added:
                break
    lines = [*prefix]
    for block in visible_blocks:
        lines.extend(block)
    lines.extend(suffix)
    return "\n".join(panel(lines, width)) + "\n"


def render_text_screen(
    title: str,
    body_lines: Sequence[str],
    *,
    hint: str,
    width: int = 80,
    height: int | None = None,
) -> str:
    """Render non-menu interactive content in the same branded panel."""

    if width < MIN_TERMINAL_WIDTH:
        raise ValueError("width must be at least 40")
    if width > 100:
        raise ValueError("width must not exceed 100")
    content_width = width - 4
    if height is not None and height < 4:
        safe_title = sanitize_terminal_text(title)
        line = pad_display(clip_display(safe_title, width), width)
        return "\n".join(line for _ in range(max(1, height))) + "\n"
    title_lines, hint_lines, separators, body_capacity = _text_screen_layout(
        title,
        hint,
        width=width,
        height=height,
    )
    lines = [*title_lines]
    if separators:
        lines.append("")
    for body_line in body_lines:
        lines.extend(_safe_wrapped(body_line, content_width))
    if body_capacity is not None:
        body_start = len(title_lines) + (1 if separators else 0)
        lines = lines[: body_start + body_capacity]
    if separators == 2:
        lines.append("")
    lines.extend(hint_lines)
    return "\n".join(panel(lines, width)) + "\n"


def text_screen_body_capacity(
    title: str,
    hint: str,
    *,
    width: int,
    height: int,
) -> int:
    """Return body rows available inside a height-bounded text panel."""

    return _text_screen_layout(title, hint, width=width, height=height)[3] or 0


def _text_screen_layout(
    title: str,
    hint: str,
    *,
    width: int,
    height: int | None,
) -> tuple[list[str], list[str], int, int | None]:
    content_width = width - 4
    title_lines = _safe_wrapped(title, content_width)
    hint_lines = _safe_wrapped(hint, content_width) if hint else []
    if height is None:
        return title_lines, hint_lines, 2, None
    body_budget = max(0, height - 4)
    if body_budget == 0:
        return [], [], 0, 0
    kept_title = title_lines[:1]
    kept_hint = hint_lines[:1] if body_budget >= 2 else []
    remaining = body_budget - len(kept_title) - len(kept_hint)
    if len(title_lines) > 1 and remaining > 3:
        kept_title.append(title_lines[1])
        remaining -= 1
    if len(hint_lines) > 1 and remaining > 3:
        kept_hint.append(hint_lines[1])
        remaining -= 1
    separators = min(2, max(0, remaining - 1))
    body_capacity = max(0, remaining - separators)
    return kept_title, kept_hint, separators, body_capacity
