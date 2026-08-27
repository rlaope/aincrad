from __future__ import annotations

import fcntl
import os
import pty
import re
import select
import signal
import struct
import subprocess
import sys
import termios
import time
from pathlib import Path

import pytest

from aincrad.tui.layout import display_width

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _read_until(master_fd: int, expected: str, *, timeout: float = 8.0) -> str:
    deadline = time.monotonic() + timeout
    received = bytearray()
    while time.monotonic() < deadline:
        readable, _, _ = select.select([master_fd], [], [], 0.1)
        if not readable:
            continue
        chunk = os.read(master_fd, 4096)
        if not chunk:
            break
        received.extend(chunk)
        decoded = received.decode("utf-8", errors="replace")
        if expected in decoded:
            return decoded
    raise AssertionError(
        f"PTY output did not contain {expected!r}: "
        f"{received.decode('utf-8', errors='replace')!r}"
    )


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
    try:
        home = _read_until(master_fd, "Enter 선택")
        assert "1. 시작하기" not in home
        os.write(master_fd, b"\r")
        _read_until(master_fd, "직업 선택")
        os.write(master_fd, b"\r")
        _read_until(master_fd, "주인공 이름")
        os.write(master_fd, "테스트용사\r".encode())
        action = _read_until(master_fd, "AI 판단에 맡기기")
        assert "테스트용사의 행동" in action
        os.write(master_fd, b"\r")
        _read_until(master_fd, "다음 시간을 진행할까요?")
        os.write(master_fd, b"s\r")
        _read_until(master_fd, "THE GLASS FRONTIER")
        os.write(master_fd, b"s")
        _read_until(master_fd, "◆ 히스토리")
        os.write(master_fd, b"s")
        _read_until(master_fd, "◆ 종료")
        os.write(master_fd, b"\r")
        _read_until(master_fd, "\x1b[?1049l")
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
    try:
        captured = _read_until(master_fd, "Enter 선택")
        plain = _ANSI.sub("", captured)
        panel_lines = [
            line
            for line in plain.splitlines()
            if line.startswith(("╭", "├", "│", "╰"))
        ]
        assert panel_lines[0] == "╭" + "─" * 38 + "╮"
        assert panel_lines[-1] == "╰" + "─" * 38 + "╯"
        assert all(display_width(line) == 40 for line in panel_lines)
        os.write(master_fd, b"ss\r")
        _read_until(master_fd, "\x1b[?1049l")
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
    try:
        _read_until(master_fd, "Enter 선택")

        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 40, 0, 0))
        os.kill(process.pid, signal.SIGWINCH)
        narrow = _ANSI.sub("", _read_until(master_fd, "╰" + "─" * 38 + "╯"))
        narrow_lines = [
            line
            for line in narrow.splitlines()
            if line.startswith(("╭", "├", "│", "╰"))
        ]
        assert all(display_width(line) == 40 for line in narrow_lines)

        os.write(master_fd, b"s")
        _read_until(master_fd, "◆ 히스토리")

        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 100, 0, 0))
        os.kill(process.pid, signal.SIGWINCH)
        wide = _ANSI.sub("", _read_until(master_fd, "╰" + "─" * 98 + "╯"))
        wide_lines = [
            line
            for line in wide.splitlines()
            if line.startswith(("╭", "├", "│", "╰"))
        ]
        assert all(display_width(line) == 100 for line in wide_lines)

        os.write(master_fd, b"s")
        _read_until(master_fd, "◆ 종료")

        os.write(master_fd, b"\r")
        _read_until(master_fd, "\x1b[?1049l")
        assert process.wait(timeout=8) == 0
        assert termios.tcgetattr(slave_fd) == original_attributes
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)
        os.close(master_fd)
        os.close(slave_fd)
