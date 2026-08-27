from __future__ import annotations

from io import StringIO

import pytest

from aincrad.tui.keys import Key, KeyReader, PosixKeyReader, decode_posix_bytes


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (b"\x1b[A", Key.UP),
        (b"\x1bOA", Key.UP),
        (b"\x1b[B", Key.DOWN),
        (b"\x1bOB", Key.DOWN),
        (b"w", Key.UP),
        (b"W", Key.UP),
        (b"s", Key.DOWN),
        (b"S", Key.DOWN),
        (b"\r", Key.ENTER),
        (b"\n", Key.ENTER),
        (b"\x1b", Key.BACK),
        (b"q", Key.QUIT),
        (b"Q", Key.QUIT),
        (b"\x03", Key.INTERRUPT),
        (b"\x04", Key.EOF),
        (b"", Key.EOF),
    ],
)
def test_decode_posix_bytes_maps_supported_input(data: bytes, expected: Key) -> None:
    assert decode_posix_bytes(data) is expected


def test_key_reader_protocol_accepts_reader() -> None:
    class StubReader:
        def read_key(self) -> Key:
            return Key.ENTER

    reader: KeyReader = StubReader()
    assert reader.read_key() is Key.ENTER


def test_decoder_rejects_malformed_and_oversized_sequences() -> None:
    assert decode_posix_bytes(b"\x1b[Z") is Key.UNKNOWN
    assert decode_posix_bytes(b"\x1b[" + b"1" * 20 + b"A", max_sequence_length=8) is Key.UNKNOWN


def test_posix_reader_collects_escape_sequence_with_injected_readiness() -> None:
    chunks = iter((b"\x1b", b"[", b"A"))
    waits: list[float] = []

    def wait_readable(timeout: float) -> bool:
        waits.append(timeout)
        return True

    reader = PosixKeyReader(
        read_bytes=lambda _size: next(chunks),
        wait_readable=wait_readable,
        escape_timeout=0.01,
    )

    assert reader.read_key() is Key.UP
    assert waits == [0.01, 0.01]


def test_posix_reader_treats_escape_timeout_as_back_without_sleeping() -> None:
    waits: list[float] = []

    def wait_readable(timeout: float) -> bool:
        waits.append(timeout)
        return False

    reader = PosixKeyReader(
        read_bytes=lambda _size: b"\x1b",
        wait_readable=wait_readable,
        escape_timeout=0.02,
    )

    assert reader.read_key() is Key.BACK
    assert waits == [0.02]


def test_posix_reader_bounds_malformed_sequence_reads() -> None:
    read_count = 0

    def read_bytes(_size: int) -> bytes:
        nonlocal read_count
        read_count += 1
        return b"\x1b" if read_count == 1 else b"x"

    reader = PosixKeyReader(
        read_bytes=read_bytes,
        wait_readable=lambda _timeout: True,
        max_sequence_length=4,
    )

    assert reader.read_key() is Key.UNKNOWN
    assert read_count == 4


def test_posix_reader_returns_eof_without_waiting() -> None:
    wait_called = False

    def wait_readable(_timeout: float) -> bool:
        nonlocal wait_called
        wait_called = True
        return True

    def read_bytes(_size: int) -> bytes:
        return b""

    reader = PosixKeyReader(read_bytes=read_bytes, wait_readable=wait_readable)

    assert reader.read_key() is Key.EOF
    assert wait_called is False


def test_posix_reader_collects_and_echoes_a_utf8_name_in_raw_mode() -> None:
    encoded = iter("유리별\r".encode())
    output = StringIO()
    reader = PosixKeyReader(read_bytes=lambda _size: bytes((next(encoded),)))

    assert reader.read_text_line(output, "주인공 이름: ") == "유리별"
    assert output.getvalue() == "\x1b[?25h주인공 이름: 유리별\n\x1b[?25l"


def test_posix_reader_can_redraw_text_inside_an_owned_frame_without_raw_echo() -> None:
    encoded = iter("유리\x7f별\r".encode())
    output = StringIO()
    frames: list[str] = []
    reader = PosixKeyReader(read_bytes=lambda _size: bytes((next(encoded),)))

    assert reader.read_text_line(output, "ignored", redraw=frames.append) == "유별"

    assert frames == ["", "유", "유리", "유", "유별"]
    assert output.getvalue() == ""


def test_legacy_raw_backspace_repaints_after_removing_a_zero_width_mark() -> None:
    encoded = iter("e\u20dd\x7f\r".encode())
    output = StringIO()
    reader = PosixKeyReader(read_bytes=lambda _size: bytes((next(encoded),)))

    assert reader.read_text_line(output, "이름: ") == "e"
    assert "\r\x1b[2K이름: e" in output.getvalue()


def test_legacy_raw_backspace_repaints_after_removing_emoji_modifier() -> None:
    encoded = iter("👍🏽\x7f\r".encode())
    output = StringIO()
    reader = PosixKeyReader(read_bytes=lambda _size: bytes((next(encoded),)))

    assert reader.read_text_line(output, "이름: ") == "👍"
    assert "\r\x1b[2K이름: 👍" in output.getvalue()


def test_hidden_text_input_still_enforces_byte_limit() -> None:
    encoded = iter(b"a" * 257)
    reader = PosixKeyReader(read_bytes=lambda _size: bytes((next(encoded),)))

    with pytest.raises(ValueError, match="byte limit"):
        reader.read_text_line(
            StringIO(),
            "",
            max_bytes=256,
            accept_input=lambda: False,
        )
