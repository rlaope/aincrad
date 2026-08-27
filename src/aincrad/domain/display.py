from __future__ import annotations

import unicodedata

# Unicode 14.0 emoji-data.txt, Emoji_Modifier_Base=Yes.
_EMOJI_MODIFIER_BASE_RANGES = (
    (0x261D, 0x261D),
    (0x26F9, 0x26F9),
    (0x270A, 0x270C),
    (0x270D, 0x270D),
    (0x1F385, 0x1F385),
    (0x1F3C2, 0x1F3C4),
    (0x1F3C7, 0x1F3C7),
    (0x1F3CA, 0x1F3CA),
    (0x1F3CB, 0x1F3CC),
    (0x1F442, 0x1F443),
    (0x1F446, 0x1F450),
    (0x1F466, 0x1F46B),
    (0x1F46C, 0x1F46D),
    (0x1F46E, 0x1F478),
    (0x1F47C, 0x1F47C),
    (0x1F481, 0x1F483),
    (0x1F485, 0x1F487),
    (0x1F48F, 0x1F48F),
    (0x1F491, 0x1F491),
    (0x1F4AA, 0x1F4AA),
    (0x1F574, 0x1F575),
    (0x1F57A, 0x1F57A),
    (0x1F590, 0x1F590),
    (0x1F595, 0x1F596),
    (0x1F645, 0x1F647),
    (0x1F64B, 0x1F64F),
    (0x1F6A3, 0x1F6A3),
    (0x1F6B4, 0x1F6B5),
    (0x1F6B6, 0x1F6B6),
    (0x1F6C0, 0x1F6C0),
    (0x1F6CC, 0x1F6CC),
    (0x1F90C, 0x1F90C),
    (0x1F90F, 0x1F90F),
    (0x1F918, 0x1F918),
    (0x1F919, 0x1F91E),
    (0x1F91F, 0x1F91F),
    (0x1F926, 0x1F926),
    (0x1F930, 0x1F930),
    (0x1F931, 0x1F932),
    (0x1F933, 0x1F939),
    (0x1F93C, 0x1F93E),
    (0x1F977, 0x1F977),
    (0x1F9B5, 0x1F9B6),
    (0x1F9B8, 0x1F9B9),
    (0x1F9BB, 0x1F9BB),
    (0x1F9CD, 0x1F9CF),
    (0x1F9D1, 0x1F9DD),
    (0x1FAC3, 0x1FAC5),
    (0x1FAF0, 0x1FAF6),
)


def character_width(character: str) -> int:
    """Return the standalone terminal-cell width for one Unicode scalar."""

    category = unicodedata.category(character)
    if category.startswith(("C", "M")):
        return 0
    return 2 if unicodedata.east_asian_width(character) in {"F", "W"} else 1


def display_units(text: str) -> list[tuple[str, int]]:
    """Segment supported terminal graphemes into deterministic display units."""

    units: list[tuple[str, int]] = []
    index = 0
    while index < len(text):
        character = text[index]
        if not character.isprintable() or unicodedata.category(character).startswith("C"):
            units.append(("�", 1))
            index += 1
            continue
        if _is_extender_scalar(character):
            units.append(("�", 1))
            index += 1
            continue
        cluster = character
        width = character_width(character)
        index += 1

        if _is_regional_indicator(character) and index < len(text):
            following = text[index]
            if _is_regional_indicator(following):
                units.append((cluster + following, 2))
                index += 1
                continue

        base = character
        has_modifier = False
        while index < len(text):
            following = text[index]
            codepoint = ord(following)
            if unicodedata.category(following).startswith("M"):
                if is_unattached_extender(text, index):
                    break
                cluster += following
                if following == "\ufe0f" and _accepts_emoji_variation(base):
                    width = max(width, 2)
                if following == "\u20e3":
                    width = 2
                index += 1
                continue
            if 0x1F3FB <= codepoint <= 0x1F3FF:
                if has_modifier or is_unattached_extender(text, index):
                    break
                cluster += following
                width = max(width, 2)
                has_modifier = True
                index += 1
                continue
            break
        units.append((cluster, width))
    return units


def display_width(text: str) -> int:
    return sum(width for _unit, width in display_units(text))


def safe_terminal_text(text: str) -> str:
    """Return the canonical control-free terminal projection for ``text``."""

    return "".join(unit for unit, _width in display_units(text))


def is_unattached_extender(text: str, index: int) -> bool:
    if index < 0 or index >= len(text):
        raise ValueError("index must be a valid text index")
    character = text[index]
    codepoint = ord(character)
    if character == "\u200d":
        return True
    if 0x1F3FB <= codepoint <= 0x1F3FF:
        return index == 0 or not is_emoji_modifier_base(text[index - 1])
    if not unicodedata.category(character).startswith("M"):
        return False
    if index == 0:
        return True
    previous = text[index - 1]
    if character in {"\ufe0e", "\ufe0f"}:
        return previous.isspace() or unicodedata.category(previous).startswith(("C", "M"))
    if character == "\u20e3":
        base_index = index - 2 if previous in {"\ufe0e", "\ufe0f"} else index - 1
        return base_index < 0 or text[base_index] not in "#*0123456789"
    return previous.isspace() or unicodedata.category(previous).startswith("C")


def is_emoji_modifier_base(character: str) -> bool:
    codepoint = ord(character)
    return any(start <= codepoint <= end for start, end in _EMOJI_MODIFIER_BASE_RANGES)


def _accepts_emoji_variation(character: str) -> bool:
    codepoint = ord(character)
    return (
        codepoint
        in {
            0x00A9,
            0x00AE,
            0x203C,
            0x2049,
            0x2122,
            0x2139,
            0x3030,
            0x303D,
            0x3297,
            0x3299,
        }
        or 0x2190 <= codepoint <= 0x27BF
        or 0x2934 <= codepoint <= 0x2935
        or 0x2B00 <= codepoint <= 0x2BFF
    )


def _is_regional_indicator(character: str) -> bool:
    return 0x1F1E6 <= ord(character) <= 0x1F1FF


def _is_extender_scalar(character: str) -> bool:
    codepoint = ord(character)
    return (
        character == "\u200d"
        or 0x1F3FB <= codepoint <= 0x1F3FF
        or unicodedata.category(character).startswith("M")
    )
