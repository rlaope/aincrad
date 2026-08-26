from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from aincrad.persistence import (
    EventLog,
    EventLogIntegrityError,
    EventLogSchemaError,
    canonical_json,
    replay,
)


@dataclass(frozen=True)
class Moved:
    actor: str
    destination: str


def test_canonical_json_sorts_keys_and_serializes_dataclass() -> None:
    assert canonical_json({"z": 1, "event": Moved("rhea", "vault-2"), "a": True}) == (
        '{"a":true,"event":{"actor":"rhea","destination":"vault-2"},"z":1}'
    )


def test_append_only_jsonl_builds_and_validates_hash_chain(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    log = EventLog(path)

    first = log.append(Moved("rhea", "vault-2"))
    second = log.append({"kind": "rested", "actor": "rhea"})

    records = log.verify()
    assert records == (first, second)
    assert [record.seq for record in records] == [1, 2]
    assert second.prev_event_hash == first.event_hash
    assert len(first.event_hash) == 64
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def _three_event_log(path: Path) -> EventLog:
    log = EventLog(path)
    for amount in (2, 3, -1):
        log.append({"kind": "hp_changed", "amount": amount})
    return log


def test_verification_rejects_modified_event(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    log = _three_event_log(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[1])
    record["event"]["amount"] = 300
    lines[1] = canonical_json(record)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(EventLogIntegrityError, match="event_hash mismatch"):
        log.verify()


def test_verification_rejects_deleted_event(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    log = _three_event_log(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join((lines[0], lines[2])) + "\n", encoding="utf-8")

    with pytest.raises(EventLogIntegrityError, match="expected seq 2"):
        log.verify()


def test_verification_rejects_reordered_events(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    log = _three_event_log(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[0], lines[1] = lines[1], lines[0]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(EventLogIntegrityError, match="expected seq 1"):
        log.verify()


def test_replay_of_same_log_is_deterministic(tmp_path: Path) -> None:
    log = _three_event_log(tmp_path / "events.jsonl")

    def apply_hp(hp: int, event: object) -> int:
        assert isinstance(event, dict)
        return hp + event["amount"]

    first = replay(log, 10, apply_hp)
    second = replay(log, 10, apply_hp)

    assert first == second == 14


def test_malformed_json_is_reported_as_schema_error(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text('{"seq": 1, definitely-not-json}\n', encoding="utf-8")

    with pytest.raises(EventLogSchemaError, match="line 1: invalid JSON"):
        EventLog(path).verify()


def test_missing_log_file_error_is_not_silenced(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        EventLog(tmp_path / "missing.jsonl").verify()


def test_serialization_rejects_non_string_mapping_keys() -> None:
    with pytest.raises(TypeError, match="string keys"):
        canonical_json({1: "unsafe"})
