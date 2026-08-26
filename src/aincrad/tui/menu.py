from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum, auto
from typing import Generic, TypeVar

from .keys import Key

T = TypeVar("T")


class MenuOutcome(Enum):
    SELECTED = auto()
    BACK = auto()


@dataclass(frozen=True)
class MenuResult(Generic[T]):
    outcome: MenuOutcome
    value: T | None = None


class MenuController(Generic[T]):
    """Drive a non-numeric menu using logical keyboard actions."""

    def __init__(self, choices: Sequence[T]) -> None:
        if not choices:
            raise ValueError("menu requires at least one choice")
        self._choices = tuple(choices)
        self._selected_index = 0

    @property
    def selected_index(self) -> int:
        return self._selected_index

    @property
    def selected(self) -> T:
        return self._choices[self._selected_index]

    def handle_key(self, key: Key) -> MenuResult[T] | None:
        if key is Key.UP:
            self._selected_index = max(0, self._selected_index - 1)
        elif key is Key.DOWN:
            self._selected_index = min(len(self._choices) - 1, self._selected_index + 1)
        elif key is Key.ENTER:
            return MenuResult(MenuOutcome.SELECTED, self.selected)
        elif key is Key.BACK:
            return MenuResult(MenuOutcome.BACK)
        return None
