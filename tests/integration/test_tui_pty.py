from __future__ import annotations

import codecs
import fcntl
import os
import pty
import select
import signal
import struct
import subprocess
import sys
import termios
import time
from pathlib import Path

import pyte
import pytest
from wcwidth import wcwidth


class TerminalCapture:
    """Reconstruct the visible terminal cells from cursor-addressed ANSI output."""

    def __init__(self, master_fd: int, *, columns: int, lines: int) -> None:
        self.master_fd = master_fd
        self.screen = pyte.Screen(columns, lines)
        self.stream = pyte.Stream(self.screen)
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.raw = bytearray()

    @property
    def rows(self) -> list[str]:
        rendered: list[str] = []
        for y in range(self.screen.lines):
            row: list[str] = []
            skip_wide_stub = False
            for x in range(self.screen.columns):
                if skip_wide_stub:
                    skip_wide_stub = False
                    continue
                data = self.screen.buffer[y][x].data
                if not data:
                    row.append(" ")
                    continue
                row.append(data)
                skip_wide_stub = wcwidth(data[0]) == 2
            rendered.append("".join(row))
        return rendered

    @property
    def visible(self) -> str:
        return "\n".join(self.rows)

    def resize(self, *, columns: int, lines: int) -> None:
        self.screen.resize(lines=lines, columns=columns)

    def drain(self, *, quiet_for: float = 0.1, timeout: float = 1.0) -> None:
        deadline = time.monotonic() + timeout
        quiet_deadline = time.monotonic() + quiet_for
        while time.monotonic() < deadline:
            wait = max(0.0, min(quiet_deadline, deadline) - time.monotonic())
            readable, _, _ = select.select([self.master_fd], [], [], wait)
            if not readable:
                return
            chunk = os.read(self.master_fd, 65536)
            if not chunk:
                return
            self.raw.extend(chunk)
            self.stream.feed(self.decoder.decode(chunk))
            quiet_deadline = time.monotonic() + quiet_for

    def read_until(self, expected: str, *, timeout: float = 8.0) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            readable, _, _ = select.select([self.master_fd], [], [], 0.1)
            if not readable:
                continue
            chunk = os.read(self.master_fd, 65536)
            if not chunk:
                break
            self.raw.extend(chunk)
            self.stream.feed(self.decoder.decode(chunk))
            if expected in self.visible:
                self.drain()
                return self.visible
        raise AssertionError(
            f"visible terminal did not contain {expected!r}: {self.visible!r}"
        )

    def read_until_bytes(self, expected: bytes, *, timeout: float = 8.0) -> bytes:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if expected in self.raw:
                return bytes(self.raw)
            readable, _, _ = select.select([self.master_fd], [], [], 0.1)
            if not readable:
                continue
            chunk = os.read(self.master_fd, 65536)
            if not chunk:
                break
            self.raw.extend(chunk)
            self.stream.feed(self.decoder.decode(chunk))
        raise AssertionError(f"PTY bytes did not contain {expected!r}")


@pytest.mark.skipif(os.name != "posix", reason="POSIX terminal contract")
def test_real_pty_keyboard_flow_restores_terminal_attributes(tmp_path: Path) -> None:
    master_fd, slave_fd = pty.openpty()
    original_attributes = termios.tcgetattr(slave_fd)
    process = subprocess.Popen(
        [sys.executable, "-m", "aincrad"],
        cwd=tmp_path,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
    )
    capture = TerminalCapture(master_fd, columns=80, lines=24)
    try:
        home = capture.read_until("메인 메뉴")
        assert "1. 시작하기" not in home
        os.write(master_fd, b"\r")
        capture.read_until("직업 선택")
        os.write(master_fd, b"\r")
        capture.read_until("주인공 이름")
        os.write(master_fd, "테스트용사\r".encode())
        action = capture.read_until("테스트용사의 행동")
        assert "1일차 00:00" in action
        os.write(master_fd, b"\r")
        capture.read_until("여정 계속")
        os.write(master_fd, b"s\r")
        capture.read_until("메인 메뉴")
        os.write(master_fd, b"ss\r")
        capture.read_until_bytes(b"\x1b[?1049l")
        assert process.wait(timeout=8) == 0
        assert termios.tcgetattr(slave_fd) == original_attributes
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)
        os.close(master_fd)
        os.close(slave_fd)


@pytest.mark.skipif(os.name != "posix", reason="POSIX terminal contract")
def test_real_pty_renders_a_complete_40_column_home_panel(tmp_path: Path) -> None:
    master_fd, slave_fd = pty.openpty()
    fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 40, 0, 0))
    original_attributes = termios.tcgetattr(slave_fd)
    process = subprocess.Popen(
        [sys.executable, "-m", "aincrad"],
        cwd=tmp_path,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
    )
    capture = TerminalCapture(master_fd, columns=40, lines=24)
    try:
        captured = capture.read_until("메인 메뉴")
        assert "THE GLASS FRONTIER" in captured
        rows = capture.rows
        top = next(row for row in rows if "╭" in row and "╮" in row)
        bottom = next(row for row in rows if "╰" in row and "╯" in row)
        assert top.index("╭") == bottom.index("╰")
        assert top.index("╮") == bottom.index("╯")
        assert top.index("╮") < 40
        os.write(master_fd, b"ss\r")
        capture.read_until_bytes(b"\x1b[?1049l")
        assert process.wait(timeout=8) == 0
        assert termios.tcgetattr(slave_fd) == original_attributes
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)
        os.close(master_fd)
        os.close(slave_fd)


@pytest.mark.skipif(os.name != "posix", reason="POSIX terminal contract")
def test_real_pty_reflows_while_preserving_menu_selection(tmp_path: Path) -> None:
    master_fd, slave_fd = pty.openpty()
    fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
    original_attributes = termios.tcgetattr(slave_fd)
    process = subprocess.Popen(
        [sys.executable, "-m", "aincrad"],
        cwd=tmp_path,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
    )
    capture = TerminalCapture(master_fd, columns=80, lines=24)
    try:
        capture.read_until("메인 메뉴")
        os.write(master_fd, b"s")
        capture.read_until("히스토리")

        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 40, 0, 0))
        capture.resize(columns=40, lines=24)
        os.kill(process.pid, signal.SIGWINCH)
        narrow = capture.read_until("메인 메뉴")
        assert capture.screen.columns == 40
        assert all("\ufffd" not in row for row in capture.rows)
        assert "히스토리" in narrow
        os.write(master_fd, b"\r")
        capture.read_until("기록된 회차가 없습니다")
        os.write(master_fd, b"\r")
        capture.read_until("메인 메뉴")
        os.write(master_fd, b"ss\r")
        capture.read_until_bytes(b"\x1b[?1049l")
        assert process.wait(timeout=8) == 0
        assert termios.tcgetattr(slave_fd) == original_attributes
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)
        os.close(master_fd)
        os.close(slave_fd)


@pytest.mark.skipif(os.name != "posix", reason="POSIX terminal contract")
def test_real_pty_session_failure_is_nonzero_and_restores_terminal(tmp_path: Path) -> None:
    master_fd, slave_fd = pty.openpty()
    original_attributes = termios.tcgetattr(slave_fd)
    script = """
from aincrad.cli import main

def fail(**_kwargs):
    raise RuntimeError("injected session failure")

raise SystemExit(main(runner=fail))
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
    )
    capture = TerminalCapture(master_fd, columns=80, lines=24)
    try:
        capture.read_until("메인 메뉴")
        os.write(master_fd, b"\r")
        capture.read_until_bytes(b"\x1b[?1049l")
        assert process.wait(timeout=8) == 1
        assert termios.tcgetattr(slave_fd) == original_attributes
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)
        os.close(master_fd)
        os.close(slave_fd)


@pytest.mark.skipif(os.name != "posix", reason="POSIX terminal contract")
def test_real_pty_sanitizes_menu_option_controls(tmp_path: Path) -> None:
    master_fd, slave_fd = pty.openpty()
    original_attributes = termios.tcgetattr(slave_fd)
    script = """
from aincrad.tui.textual_app import AincradTextualApp, MenuOption

def session(ui):
    ui.choose(
        "메인 메뉴",
        (MenuOption("BAD\\x1b[31mRED\\u202eX", "DESC\\x00\\u2066", "done"),),
    )
    return 0

raise SystemExit(AincradTextualApp(session).run())
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
    )
    capture = TerminalCapture(master_fd, columns=80, lines=24)
    try:
        capture.read_until("BAD")
        os.write(master_fd, b"\r")
        raw = capture.read_until_bytes(b"\x1b[?1049l")
        assert b"\x1b[31m" not in raw
        assert "\u202e".encode() not in raw
        assert "\u2066".encode() not in raw
        assert b"DESC\x00" not in raw
        assert process.wait(timeout=8) == 0
        assert termios.tcgetattr(slave_fd) == original_attributes
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)
        os.close(master_fd)
        os.close(slave_fd)


@pytest.mark.skipif(os.name != "posix", reason="POSIX terminal contract")
def test_real_pty_sanitizes_name_while_bracketed_paste_is_live(tmp_path: Path) -> None:
    master_fd, slave_fd = pty.openpty()
    original_attributes = termios.tcgetattr(slave_fd)
    script = """
from aincrad.tui.textual_app import AincradTextualApp

def session(ui):
    ui.input_text("주인공 이름", subtitle="이름을 정하세요", validate=lambda value: value)
    return 0

raise SystemExit(AincradTextualApp(session).run())
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
    )
    capture = TerminalCapture(master_fd, columns=80, lines=24)
    pasted = "A\u202eB\u2066C\x1b[31mD\x00E".encode()
    try:
        capture.read_until("주인공 이름")
        before = len(capture.raw)
        os.write(master_fd, b"\x1b[200~" + pasted + b"\x1b[201~")
        capture.read_until("�B�C")
        live_output = bytes(capture.raw[before:])
        assert "\u202e".encode() not in live_output
        assert "\u2066".encode() not in live_output
        assert b"\x00" not in live_output
        os.write(master_fd, b"\r")
        capture.read_until_bytes(b"\x1b[?1049l")
        assert process.wait(timeout=8) == 0
        assert termios.tcgetattr(slave_fd) == original_attributes
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)
        os.close(master_fd)
        os.close(slave_fd)
