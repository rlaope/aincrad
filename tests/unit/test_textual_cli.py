from __future__ import annotations

from collections.abc import Callable, Sequence
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

from aincrad.cli import (
    _available_intents,
    _default_run,
    _run_home_textual,
    _starting_world,
)
from aincrad.domain import ActionKind, CharacterClass
from aincrad.history import HistoryArchive
from aincrad.tui.textual_app import MenuOption


class FakeInteraction:
    def __init__(self, *answers: object, name: str = "유리별") -> None:
        self.answers = iter(answers)
        self.name = name
        self.menus: list[tuple[str, tuple[MenuOption[Any], ...]]] = []
        self.text_screens: list[tuple[str, tuple[str, ...]]] = []

    def choose(
        self,
        title: str,
        options: Sequence[MenuOption[Any]],
        *,
        subtitle: str = "",
        context: Sequence[str] = (),
        allow_back: bool = False,
    ) -> object | None:
        self.menus.append((title, tuple(options)))
        return next(self.answers)

    def input_text(
        self,
        title: str,
        *,
        subtitle: str,
        validate: Callable[[str], str],
    ) -> str | None:
        return validate(self.name)

    def show_text(self, title: str, body_lines: Sequence[str]) -> None:
        self.text_screens.append((title, tuple(body_lines)))


def test_textual_home_uses_widget_menu_without_plain_output(tmp_path: Path) -> None:
    interaction = FakeInteraction("exit")
    output = StringIO()

    result = _run_home_textual(
        runner=None,
        stdin=StringIO(),
        stdout=output,
        history_root=tmp_path / "history",
        interaction=interaction,
    )

    assert result == 0
    assert output.getvalue() == ""
    assert interaction.menus[0][0] == "메인 메뉴"
    assert [option.label for option in interaction.menus[0][1]] == [
        "새 모험",
        "히스토리",
        "종료",
    ]


def test_default_run_routes_character_name_and_action_through_textual_widgets() -> None:
    world = _starting_world(CharacterClass.WARRIOR, "유리별")
    wait = next(
        intent
        for intent in _available_intents(world, "hero")
        if intent.action is ActionKind.WAIT
    )
    interaction = FakeInteraction(CharacterClass.WARRIOR, wait)
    output = StringIO()

    result = _default_run(
        seed=42,
        hours=1,
        headless=False,
        output=None,
        force=False,
        stdin=StringIO(),
        stdout=output,
        interaction=interaction,
    )

    assert any(adventurer.name == "유리별" for adventurer in result.adventurers)
    assert output.getvalue() == ""
    assert [title for title, _ in interaction.menus] == ["직업 선택", "유리별의 행동"]
    assert interaction.menus[-1][1][-1].label == "AI 판단에 맡기기"


def test_cancel_before_first_action_does_not_create_phantom_history(tmp_path: Path) -> None:
    interaction = FakeInteraction(CharacterClass.WARRIOR, None)
    history_root = tmp_path / "history"

    with pytest.raises(EOFError, match="행동 선택"):
        _default_run(
            seed=42,
            hours=1,
            headless=False,
            output=tmp_path / "events.jsonl",
            force=False,
            history_root=history_root,
            stdin=StringIO(),
            stdout=StringIO(),
            interaction=interaction,
        )

    assert HistoryArchive(history_root).list_runs() == ()
