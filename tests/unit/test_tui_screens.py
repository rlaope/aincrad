from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from aincrad.tui.screens import MenuChoice, render_menu


def test_renders_korean_choices_without_numeric_prefixes_and_marks_selection() -> None:
    choices = (
        MenuChoice("새 모험", "새로운 여정을 시작합니다"),
        MenuChoice("이어하기", "기록된 여정을 불러옵니다"),
    )

    screen = render_menu("The Glass Frontier", choices, 1)

    assert screen == (
        "The Glass Frontier\n"
        "\n"
        "  새 모험 — 새로운 여정을 시작합니다\n"
        "> 이어하기 — 기록된 여정을 불러옵니다\n"
        "\n"
        "↑/↓ 또는 W/S로 이동 · Enter로 선택\n"
    )
    assert "1." not in screen
    assert "2." not in screen


def test_menu_choice_is_immutable() -> None:
    choice = MenuChoice("새 모험")

    with pytest.raises(FrozenInstanceError):
        choice.label = "이어하기"  # type: ignore[misc]


def test_neutralizes_controls_in_all_content_and_adds_back_hint() -> None:
    screen = render_menu(
        "기록\x1b[2J",
        (MenuChoice("보기\n", "설명\u202e"),),
        0,
        hint="이동\r",
        allow_back=True,
    )

    assert "\x1b" not in screen
    assert "\u202e" not in screen
    assert screen == "기록�[2J\n\n> 보기� — 설명�\n\n이동� · Esc로 뒤로\n"


@pytest.mark.parametrize(
    ("choices", "selected_index", "width", "message"),
    [
        ((), 0, 80, "choices must not be empty"),
        ((MenuChoice("새 모험"),), -1, 80, "selected_index out of range"),
        ((MenuChoice("새 모험"),), 1, 80, "selected_index out of range"),
        ((MenuChoice("새 모험"),), 0, 39, "width must be at least 40"),
    ],
)
def test_rejects_empty_choices_invalid_index_and_narrow_width(
    choices: tuple[MenuChoice, ...],
    selected_index: int,
    width: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        render_menu("메뉴", choices, selected_index, width=width)


def test_wraps_korean_safely_at_40_columns_and_keeps_it_on_one_line_at_80() -> None:
    title = "가" * 25
    choices = (MenuChoice("나" * 25),)

    narrow = render_menu(title, choices, 0, width=40)
    wide = render_menu(title, choices, 0, width=80)

    assert narrow == (
        f"{'가' * 20}\n"
        f"{'가' * 5}\n"
        "\n"
        f"> {'나' * 19}\n"
        f"  {'나' * 6}\n"
        "\n"
        "↑/↓ 또는 W/S로 이동 · Enter로 선택\n"
    )
    assert wide == (
        f"{'가' * 25}\n"
        "\n"
        f"> {'나' * 25}\n"
        "\n"
        "↑/↓ 또는 W/S로 이동 · Enter로 선택\n"
    )


def test_selection_movement_changes_only_marker_and_preserves_ai_choice_last() -> None:
    choices = (
        MenuChoice("탐색"),
        MenuChoice("휴식"),
        MenuChoice("AI 판단에 맡기기"),
    )

    first = render_menu("행동 선택", choices, 0)
    last = render_menu("행동 선택", choices, 2)

    assert first == (
        "행동 선택\n\n> 탐색\n  휴식\n  AI 판단에 맡기기\n\n"
        "↑/↓ 또는 W/S로 이동 · Enter로 선택\n"
    )
    assert last == (
        "행동 선택\n\n  탐색\n  휴식\n> AI 판단에 맡기기\n\n"
        "↑/↓ 또는 W/S로 이동 · Enter로 선택\n"
    )
