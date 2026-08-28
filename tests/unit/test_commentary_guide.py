from __future__ import annotations

import json
import os
import stat
import time
from contextlib import suppress
from pathlib import Path

import pytest

import aincrad.commentary.guide as guide_module
from aincrad.commentary.guide import (
    DestinationCandidate,
    HermesKimiCommentaryAdapter,
    MovementCommentaryRequest,
    deterministic_commentary,
)


def test_deterministic_commentary_ranks_visible_candidates_and_preserves_destinations() -> None:
    request = _request()

    result = deterministic_commentary(request)

    assert [item.destination_id for item in result.recommendations] == [
        "emberfall-inn",
        "mossreach",
        "vault-1",
    ]
    assert [item.destination_id for item in result.remaining_destinations] == ["emberfall-shop"]
    assert "물리적" in result.recommendations[0].commentary_ko
    assert "사회적" in result.recommendations[0].commentary_ko
    assert result.source == "deterministic"


def test_hermes_adapter_uses_fixed_argv_and_bounded_stdin(tmp_path: Path) -> None:
    executable = tmp_path / "fake-hermes"
    argv_path = tmp_path / "argv.json"
    stdin_path = tmp_path / "stdin.json"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        f"pathlib.Path({str(argv_path)!r}).write_text(json.dumps(sys.argv[1:]))\n"
        f"pathlib.Path({str(stdin_path)!r}).write_bytes(sys.stdin.buffer.read())\n"
        'print(json.dumps({"recommendations": [{"destination_id": "mossreach", '
        '"commentary_ko": "물리적: 습한 길입니다. 사회적: 채집꾼에게 물을 수 있습니다."}]}))\n',
        encoding="utf-8",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    request = _request()

    result = HermesKimiCommentaryAdapter(executable=executable).commentary(request)

    assert json.loads(argv_path.read_text(encoding="utf-8")) == [
        "chat",
        "-Q",
        "--ignore-rules",
        "--max-turns",
        "1",
        "--run-budget",
        "8",
        "--source",
        "tool",
        "--provider",
        "og",
        "-m",
        "moonshotai/kimi-k3-ultrafast",
        "--reasoning",
        "minimal",
        "--query-file",
        "-",
    ]
    prompt = stdin_path.read_bytes()
    assert prompt
    assert len(prompt) <= 8_192
    assert b"mossreach" in prompt
    assert result.source == "hermes_cli"
    assert [item.destination_id for item in result.recommendations] == [
        "emberfall-inn",
        "mossreach",
        "vault-1",
    ]
    assert [item.destination_id for item in result.remaining_destinations] == ["emberfall-shop"]


def test_adapter_accepts_only_the_known_hermes_toolset_warning_prefix(
    tmp_path: Path,
) -> None:
    executable = _executable(
        tmp_path,
        "hermes-warning",
        "import json\n"
        "print('Warning: Unknown toolsets: omh')\n"
        "print(json.dumps({'recommendations': [{'destination_id': 'mossreach', "
        "'commentary_ko': '물리적: 젖은 길. 사회적: 채집꾼.'}]}))\n",
    )

    result = HermesKimiCommentaryAdapter(executable=executable).commentary(_request())

    assert result.source == "hermes_cli"


def test_adapter_rejects_unsafe_schema_and_keeps_every_destination(tmp_path: Path) -> None:
    executable = _executable(
        tmp_path,
        "unsafe-schema",
        'import json\nprint(json.dumps({"recommendations": ['
        '{"destination_id": "mossreach", "commentary_ko": "첫 추천"}, '
        '{"destination_id": "mossreach", "commentary_ko": "중복 추천"}], "extra": "거부"}))\n',
    )
    request = _request()

    result = HermesKimiCommentaryAdapter(executable=executable).commentary(request)

    assert result.source == "deterministic"
    ids = [item.destination_id for item in result.recommendations] + [
        item.destination_id for item in result.remaining_destinations
    ]
    assert ids == ["emberfall-inn", "mossreach", "vault-1", "emberfall-shop"]
    assert len(ids) == len(set(ids)) == len(request.destinations)


def test_adapter_falls_back_for_malformed_json_and_missing_binary(tmp_path: Path) -> None:
    malformed = _executable(tmp_path, "malformed", "print('not json')\n")
    request = _request()

    malformed_result = HermesKimiCommentaryAdapter(executable=malformed).commentary(request)
    missing_result = HermesKimiCommentaryAdapter(
        executable=tmp_path / "missing"
    ).commentary(request)

    assert malformed_result == deterministic_commentary(request)
    assert missing_result == deterministic_commentary(request)


def test_adapter_falls_back_when_prompt_or_process_output_exceeds_bound(tmp_path: Path) -> None:
    oversized_output = _executable(
        tmp_path,
        "oversized-output",
        "import json\n"
        'print(json.dumps({"recommendations": [{"destination_id": "mossreach", '
        '"commentary_ko": "가" * 40000}]}))\n',
    )
    observed_stdin = tmp_path / "oversized-stdin"
    echo = _executable(
        tmp_path,
        "echo",
        "import pathlib, sys\n"
        f"pathlib.Path({str(observed_stdin)!r}).write_bytes(sys.stdin.buffer.read())\n"
        'print("{}")\n',
    )
    request = _request()
    oversized_request = MovementCommentaryRequest(
        current_location_name_ko="광장",
        current_location_description_ko="가" * 9000,
        hp_summary_ko="HP 1/1",
        mp_summary_ko="MP 1/1",
        identity_labels_ko=(),
        destinations=request.destinations,
    )

    output_result = HermesKimiCommentaryAdapter(executable=oversized_output).commentary(request)
    prompt_result = HermesKimiCommentaryAdapter(executable=echo).commentary(oversized_request)

    assert output_result == deterministic_commentary(request)
    assert prompt_result == deterministic_commentary(oversized_request)
    assert not observed_stdin.exists()


def test_adapter_does_not_inherit_unrelated_secret_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed = tmp_path / "observed.txt"
    executable = _executable(
        tmp_path,
        "environment",
        "import json, os, pathlib\n"
        f"pathlib.Path({str(observed)!r}).write_text(os.getenv('AINCRAD_SECRET_SENTINEL', ''))\n"
        "print(json.dumps({'recommendations': [{'destination_id': 'mossreach', "
        "'commentary_ko': '물리적: 안전함. 사회적: 대화함.'}]}))\n",
    )
    monkeypatch.setenv("AINCRAD_SECRET_SENTINEL", "should-not-cross")

    result = HermesKimiCommentaryAdapter(executable=executable).commentary(_request())

    assert result.source == "hermes_cli"
    assert observed.read_text(encoding="utf-8") == ""


def test_adapter_sanitizes_ansi_bidi_and_caps_display_text(tmp_path: Path) -> None:
    executable = _executable(
        tmp_path,
        "unsafe-text",
        "import json\n"
        'print(json.dumps({"recommendations": [{"destination_id": "mossreach", '
        '"commentary_ko": "\\u001b[31m물리적: 진입로\\u001b[0m '
        '사회적: 안내인\\u202e" + "가" * 400}]}))\n',
    )

    result = HermesKimiCommentaryAdapter(executable=executable).commentary(_request())

    commentary = next(
        item.commentary_ko
        for item in result.recommendations
        if item.destination_id == "mossreach"
    )
    assert result.source == "hermes_cli"
    assert "\x1b" not in commentary
    assert "\u202e" not in commentary
    assert len(commentary) <= 280


def test_adapter_timeout_kills_its_process_group_without_survivor(tmp_path: Path) -> None:
    child_pid_file = tmp_path / "child.pid"
    executable = _executable(
        tmp_path,
        "timeout",
        "import pathlib, subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        f"pathlib.Path({str(child_pid_file)!r}).write_text(str(child.pid))\n"
        "time.sleep(30)\n",
    )
    try:
        result = HermesKimiCommentaryAdapter(executable=executable, timeout_seconds=2.0).commentary(
            _request()
        )
        child_pid = int(child_pid_file.read_text(encoding="utf-8"))

        assert result == deterministic_commentary(_request())
        assert _wait_for_exit(child_pid)
    finally:
        if child_pid_file.exists():
            _stop_process(int(child_pid_file.read_text(encoding="utf-8")))


def test_commentary_process_cleanup_tolerates_reaped_group_permission_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ReapedProcess:
        pid = 4321

        def __init__(self) -> None:
            self.wait_calls = 0

        def wait(self, timeout: float) -> int:
            self.wait_calls += 1
            return 0

    process = ReapedProcess()

    def denied_killpg(_pid: int, _signal: int) -> None:
        raise PermissionError("process group already reaped")

    monkeypatch.setattr(guide_module.os, "killpg", denied_killpg)

    guide_module._terminate_process_group(process)  # type: ignore[arg-type]

    assert process.wait_calls == 2


def _request() -> MovementCommentaryRequest:
    return MovementCommentaryRequest(
        current_location_name_ko="빛결 광장",
        current_location_description_ko="길 안내등이 켜진 안전한 광장",
        hp_summary_ko="HP 12/20",
        mp_summary_ko="MP 3/10",
        identity_labels_ko=("전사", "길잡이"),
        destinations=(
            DestinationCandidate("vault-1", "메아리 회랑", "위험한 유리 회랑", 30),
            DestinationCandidate(
                "emberfall-inn", "고요한 심지 여관", "안전하게 쉴 수 있는 여관", 10
            ),
            DestinationCandidate("mossreach", "이끼자락 황야", "사냥꾼과 채집꾼이 오가는 황야", 20),
            DestinationCandidate(
                "emberfall-shop", "잿불창고 교역소", "물자 거래가 활발한 교역소", 40
            ),
        ),
    )


def _executable(tmp_path: Path, name: str, body: str) -> Path:
    executable = tmp_path / name
    executable.write_text(f"#!/usr/bin/env python3\n{body}", encoding="utf-8")
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return executable


def _wait_for_exit(pid: int) -> bool:
    for _attempt in range(20):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


def _stop_process(pid: int) -> None:
    with suppress(ProcessLookupError):
        os.kill(pid, 9)
