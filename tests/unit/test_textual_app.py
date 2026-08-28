from __future__ import annotations

import asyncio
import threading

from textual.color import Color
from textual.widgets import Input, Label, Static

from aincrad.domain.identity import validate_hero_name
from aincrad.tui.textual_app import (
    AincradTextualApp,
    MenuOption,
    MenuScreen,
    NameScreen,
    StoryScreen,
    TextInputScreen,
    TextScreen,
    TextualInteraction,
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


def test_four_home_options_fit_inside_a_40_by_24_viewport() -> None:
    def session(ui):  # type: ignore[no-untyped-def]
        ui.choose(
            "메인 메뉴",
            (
                MenuOption("새 모험", "직업과 이름을 정해 첫 시간을 시작합니다", "start"),
                MenuOption(
                    "스토리 AI",
                    "Kimi 자유 서사 또는 로컬 fallback을 선택합니다",
                    "commentator",
                ),
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
            assert len(items) == 4
            assert all(
                choices.y <= item.region.y
                and item.region.bottom <= choices.bottom
                and item.region.height > 0
                for item in items
            )
            await pilot.press("escape")

    asyncio.run(exercise())


def test_menu_options_have_visible_vertical_separation() -> None:
    def session(ui):  # type: ignore[no-untyped-def]
        ui.choose(
            "메인 메뉴",
            (
                MenuOption("새 모험", "직업과 이름을 정해 첫 시간을 시작합니다", "start"),
                MenuOption("히스토리", "기록된 회차와 이야기 일지를 살펴봅니다", "history"),
                MenuOption("종료", "터미널로 돌아갑니다", "exit"),
            ),
        )
        return 0

    async def exercise() -> None:
        app = AincradTextualApp(session)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            assert isinstance(app.screen, MenuScreen)
            items = list(app.screen.query("ListItem"))
            assert len(items) == 3
            assert all(item.region.height > 0 for item in items)
            for first, second in zip(items, items[1:], strict=False):
                assert second.region.y - first.region.bottom >= 1
            await pilot.press("enter")

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
            hint = app.screen.query_one("#hint", Static)
            assert str(hint.content) == "W/S 스크롤 · Enter 뒤로"
            assert scroll.styles.padding.right == 2
            assert scroll.scroll_y == 0
            await pilot.press("s")
            await pilot.pause()
            assert scroll.scroll_y > 0
            await pilot.press("w")
            await pilot.pause()
            assert scroll.scroll_y == 0
            await pilot.press("enter")

    asyncio.run(exercise())


def test_textual_interaction_has_a_dedicated_story_animation_api() -> None:
    assert hasattr(TextualInteraction, "show_story")


def test_story_screen_reveals_text_over_time_then_enter_skips_and_continues() -> None:
    story = "등불 아래에서 한 시간의 선택이 천천히 이야기로 펼쳐졌다. " * 8

    def session(ui):  # type: ignore[no-untyped-def]
        ui.show_story("한 시간의 이야기", (story,))
        return 0

    async def exercise() -> None:
        app = AincradTextualApp(session)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause(0.12)
            screen = app.screen
            assert screen.__class__.__name__ == "StoryScreen"
            revealed = screen.revealed_text  # type: ignore[attr-defined]
            assert 0 < len(revealed) < len(story)
            assert "Enter 전체 표시" in str(screen.query_one("#hint", Static).content)

            await pilot.press("enter")
            await pilot.pause()
            assert screen.revealed_text == story  # type: ignore[attr-defined]
            assert "Enter 계속" in str(screen.query_one("#hint", Static).content)

            await pilot.press("enter")
            await pilot.pause()

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
            name_input = app.screen.query_one("#text-input", Input)
            name_input.insert_text_at_cursor("A\u202eB\u2066C\x1b[31mD\x00E")
            await pilot.pause()
            assert "\u202e" not in name_input.value
            assert "\u2066" not in name_input.value
            assert "\x1b" not in name_input.value
            assert "\x00" not in name_input.value
            await pilot.press("enter")

    asyncio.run(exercise())


def test_input_text_supports_caller_supplied_placeholder_and_hint() -> None:
    captured: list[str | None] = []

    def session(ui):  # type: ignore[no-untyped-def]
        captured.append(
            ui.input_text(
                "성격 묘사",
                subtitle="모험가의 성격을 자유롭게 묘사하세요",
                validate=lambda value: value.strip(),
                placeholder="자유롭게 문장으로 입력하세요",
                hint="Enter 확정 · Esc 뒤로",
            )
        )
        return 0

    async def exercise() -> None:
        app = AincradTextualApp(session)
        async with app.run_test(size=(60, 16)) as pilot:
            await pilot.pause()
            assert isinstance(app.screen, TextInputScreen)
            field = app.screen.query_one("#text-input", Input)
            assert field.placeholder == "자유롭게 문장으로 입력하세요"
            hint = str(app.screen.query_one("#hint", Label).content)
            assert hint == "Enter 확정 · Esc 뒤로"
            await pilot.press("호", "기", "심", "enter")
            await pilot.pause()

    asyncio.run(exercise())
    assert captured == ["호기심"]


def test_input_text_default_copy_is_generic_not_name_specific() -> None:
    def session(ui):  # type: ignore[no-untyped-def]
        ui.input_text(
            "특성 입력",
            subtitle="자유 서술",
            validate=lambda value: value,
        )
        return 0

    async def exercise() -> None:
        app = AincradTextualApp(session)
        async with app.run_test(size=(60, 16)) as pilot:
            await pilot.pause()
            field = app.screen.query_one("#text-input", Input)
            hint = str(app.screen.query_one("#hint", Label).content)
            assert "이름" not in field.placeholder
            assert "이름" not in hint
            assert field.placeholder
            assert "Enter" in hint
            await pilot.press("enter")

    asyncio.run(exercise())


def test_show_story_from_mounts_loading_shell_before_producer_returns() -> None:
    observed: dict[str, object] = {}
    app_box: list[AincradTextualApp] = []

    def session(ui):  # type: ignore[no-untyped-def]
        def producer() -> tuple[str, ...]:
            screen = app_box[0].screen
            observed["screen_type"] = type(screen).__name__
            observed["is_loading"] = getattr(screen, "is_loading", None)
            observed["story_text"] = str(
                screen.query_one("#story-text", Static).content
            )
            observed["hint"] = str(screen.query_one("#hint", Static).content)
            return ("등불이 흔들리며 이야기가 도착했다.",)

        ui.show_story_from("한 시간의 이야기", producer)
        return 0

    async def exercise() -> None:
        app = AincradTextualApp(session)
        app_box.append(app)
        async with app.run_test(size=(80, 24)) as pilot:
            for _ in range(40):
                await pilot.pause(0.05)
                if observed:
                    break
            assert observed["screen_type"] == "StoryScreen"
            assert observed["is_loading"] is True
            loading_copy = f"{observed['story_text']}{observed['hint']}"
            assert loading_copy.strip()
            assert "준비" in loading_copy
            for _ in range(40):
                await pilot.pause(0.05)
                screen = app.screen
                if isinstance(screen, StoryScreen) and screen.revealed_text:
                    break
            assert isinstance(app.screen, StoryScreen)
            await pilot.press("enter")
            await pilot.pause()
            revealed = app.screen.revealed_text  # type: ignore[attr-defined]
            assert revealed == "등불이 흔들리며 이야기가 도착했다."
            await pilot.press("enter")
            await pilot.pause()

    asyncio.run(exercise())


def test_show_story_from_ignores_enter_while_loading_then_reveals() -> None:
    release = threading.Event()
    finished: list[int] = []

    def session(ui):  # type: ignore[no-untyped-def]
        def producer() -> tuple[str, ...]:
            assert release.wait(timeout=10.0)
            return ("느린 제공자가 마침내 장면을 보냈다.",)

        ui.show_story_from("한 시간의 이야기", producer)
        finished.append(0)
        return 0

    async def exercise() -> None:
        app = AincradTextualApp(session)
        async with app.run_test(size=(80, 24)) as pilot:
            for _ in range(40):
                await pilot.pause(0.05)
                if isinstance(app.screen, StoryScreen):
                    break
            screen = app.screen
            assert isinstance(screen, StoryScreen)
            assert screen.is_loading
            await pilot.press("enter", "enter", "escape")
            await pilot.pause()
            assert app.screen is screen
            assert not finished
            release.set()
            for _ in range(60):
                await pilot.pause(0.05)
                if screen.revealed_text:
                    break
            assert not screen.is_loading
            assert len(screen.revealed_text) > 0
            await pilot.press("enter")
            await pilot.pause()
            assert screen.revealed_text == "느린 제공자가 마침내 장면을 보냈다."
            await pilot.press("enter")
            for _ in range(40):
                await pilot.pause(0.05)
                if finished:
                    break
            assert finished == [0]

    asyncio.run(exercise())


def test_show_story_from_propagates_producer_error_without_orphan_screen() -> None:
    outcomes: list[str] = []

    def session(ui):  # type: ignore[no-untyped-def]
        def producer() -> tuple[str, ...]:
            raise RuntimeError("provider unavailable")

        try:
            ui.show_story_from("한 시간의 이야기", producer)
        except RuntimeError as error:
            outcomes.append(str(error))
            ui.show_story("한 시간의 이야기", ("로컬 대체 장면입니다.",))
        return 0

    async def exercise() -> None:
        app = AincradTextualApp(session)
        async with app.run_test(size=(80, 24)) as pilot:
            fallback = None
            for _ in range(60):
                await pilot.pause(0.05)
                screen = app.screen
                if isinstance(screen, StoryScreen) and not screen.is_loading:
                    fallback = screen
                    break
            assert fallback is not None
            assert outcomes == ["provider unavailable"]
            story_screens = [
                candidate
                for candidate in app.screen_stack
                if isinstance(candidate, StoryScreen)
            ]
            assert story_screens == [fallback]
            await pilot.press("enter")
            await pilot.pause()
            assert fallback.revealed_text == "로컬 대체 장면입니다."
            await pilot.press("enter")
            await pilot.pause()

    asyncio.run(exercise())
