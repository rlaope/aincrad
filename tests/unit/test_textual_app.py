from __future__ import annotations

import asyncio

from textual.color import Color
from textual.widgets import Input, Static

from aincrad.domain.identity import validate_hero_name
from aincrad.tui.textual_app import (
    AincradTextualApp,
    MenuOption,
    MenuScreen,
    NameScreen,
    TextScreen,
)


def test_textual_menu_uses_widgets_and_returns_keyboard_selection() -> None:
    selections: list[str | None] = []

    def session(ui):  # type: ignore[no-untyped-def]
        selections.append(
            ui.choose(
                "메인 메뉴",
                (
                    MenuOption("새 모험", "첫 시간을 시작합니다", "start"),
                    MenuOption("히스토리", "기록을 열람합니다", "history"),
                    MenuOption("종료", "터미널로 돌아갑니다", "exit"),
                ),
                subtitle="새로운 여정을 시작하거나 기록된 모험을 열람합니다",
            )
        )
        return 0

    async def exercise() -> None:
        app = AincradTextualApp(session)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            assert isinstance(app.screen, MenuScreen)
            assert "THE GLASS FRONTIER" in app.screen.snapshot_text
            await pilot.press("down", "enter")
            await pilot.pause()

    asyncio.run(exercise())
    assert selections == ["history"]


def test_textual_menu_uses_the_designed_amber_focus_color() -> None:
    def session(ui):  # type: ignore[no-untyped-def]
        ui.choose(
            "메인 메뉴",
            (MenuOption("새 모험", "첫 시간을 시작합니다", "start"),),
        )
        return 0

    async def exercise() -> None:
        app = AincradTextualApp(session)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            item = app.screen.query_one("#option-0")
            assert item.styles.background == Color.parse("#694c2b")
            await pilot.press("escape")

    asyncio.run(exercise())


def test_textual_menu_reflows_inside_narrow_terminal() -> None:
    def session(ui):  # type: ignore[no-untyped-def]
        return 0 if ui.choose(
            "메인 메뉴",
            (
                MenuOption("새 모험", "직업과 이름을 정해 첫 시간을 시작합니다", "start"),
                MenuOption("히스토리", "기록된 회차와 이야기 일지를 살펴봅니다", "history"),
                MenuOption("종료", "터미널로 돌아갑니다", "exit"),
            ),
        ) is not None else 0

    async def exercise() -> None:
        app = AincradTextualApp(session)
        async with app.run_test(size=(40, 12)) as pilot:
            await pilot.pause()
            assert isinstance(app.screen, MenuScreen)
            panel = app.screen.query_one("#dialog")
            assert panel.region.x >= 0
            assert panel.region.y >= 0
            assert panel.region.right <= 40
            assert panel.region.bottom <= 12
            assert "새 모험" in app.screen.snapshot_text
            await pilot.resize_terminal(100, 24)
            await pilot.pause()
            assert panel.region.right <= 100
            assert panel.region.bottom <= 24
            await pilot.press("enter")

    asyncio.run(exercise())


def test_three_home_options_fit_inside_a_40_by_24_viewport() -> None:
    def session(ui):  # type: ignore[no-untyped-def]
        ui.choose(
            "메인 메뉴",
            (
                MenuOption("새 모험", "직업과 이름을 정해 첫 시간을 시작합니다", "start"),
                MenuOption("히스토리", "저장된 여정의 시간별 기록을 엽니다", "history"),
                MenuOption("종료", "터미널로 돌아갑니다", "exit"),
            ),
            subtitle="새로운 여정을 시작하거나 기록된 모험을 열람합니다",
        )
        return 0

    async def exercise() -> None:
        app = AincradTextualApp(session)
        async with app.run_test(size=(40, 24)) as pilot:
            for _ in range(20):
                await pilot.pause(0.05)
                if app.screen.query("#menu"):
                    break
            choices = app.screen.query_one("#menu").region
            items = list(app.screen.query("ListItem"))
            assert len(items) == 3
            assert all(
                choices.y <= item.region.y
                and item.region.bottom <= choices.bottom
                and item.region.height > 0
                for item in items
            )
            await pilot.press("escape")

    asyncio.run(exercise())


def test_textual_name_input_accepts_korean_and_reports_validation() -> None:
    names: list[str | None] = []

    def session(ui):  # type: ignore[no-untyped-def]
        names.append(
            ui.input_text(
                "주인공 이름",
                subtitle="모험 중 표시할 이름을 정하세요",
                validate=validate_hero_name,
            )
        )
        return 0

    async def exercise() -> None:
        app = AincradTextualApp(session)
        async with app.run_test(size=(60, 16)) as pilot:
            await pilot.pause()
            assert isinstance(app.screen, NameScreen)
            await pilot.press("유", "리", "별", "enter")
            await pilot.pause()

    asyncio.run(exercise())
    assert names == ["유리별"]


def test_session_failure_returns_nonzero_exit_status() -> None:
    def session(_ui):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")

    assert AincradTextualApp(session).run(headless=True) == 1


def test_menu_without_back_does_not_honor_hidden_cancel_keys() -> None:
    selections: list[str | None] = []

    def session(ui):  # type: ignore[no-untyped-def]
        selections.append(
            ui.choose(
                "행동 선택",
                (MenuOption("기다리기", "한 시간을 보냅니다", "wait"),),
            )
        )
        return 0

    async def exercise() -> None:
        app = AincradTextualApp(session)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            await pilot.press("escape", "q")
            await pilot.pause()
            assert isinstance(app.screen, MenuScreen)
            await pilot.press("enter")

    asyncio.run(exercise())
    assert selections == ["wait"]


def test_menu_sanitizes_option_labels_and_descriptions() -> None:
    def session(ui):  # type: ignore[no-untyped-def]
        ui.choose(
            "메인 메뉴",
            (MenuOption("안전\x1b[31m\u202e", "설명\x00\u2066", "value"),),
        )
        return 0

    async def exercise() -> None:
        app = AincradTextualApp(session)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            rendered = str(app.screen.query_one("#option-0 Static", Static).content)
            assert "\x1b" not in rendered
            assert "\x00" not in rendered
            assert "\u202e" not in rendered
            assert "\u2066" not in rendered
            await pilot.press("enter")

    asyncio.run(exercise())


def test_text_screen_scrolls_with_w_and_s() -> None:
    def session(ui):  # type: ignore[no-untyped-def]
        ui.show_text("긴 기록", tuple(f"기록 {index}" for index in range(100)))
        return 0

    async def exercise() -> None:
        app = AincradTextualApp(session)
        async with app.run_test(size=(40, 12)) as pilot:
            await pilot.pause()
            assert isinstance(app.screen, TextScreen)
            scroll = app.screen.query_one("#text-scroll")
            assert scroll.scroll_y == 0
            await pilot.press("s")
            await pilot.pause()
            assert scroll.scroll_y > 0
            await pilot.press("w")
            await pilot.pause()
            assert scroll.scroll_y == 0
            await pilot.press("enter")

    asyncio.run(exercise())


def test_name_input_sanitizes_inserted_text_before_live_render() -> None:
    def session(ui):  # type: ignore[no-untyped-def]
        ui.input_text(
            "주인공 이름",
            subtitle="이름을 정하세요",
            validate=lambda value: value,
        )
        return 0

    async def exercise() -> None:
        app = AincradTextualApp(session)
        async with app.run_test(size=(60, 16)) as pilot:
            await pilot.pause()
            name_input = app.screen.query_one("#name", Input)
            name_input.insert_text_at_cursor("A\u202eB\u2066C\x1b[31mD\x00E")
            await pilot.pause()
            assert "\u202e" not in name_input.value
            assert "\u2066" not in name_input.value
            assert "\x1b" not in name_input.value
            assert "\x00" not in name_input.value
            await pilot.press("enter")

    asyncio.run(exercise())
