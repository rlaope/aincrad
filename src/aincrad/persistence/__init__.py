from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, TypeVar

GENESIS_HASH = "0" * 64
MAX_RECORDS = 100_000
_RECORD_KEYS = {"seq", "event", "prev_event_hash", "event_hash"}
StateT = TypeVar("StateT")


class EventLogError(Exception):
    """Base class for event-log failures."""


class EventLogSchemaError(EventLogError):
    """A JSONL record does not conform to the event-log schema."""


class EventLogIntegrityError(EventLogError):
    """The sequence or cryptographic hash chain is invalid."""


@dataclass(frozen=True)
class StoredEvent:
    seq: int
    event: Any
    prev_event_hash: str
    event_hash: str


def to_json_value(value: Any) -> Any:
    """Convert supported event values to JSON-compatible primitives."""
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: to_json_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Enum):
        return to_json_value(value.value)
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("event mappings must have string keys")
        return {key: to_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported event value: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Return deterministic, compact UTF-8 JSON text."""
    return json.dumps(
        to_json_value(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _hash_record(seq: int, event: Any, prev_event_hash: str) -> str:
    payload = canonical_json(
        {"seq": seq, "event": event, "prev_event_hash": prev_event_hash}
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _is_hash(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


class EventLog:
    """Append-only JSONL event store with a verified SHA-256 hash chain."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, event: Any) -> StoredEvent:
        normalized = to_json_value(event)
        existing = self.verify() if self.path.exists() else ()
        if len(existing) >= MAX_RECORDS:
            raise EventLogSchemaError(f"event log exceeds {MAX_RECORDS} records")
        seq = len(existing) + 1
        previous = existing[-1].event_hash if existing else GENESIS_HASH
        record = StoredEvent(seq, normalized, previous, _hash_record(seq, normalized, previous))
        serialized = canonical_json(
            {
                "seq": record.seq,
                "event": record.event,
                "prev_event_hash": record.prev_event_hash,
                "event_hash": record.event_hash,
            }
        )
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(serialized + "\n")
            stream.flush()
        return record

    def verify(self) -> tuple[StoredEvent, ...]:
        return self._read(verify_hash=True)

    def read(self) -> tuple[StoredEvent, ...]:
        """Read schema-valid records without authenticating the hash chain."""

        return self._read(verify_hash=False)

    def _read(self, *, verify_hash: bool) -> tuple[StoredEvent, ...]:
        records: list[StoredEvent] = []
        expected_previous = GENESIS_HASH
        with self.path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if line_number > MAX_RECORDS:
                    raise EventLogSchemaError(f"event log exceeds {MAX_RECORDS} records")
                try:
                    raw = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    raise EventLogSchemaError(f"line {line_number}: invalid JSON") from exc
                if not isinstance(raw, dict) or set(raw) != _RECORD_KEYS:
                    raise EventLogSchemaError(f"line {line_number}: invalid record fields")
                seq = raw["seq"]
                if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1:
                    raise EventLogSchemaError(f"line {line_number}: seq must be a positive integer")
                if not _is_hash(raw["prev_event_hash"]) or not _is_hash(raw["event_hash"]):
                    raise EventLogSchemaError(f"line {line_number}: invalid hash field")
                expected_seq = len(records) + 1
                if seq != expected_seq:
                    raise EventLogIntegrityError(
                        f"line {line_number}: expected seq {expected_seq}, got {seq}"
                    )
                if verify_hash and raw["prev_event_hash"] != expected_previous:
                    raise EventLogIntegrityError(
                        f"line {line_number}: prev_event_hash does not match prior event"
                    )
                expected_hash = _hash_record(seq, raw["event"], expected_previous)
                if verify_hash and raw["event_hash"] != expected_hash:
                    raise EventLogIntegrityError(f"line {line_number}: event_hash mismatch")
                record = StoredEvent(
                    seq,
                    raw["event"],
                    raw["prev_event_hash"],
                    raw["event_hash"],
                )
                records.append(record)
                expected_previous = raw["event_hash"] if not verify_hash else expected_hash
        return tuple(records)


def fold(
    events: Iterable[Any],
    initial_state: StateT,
    reducer: Callable[[StateT, Any], StateT],
) -> StateT:
    """Fold event values over an initial state in their supplied order."""
    state = initial_state
    for event in events:
        state = reducer(state, event)
    return state


def replay(
    log: EventLog,
    initial_state: StateT,
    reducer: Callable[[StateT, Any], StateT],
) -> StateT:
    """Verify a log, then deterministically fold its event payloads."""
    return fold((record.event for record in log.verify()), initial_state, reducer)
