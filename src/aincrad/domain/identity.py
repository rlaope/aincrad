"""Stable hero identity and display-name validation."""

import unicodedata

from aincrad.domain.display import display_width, is_unattached_extender

HERO_ID = "hero"
MAX_HERO_NAME_CELLS = 24


class HeroNameError(ValueError):
    """Raised when a hero display name is invalid."""


def validate_hero_name(raw: str) -> str:
    """Return a hero display name with surrounding whitespace removed."""
    if not isinstance(raw, str):
        raise TypeError("hero name must be a str")

    name = raw.strip()
    if not name:
        raise HeroNameError("hero name cannot be empty")
    if _has_unsupported_sequence(name):
        raise HeroNameError("hero name contains an unsupported Unicode sequence")
    if any(unicodedata.category(character).startswith("C") for character in name):
        raise HeroNameError("hero name cannot contain control or format characters")

    cells = display_width(name)
    if cells == 0:
        raise HeroNameError("hero name must occupy display cells")
    if cells > MAX_HERO_NAME_CELLS:
        raise HeroNameError(f"hero name cannot exceed {MAX_HERO_NAME_CELLS} display cells")
    return name


def _has_unsupported_sequence(name: str) -> bool:
    return any(is_unattached_extender(name, index) for index in range(len(name)))
