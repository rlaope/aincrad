from __future__ import annotations

import unicodedata
from dataclasses import FrozenInstanceError

import pytest

from aincrad.tui.renderer import sanitize_terminal_text
from aincrad.tui.screens import MenuChoice, render_menu, render_status_context


def _display_width(text: str) -> int:
    return sum(
        0
        if unicodedata.combining(character)
        else 2
        if unicodedata.east_asian_width(character) in {"F", "W"}
        else 1
        for character in text
    )


def test_renders_branded_panel_context_and_strong_selected_card() -> None:
    screen = render_menu(
        "행동 선택",
        (
            MenuChoice("Mossreach Wilds로 이동", "비에 젖은 구릉으로 향합니다"),
            MenuChoice("AI 판단에 맡기기", "관찰 가능한 정보로 결정합니다"),
        ),
        1,
        subtitle="다음 한 시간의 행동을 고르세요",
        context=("1일차 · 03:00", "Emberfall · HP 24/24 · MP 8/8"),
        allow_back=True,
        width=60,
    )

    lines = screen.splitlines()
    assert lines[0] == "╭" + "─" * 58 + "╮"
    assert "THE GLASS FRONTIER" in screen
    assert "행동 선택" in screen
    assert "1일차 · 03:00" in screen
    assert "◆ AI 판단에 맡기기" in screen
    assert "관찰 가능한 정보로 결정합니다" in screen
    assert "↑↓ / W S" in screen
    assert "Esc" in screen
    assert lines[-1] == "╰" + "─" * 58 + "╯"
    assert all(_display_width(line) == 60 for line in lines)


@pytest.mark.parametrize("width", [40, 60, 80])
def test_every_menu_line_respects_terminal_display_width(width: int) -> None:
    screen = render_menu(
        "긴 한글 제목과 English title",
        (
            MenuChoice("별빛이 스며드는 아주 긴 이동 경로", "설명도 안전하게 줄바꿈됩니다"),
            MenuChoice("AI 판단에 맡기기", "마지막 선택지는 항상 유지됩니다"),
        ),
        0,
        context=("긴 상태 문자열 · HP 24/24 · MP 8/8 · 파티 2명",),
        width=width,
    )

    assert all(_display_width(line) == width for line in screen.splitlines())


def test_status_context_keeps_decision_information_at_wide_and_narrow_widths() -> None:
    wide = render_status_context(
        day=1,
        hour=3,
        location="Emberfall",
        hp=6,
        max_hp=24,
        mp=8,
        max_mp=8,
        level=2,
        party_size=1,
        gold=17,
        resources=3,
        width=80,
    )
    narrow = render_status_context(
        day=1,
        hour=3,
        location="Emberfall",
        hp=6,
        max_hp=24,
        mp=8,
        max_mp=8,
        level=2,
        party_size=1,
        gold=17,
        resources=3,
        width=40,
    )

    assert wide == (
        "1일차 03:00 · Emberfall · HP !6/24 · MP 8/8 · Lv.2 · 파티 1명",
        "소지품: 자원 3개 · 소지금 17 G",
    )
    assert narrow == (
        "1일차 03:00 · Emberfall",
        "HP !6/24 · MP 8/8 · Lv.2 · 파티 1명",
        "소지품: 자원 3개 · 소지금 17 G",
    )


def test_renders_korean_choices_without_numeric_prefixes_and_marks_selection() -> None:
    choices = (
        MenuChoice("새 모험", "새로운 여정을 시작합니다"),
        MenuChoice("이어하기", "기록된 여정을 불러옵니다"),
    )

    screen = render_menu("The Glass Frontier", choices, 1)

    assert "◆ THE GLASS FRONTIER" in screen
    assert "  새 모험" in screen
    assert "◆ 이어하기" in screen
    assert "↳ 기록된 여정을 불러옵니다" in screen
    assert "새로운 여정을 시작합니다" not in screen
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
    assert "기록�[2J" in screen
    assert "◆ 보기�" in screen
    assert "↳ 설명�" in screen
    assert "이동� · Esc 뒤로" in screen
    assert all(_display_width(line) == 80 for line in screen.splitlines())


def test_neutralizes_unattached_marks_without_removing_attached_marks() -> None:
    screen = render_menu(
        "\u0301기록",
        (MenuChoice("e\u0301", "설명 \ufe0f"),),
        0,
    )

    assert "�기록" in screen
    assert "◆ e\u0301" in screen
    assert "설명 �" in screen


def test_neutralizes_invalid_emoji_modifiers_and_preserves_valid_one() -> None:
    screen = render_menu(
        "👍🏽",
        (MenuChoice("👍🏽🏽"), MenuChoice("🚗🏽"), MenuChoice("🇰🏽")),
        0,
    )

    assert "│ 👍🏽" in screen
    assert "◆ 👍🏽�" in screen
    assert "🚗�" in screen
    assert "🇰�" in screen


def test_sanitizer_is_idempotent_for_unassigned_unicode_15_modifier_bases() -> None:
    text = "\U0001FAF7🏽\U0001FAF8🏽"
    sanitized = sanitize_terminal_text(text)

    assert sanitize_terminal_text(sanitized) == sanitized
    assert sanitized == "����"


@pytest.mark.parametrize("text", ["\x1b[2J", "\u202eABC", "🇰🇰\u0301A"])
def test_sanitizer_and_display_units_share_safe_projection(text: str) -> None:
    from aincrad.domain.display import display_units

    expected = "".join(unit for unit, _width in display_units(text))
    sanitized = sanitize_terminal_text(text)

    assert sanitized == expected
    assert sanitize_terminal_text(sanitized) == sanitized


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

    assert all(_display_width(line) == 40 for line in narrow.splitlines())
    assert all(_display_width(line) == 80 for line in wide.splitlines())
    assert narrow.count("가") == 25
    assert narrow.count("나") == 25
    assert wide.count("가") == 25
    assert wide.count("나") == 25


def test_menu_keeps_selected_choice_visible_within_terminal_height() -> None:
    choices = tuple(
        MenuChoice(f"{index}회차 · 모험가", "상세 기록을 엽니다")
        for index in range(1, 21)
    )

    screen = render_menu(
        "히스토리 선택",
        choices,
        19,
        width=40,
        height=12,
    )

    assert len(screen.splitlines()) <= 12
    assert "◆ 20회차 · 모험가" in screen
    assert "1회차 · 모험가" not in screen
    assert "Enter 선택" in screen


def test_menu_bounds_wrapped_hint_while_preserving_selected_row() -> None:
    screen = render_menu(
        "선택",
        (MenuChoice("보이는 선택", "설명"),),
        0,
        width=40,
        height=8,
        hint="아주 긴 키 도움말 " * 12,
    )

    assert len(screen.splitlines()) <= 8
    assert "◆ 보이는 선택" in screen


def test_selection_movement_changes_only_marker_and_preserves_ai_choice_last() -> None:
    choices = (
        MenuChoice("탐색"),
        MenuChoice("휴식"),
        MenuChoice("AI 판단에 맡기기"),
    )

    first = render_menu("행동 선택", choices, 0)
    last = render_menu("행동 선택", choices, 2)

    assert "◆ 탐색" in first
    assert "  AI 판단에 맡기기" in first
    assert "  탐색" in last
    assert "◆ AI 판단에 맡기기" in last
    assert "> " not in first + last
    assert first.index("AI 판단에 맡기기") > first.index("휴식")
    assert last.index("AI 판단에 맡기기") > last.index("휴식")
