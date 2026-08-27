from __future__ import annotations

import os
import select
import unicodedata
from collections.abc import Callable
from enum import Enum, auto
from typing import Protocol, TextIO


class Key(Enum):
    """Logical keyboard actions understood by the TUI."""

    UP = auto()
    DOWN = auto()
    ENTER = auto()
    BACK = auto()
    QUIT = auto()
    INTERRUPT = auto()
    EOF = auto()
    RESIZE = auto()
    UNKNOWN = auto()


class KeyReader(Protocol):
    """Source of logical keyboard actions."""

    def read_key(self) -> Key: ...


ReadBytes = Callable[[int], bytes]
WaitReadable = Callable[[float], bool]


class PosixKeyReader:
    """Read logical keys from a POSIX terminal without unbounded escape reads."""

    def __init__(
        self,
        *,
        read_bytes: ReadBytes | None = None,
        wait_readable: WaitReadable | None = None,
        escape_timeout: float = 0.05,
        max_sequence_length: int = 8,
        fd: int | None = None,
        resize_pending: Callable[[], bool] | None = None,
        resize_poll_interval: float = 0.1,
    ) -> None:
        self._fd = 0 if fd is None else fd
        self._read_bytes = read_bytes or (lambda size: os.read(self._fd, size))
        self._wait_readable = wait_readable or self._select_readable
        self._escape_timeout = escape_timeout
        self._max_sequence_length = max_sequence_length
        self._resize_pending = resize_pending
        self._resize_poll_interval = resize_poll_interval

    def _select_readable(self, timeout: float) -> bool:
        readable, _, _ = select.select([self._fd], [], [], timeout)
        return bool(readable)

    def read_key(self) -> Key:
        if self._resize_pending is not None:
            while True:
                if self._resize_pending():
                    return Key.RESIZE
                if self._wait_readable(self._resize_poll_interval):
                    break
        data = self._read_bytes(1)
        if data != b"\x1b":
            return decode_posix_bytes(data, max_sequence_length=self._max_sequence_length)

        while len(data) < self._max_sequence_length:
            if not self._wait_readable(self._escape_timeout):
                break
            chunk = self._read_bytes(1)
            if not chunk:
                break
            data += chunk
            decoded = decode_posix_bytes(
                data, max_sequence_length=self._max_sequence_length
            )
            if decoded in {Key.UP, Key.DOWN}:
                return decoded
        return decode_posix_bytes(data, max_sequence_length=self._max_sequence_length)

    def read_text_line(
        self,
        output: TextIO,
        prompt: str,
        *,
        max_bytes: int = 256,
        redraw: Callable[[str], None] | None = None,
        accept_input: Callable[[], bool] | None = None,
    ) -> str:
        """Read and visibly edit one UTF-8 line while the terminal remains raw."""

        if redraw is None:
            output.write("\x1b[?25h" + prompt)
            output.flush()
        else:
            redraw("")
        characters: list[str] = []
        pending = bytearray()
        consumed = 0
        try:
            while True:
                if self._resize_pending is not None:
                    resized = False
                    while not self._wait_readable(self._resize_poll_interval):
                        if self._resize_pending():
                            resized = True
                            if redraw is not None:
                                redraw("".join(characters))
                            break
                    if resized:
                        continue
                chunk = self._read_bytes(1)
                if not chunk or chunk == b"\x04":
                    raise EOFError("text input ended")
                consumed += len(chunk)
                if consumed > max_bytes:
                    raise ValueError("text input exceeds the byte limit")
                if chunk == b"\x03":
                    raise KeyboardInterrupt
                if chunk == b"\x1b":
                    raise EOFError("text input cancelled")
                if accept_input is not None and not accept_input():
                    pending.clear()
                    continue
                if chunk in {b"\r", b"\n"}:
                    if pending:
                        raise ValueError("text input ended with incomplete UTF-8")
                    if redraw is None:
                        output.write("\n")
                        output.flush()
                    return "".join(characters)
                if chunk in {b"\x08", b"\x7f"}:
                    pending.clear()
                    if characters:
                        characters.pop()
                        if redraw is None:
                            output.write("\r\x1b[2K" + prompt + "".join(characters))
                            output.flush()
                        else:
                            redraw("".join(characters))
                    continue
                if chunk[0] < 0x20:
                    raise ValueError("text input contains a control character")
                pending.extend(chunk)
                try:
                    decoded = pending.decode("utf-8")
                except UnicodeDecodeError as error:
                    if error.reason == "unexpected end of data":
                        continue
                    raise ValueError("text input is not valid UTF-8") from error
                if any(
                    unicodedata.category(character).startswith("C")
                    for character in decoded
                ):
                    raise ValueError("text input contains a control or format character")
                characters.extend(decoded)
                if redraw is None:
                    output.write(decoded)
                    output.flush()
                else:
                    redraw("".join(characters))
                pending.clear()
        finally:
            if redraw is None:
                output.write("\x1b[?25l")
                output.flush()


def decode_posix_bytes(data: bytes, *, max_sequence_length: int = 8) -> Key:
    """Decode one bounded POSIX byte sequence into a logical key."""

    if len(data) > max_sequence_length:
        return Key.UNKNOWN
    mapping = {
        b"\x1b[A": Key.UP,
        b"\x1bOA": Key.UP,
        b"\x1b[B": Key.DOWN,
        b"\x1bOB": Key.DOWN,
        b"w": Key.UP,
        b"W": Key.UP,
        b"s": Key.DOWN,
        b"S": Key.DOWN,
        b"\r": Key.ENTER,
        b"\n": Key.ENTER,
        b"\x1b": Key.BACK,
        b"q": Key.QUIT,
        b"Q": Key.QUIT,
        b"\x03": Key.INTERRUPT,
        b"\x04": Key.EOF,
        b"": Key.EOF,
    }
    return mapping.get(data, Key.UNKNOWN)
