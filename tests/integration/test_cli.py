from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

import pytest

from aincrad.cli import (
    SimulationResult,
    _default_replay,
    _default_run,
    _event_fields,
    main,
)
from aincrad.persistence import GENESIS_HASH, EventLog, StoredEvent
from aincrad.tui import AdventurerView, EventView, RunSummary


def sample_result() -> SimulationResult:
    return SimulationResult(
        events=(EventView(datetime(2026, 8, 26, tzinfo=UTC), "이동", "도시에 도착"),),
        adventurers=(AdventurerView("Rhea Vale", "Emberfall", 100, 25, "대기"),),
        summary=RunSummary(seed=9, days=3, event_count=1, status="완료"),
    )


def test_simulate_injects_arguments_and_prints_projection(tmp_path: Path) -> None:
    calls: list[tuple[int, int, bool, Path | None, bool]] = []

    def runner(
        *, seed: int, days: int, headless: bool, output: Path | None, force: bool
    ) -> SimulationResult:
        calls.append((seed, days, headless, output, force))
        return sample_result()

    stdout = StringIO()
    event_log = tmp_path / "events.jsonl"
    exit_code = main(
        ["simulate", "--seed", "9", "--days", "3", "--headless", "--output", str(event_log)],
        runner=runner,
        stdout=stdout,
    )

    assert exit_code == 0
    assert calls == [(9, 3, True, event_log, False)]
    assert "2026-08-26" in stdout.getvalue()
    assert "Rhea Vale" in stdout.getvalue()
    assert "실행 요약" in stdout.getvalue()


def test_replay_injects_event_log_and_hash_verification(tmp_path: Path) -> None:
    event_log = tmp_path / "events.jsonl"
    event_log.write_text("", encoding="utf-8")
    calls: list[tuple[Path, bool]] = []

    def replayer(*, event_log: Path, verify_hash: bool) -> SimulationResult:
        calls.append((event_log, verify_hash))
        return sample_result()

    stdout = StringIO()
    exit_code = main(
        ["replay", str(event_log), "--verify-hash"],
        replayer=replayer,
        stdout=stdout,
    )

    assert exit_code == 0
    assert calls == [(event_log, True)]
    assert "이동" in stdout.getvalue()


@pytest.mark.parametrize(
    "arguments",
    [
        ["simulate", "--seed", "1", "--days", "0"],
        ["simulate", "--seed", "-1", "--days", "1"],
        ["simulate", "--seed", "not-a-number", "--days", "1"],
        ["replay"],
    ],
)
def test_invalid_arguments_exit_abnormally(arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main(arguments)

    assert raised.value.code != 0


def test_module_cli_smoke_is_deterministic_and_offline() -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = "src"
    command = [
        sys.executable,
        "-m",
        "aincrad",
        "simulate",
        "--seed",
        "17",
        "--days",
        "2",
        "--headless",
    ]

    first = subprocess.run(
        command,
        cwd=Path(__file__).parents[2],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    second = subprocess.run(
        command,
        cwd=Path(__file__).parents[2],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert first.returncode == 0, first.stderr
    assert first.stdout == second.stdout
    assert "시드 17" in first.stdout
    assert "2일" in first.stdout


def test_replay_rejects_non_integer_or_out_of_sequence_tick(tmp_path: Path) -> None:
    event_log = tmp_path / "events.jsonl"
    EventLog(event_log).append(
        {
            "tick": True,
            "next_tick": 1,
            "adventurer_id": "rhea-vale",
            "action": "wait",
            "target_location_id": None,
            "quantity": 1,
            "details": [],
        }
    )

    with pytest.raises(ValueError, match="tick"):
        _default_replay(event_log=event_log, verify_hash=True)


def test_replay_hash_flag_controls_chain_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    event_log = tmp_path / "events.jsonl"
    EventLog(event_log).append(
        {
            "tick": 0,
            "next_tick": 1,
            "adventurer_id": "rhea-vale",
            "action": "wait",
            "target_location_id": None,
            "quantity": 1,
            "details": [],
        }
    )
    calls: list[str] = []
    original_read = EventLog.read
    original_verify = EventLog.verify

    def read(log: EventLog):
        calls.append("read")
        return original_read(log)

    def verify(log: EventLog):
        calls.append("verify")
        return original_verify(log)

    monkeypatch.setattr(EventLog, "read", read)
    monkeypatch.setattr(EventLog, "verify", verify)

    _default_replay(event_log=event_log, verify_hash=False)
    assert calls == ["read"]
    calls.clear()
    _default_replay(event_log=event_log, verify_hash=True)
    assert calls == ["verify"]


def test_replay_reconstructs_the_simulated_final_world(tmp_path: Path) -> None:
    event_log = tmp_path / "events.jsonl"
    simulated = _default_run(
        seed=42, days=2, headless=True, output=event_log, force=False
    )

    replayed = _default_replay(event_log=event_log, verify_hash=True)

    assert replayed.adventurers == simulated.adventurers
    assert replayed.summary.days == simulated.summary.days
    assert len(replayed.events) == len(simulated.events)


def test_simulate_publish_is_atomic_when_destination_appears(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    event_log = tmp_path / "events.jsonl"

    def competing_link(source: Path, destination: Path) -> None:
        del source
        destination.write_text("competing evidence", encoding="utf-8")
        raise FileExistsError(destination)

    monkeypatch.setattr("aincrad.cli.os.link", competing_link)

    with pytest.raises(FileExistsError):
        _default_run(seed=1, days=1, headless=True, output=event_log, force=False)
    assert event_log.read_text(encoding="utf-8") == "competing evidence"


def test_replay_rejects_event_outcome_that_disagrees_with_engine(tmp_path: Path) -> None:
    event_log = tmp_path / "events.jsonl"
    EventLog(event_log).append(
        {
            "tick": 0,
            "next_tick": 1,
            "adventurer_id": "rhea-vale",
            "action": "wait",
            "target_location_id": None,
            "quantity": 1,
            "reason": "invented_rejection",
        }
    )

    with pytest.raises(ValueError, match="engine result"):
        _default_replay(event_log=event_log, verify_hash=True)


def test_replay_rejects_tick_beyond_supported_limit() -> None:
    record = StoredEvent(
        seq=100_002,
        event={
            "tick": 100_001,
            "next_tick": 100_002,
            "adventurer_id": "rhea-vale",
            "action": "wait",
            "target_location_id": None,
            "quantity": 1,
            "details": [],
        },
        prev_event_hash=GENESIS_HASH,
        event_hash=GENESIS_HASH,
    )

    with pytest.raises(ValueError, match="supported limit"):
        _event_fields(record)
