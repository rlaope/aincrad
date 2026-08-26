from __future__ import annotations

from dataclasses import dataclass

from aincrad.tui.keys import Key
from aincrad.tui.menu import MenuController, MenuOutcome


@dataclass(frozen=True)
class Choice:
    label: str


def test_menu_navigates_generic_choices_and_clamps_at_boundaries() -> None:
    choices = (Choice("alpha"), Choice("beta"), Choice("gamma"))
    menu = MenuController(choices)

    assert menu.selected is choices[0]
    assert menu.handle_key(Key.UP) is None
    assert menu.selected is choices[0]

    assert menu.handle_key(Key.DOWN) is None
    assert menu.selected is choices[1]
    assert menu.handle_key(Key.DOWN) is None
    assert menu.handle_key(Key.DOWN) is None
    assert menu.selected is choices[2]


def test_menu_enter_returns_selected_non_numeric_choice() -> None:
    choices = (Choice("alpha"), Choice("beta"))
    menu = MenuController(choices)
    menu.handle_key(Key.DOWN)

    result = menu.handle_key(Key.ENTER)

    assert result is not None
    assert result.outcome is MenuOutcome.SELECTED
    assert result.value is choices[1]


def test_menu_back_returns_explicit_back_outcome() -> None:
    menu = MenuController((Choice("alpha"),))

    result = menu.handle_key(Key.BACK)

    assert result is not None
    assert result.outcome is MenuOutcome.BACK
    assert result.value is None


def test_menu_ignores_non_navigation_keys() -> None:
    choice = Choice("alpha")
    menu = MenuController((choice,))

    assert menu.handle_key(Key.UNKNOWN) is None
    assert menu.selected is choice
