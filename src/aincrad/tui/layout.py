from __future__ import annotations

from collections.abc import Sequence

from aincrad.domain.display import display_units
from aincrad.domain.display import display_width as display_width

MIN_TERMINAL_WIDTH = 40
MAX_CONTENT_WIDTH = 100
_BRAND = "◆ THE GLASS FRONTIER"


def clip_display(text: str, width: int) -> str:
    if width < 0:
        raise ValueError("width must not be negative")
    units = display_units(text)
    if sum(cell_width for _unit, cell_width in units) <= width:
        return "".join(unit for unit, _cell_width in units)
    if width == 0:
        return ""
    if width == 1:
        return "…"
    result: list[str] = []
    used = 0
    for unit, cell_width in units:
        if used + cell_width > width - 1:
            break
        result.append(unit)
        used += cell_width
    return "".join(result) + "…"


def pad_display(text: str, width: int) -> str:
    clipped = clip_display(text, width)
    return clipped + " " * (width - display_width(clipped))


def _split_token(token: str, width: int) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    used = 0
    for unit, cell_width in display_units(token):
        if cell_width > width:
            if current:
                chunks.append("".join(current))
                current = []
                used = 0
            chunks.append("�")
            continue
        if current and used + cell_width > width:
            chunks.append("".join(current))
            current = []
            used = 0
        current.append(unit)
        used += cell_width
    if current or not chunks:
        chunks.append("".join(current))
    return chunks


def wrap_display(text: str, width: int) -> list[str]:
    """Wrap at spaces when possible, falling back to cell-safe character chunks."""

    if width <= 0:
        raise ValueError("width must be positive")
    lines: list[str] = []
    paragraphs = text.split("\n")
    for paragraph in paragraphs:
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for word in paragraph.split(" "):
            safe_word = "".join(unit for unit, _width in display_units(word))
            candidate = safe_word if not current else f"{current} {safe_word}"
            if display_width(candidate) <= width:
                current = candidate
                continue
            if current:
                lines.append(current)
                current = ""
            chunks = _split_token(safe_word, width)
            lines.extend(chunks[:-1])
            current = chunks[-1]
        lines.append(current)
    return lines or [""]


def panel(body_lines: Sequence[str], width: int) -> list[str]:
    """Build the one canonical branded panel used by interactive screens."""

    if not MIN_TERMINAL_WIDTH <= width <= MAX_CONTENT_WIDTH:
        raise ValueError("width must be between 40 and 100")
    content_width = width - 4

    def row(text: str = "") -> str:
        return f"│ {pad_display(text, content_width)} │"

    return [
        "╭" + "─" * (width - 2) + "╮",
        row(_BRAND),
        "├" + "─" * (width - 2) + "┤",
        *(row(line) for line in body_lines),
        "╰" + "─" * (width - 2) + "╯",
    ]
