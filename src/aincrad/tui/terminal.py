from __future__ import annotations

import termios
import tty
from collections.abc import Callable
from types import TracebackType
from typing import Any, TextIO

TerminalAttributes = list[Any]
GetAttributes = Callable[[int], TerminalAttributes]
SetRaw = Callable[[int], None]
SetAttributes = Callable[[int, int, TerminalAttributes], None]

_ALT_SCREEN_ON = "\x1b[?1049h"
_ALT_SCREEN_OFF = "\x1b[?1049l"
_CURSOR_HIDE = "\x1b[?25l"
_CURSOR_SHOW = "\x1b[?25h"
_CLEAR_FRAME = "\x1b[H\x1b[2J"


class AnsiScreen:
    """Own the alternate screen and cursor visibility for a bounded scope."""

    def __init__(self, output: TextIO) -> None:
        self._output = output

    def __enter__(self) -> AnsiScreen:
        self._output.write(_ALT_SCREEN_ON + _CURSOR_HIDE)
        self._output.flush()
        return self

    def draw(self, frame: str) -> None:
        """Replace the current alternate-screen frame."""

        self._output.write(_CLEAR_FRAME + frame)
        self._output.flush()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._output.write(_CURSOR_SHOW + _ALT_SCREEN_OFF)
        self._output.flush()


class RawTerminal:
    """Temporarily put a POSIX terminal in raw mode and always restore it."""

    def __init__(
        self,
        fd: int = 0,
        *,
        get_attrs: GetAttributes = termios.tcgetattr,
        set_raw: SetRaw = tty.setraw,
        set_attrs: SetAttributes = termios.tcsetattr,
        restore_when: int = termios.TCSAFLUSH,
    ) -> None:
        self._fd = fd
        self._get_attrs = get_attrs
        self._set_raw = set_raw
        self._set_attrs = set_attrs
        self._restore_when = restore_when
        self._saved: TerminalAttributes | None = None

    def __enter__(self) -> RawTerminal:
        self._saved = self._get_attrs(self._fd)
        self._set_raw(self._fd)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._saved is not None:
            self._set_attrs(self._fd, self._restore_when, self._saved)
