from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

from aincrad.cli import (
    _AI_CHOICE,
    _available_intents,
    _default_run,
    _run_home_textual,
    _starting_world,
)
from aincrad.domain import ActionIntent, ActionKind, CharacterClass
from aincrad.history import HistoryArchive
from aincrad.tui.textual_app import MenuOption


class FakeInteraction:
    def __init__(self, *answers: object, name: str = "유리별") -> None:
        self.answers = iter(answers)
        self.name = name
        self.menus: list[tuple[str, tuple[MenuOption[Any], ...]]] = []
        self.text_screens: list[tuple[str, tuple[str, ...]]] = []
        self.timeline: list[str] = []

    def choose(
        self,
        title: str,
        options: Sequence[MenuOption[Any]],
        *,
        subtitle: str = "",
        context: Sequence[str] = (),
        allow_back: bool = False,
    ) -> object | None:
        self.timeline.append(title)
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
        self.timeline.append(title)
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


def test_textual_home_shows_resolved_turn_story_before_continue_choice(tmp_path: Path) -> None:
    world = _starting_world(CharacterClass.WARRIOR, "유리별")
    wait = next(
        intent
        for intent in _available_intents(world, "hero")
        if intent.action is ActionKind.WAIT
    )
    interaction = FakeInteraction(
        "start",
        CharacterClass.WARRIOR,
        wait,
        False,
        "exit",
    )

    assert _run_home_textual(
        runner=None,
        stdin=StringIO(),
        stdout=StringIO(),
        history_root=tmp_path / "history",
        interaction=interaction,
    ) == 0

    story_index = next(
        index for index, title in enumerate(interaction.timeline) if title.endswith("시간의 기록")
    )
    continue_index = interaction.timeline.index("여정 계속")
    assert story_index < continue_index
    title, lines = interaction.text_screens[0]
    rendered = "\n".join(lines)
    assert title == "1일차 00:00 · 잿불마을 · 한 시간의 기록"
    assert lines[0] != "1일차 00:00 · 잿불마을"
    assert "유리별은 잿불마을에 남아" in rendered
    assert "경험치" in rendered
    assert "HP 24/24" in rendered


def test_textual_ai_delegation_names_the_action_it_actually_resolved(tmp_path: Path) -> None:
    interaction = FakeInteraction(
        "start",
        CharacterClass.WARRIOR,
        _AI_CHOICE,
        False,
        "exit",
    )

    assert _run_home_textual(
        runner=None,
        stdin=StringIO(),
        stdout=StringIO(),
        history_root=tmp_path / "history",
        interaction=interaction,
    ) == 0

    rendered = "\n".join(interaction.text_screens[0][1])
    assert "주변 상황을 살핀 유리별은 길을 골라 고요한 심지 여관으로 향했다" in rendered
    assert "경험치" in rendered
    assert "AI가 활동" not in rendered


def test_textual_fatal_hour_shows_story_without_continue_menu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_starting_world = _starting_world

    def fragile_world(character_class: CharacterClass, hero_name: str | None = None):
        world = original_starting_world(character_class, hero_name)
        hero = world.adventurers["hero"]
        fragile = replace(hero, location_id="mossreach", stats=replace(hero.stats, hp=1))
        return replace(world, adventurers={**world.adventurers, fragile.id: fragile})

    monkeypatch.setattr("aincrad.cli._starting_world", fragile_world)
    interaction = FakeInteraction(
        "start",
        CharacterClass.MAGE,
        ActionIntent("hero", ActionKind.MOVE, target_location_id="vault-1"),
        "exit",
        name="유리별",
    )

    assert _run_home_textual(
        runner=None,
        stdin=StringIO(),
        stdout=StringIO(),
        history_root=tmp_path / "history",
        interaction=interaction,  # type: ignore[arg-type]
    ) == 0

    rendered = "\n".join(interaction.text_screens[0][1])
    assert "유리별의 HP는 0이 되었고, 이 여정은 끝났다" in rendered
    assert interaction.timeline.count("1일차 00:00 · 메아리 회랑 · 한 시간의 기록") == 1
    assert "여정 계속" not in interaction.timeline
