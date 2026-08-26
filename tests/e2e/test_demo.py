from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "aincrad", *args],
        check=False,
        capture_output=True,
        text=True,
    )


def test_simulate_then_replay_is_a_working_offline_path(tmp_path: Path) -> None:
    output = tmp_path / "demo"

    simulated = run_cli(
        "simulate",
        "--seed",
        "42",
        "--days",
        "1",
        "--headless",
        "--output",
        str(output),
    )

    assert simulated.returncode == 0, simulated.stderr
    assert "1일차" in simulated.stdout
    assert "2일차" not in simulated.stdout
    event_log = output / "events.jsonl"
    assert event_log.is_file()
    assert event_log.read_text(encoding="utf-8").strip()

    replayed = run_cli("replay", str(event_log), "--verify-hash")

    assert replayed.returncode == 0, replayed.stderr
    assert "검증" in replayed.stdout
    assert "레아 베일" in replayed.stdout


def test_simulate_refuses_to_overwrite_event_evidence_without_force(tmp_path: Path) -> None:
    event_log = tmp_path / "events.jsonl"
    event_log.write_text("evidence", encoding="utf-8")

    refused = run_cli(
        "simulate",
        "--seed",
        "1",
        "--days",
        "1",
        "--headless",
        "--output",
        str(event_log),
    )
    assert refused.returncode != 0
    assert event_log.read_text(encoding="utf-8") == "evidence"

    replaced = run_cli(
        "simulate",
        "--seed",
        "1",
        "--days",
        "1",
        "--headless",
        "--output",
        str(event_log),
        "--force",
    )
    assert replaced.returncode == 0, replaced.stderr
    assert event_log.read_text(encoding="utf-8") != "evidence"
