from __future__ import annotations

from io import StringIO

import pytest

from aincrad.tui.terminal import AnsiScreen, RawTerminal


@pytest.mark.parametrize("raise_inside", [False, True])
def test_raw_terminal_restores_saved_attributes(raise_inside: bool) -> None:
    saved = [1, 2, 3]
    calls: list[tuple[object, ...]] = []

    def get_attrs(fd: int) -> list[int]:
        calls.append(("get", fd))
        return saved

    def set_raw(fd: int) -> None:
        calls.append(("raw", fd))

    def set_attrs(fd: int, when: int, attrs: list[int]) -> None:
        calls.append(("restore", fd, when, attrs))

    expectation = pytest.raises(RuntimeError) if raise_inside else _does_not_raise()
    with expectation, RawTerminal(
        fd=7,
        get_attrs=get_attrs,
        set_raw=set_raw,
        set_attrs=set_attrs,
        restore_when=99,
    ):
        calls.append(("body",))
        if raise_inside:
            raise RuntimeError("boom")

    assert calls == [
        ("get", 7),
        ("raw", 7),
        ("body",),
        ("restore", 7, 99, saved),
    ]


@pytest.mark.parametrize("raise_inside", [False, True])
def test_ansi_screen_restores_cursor_and_primary_screen(raise_inside: bool) -> None:
    output = StringIO()

    expectation = pytest.raises(RuntimeError) if raise_inside else _does_not_raise()
    with expectation, AnsiScreen(output):
        output.write("body")
        if raise_inside:
            raise RuntimeError("boom")

    assert output.getvalue() == "\x1b[?1049h\x1b[?25lbody\x1b[?25h\x1b[?1049l"


def test_ansi_screen_draw_replaces_the_current_frame() -> None:
    output = StringIO()

    with AnsiScreen(output) as screen:
        screen.draw("첫 화면\n")
        screen.draw("둘째 화면\n")

    rendered = output.getvalue()
    assert rendered.count("\x1b[H\x1b[2J") == 2
    assert "\x1b[H\x1b[2J둘째 화면\n" in rendered


class _does_not_raise:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *_args: object) -> None:
        return None
