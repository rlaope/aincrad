from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class MemoryKind(StrEnum):
    TASK = "task"
    EPISODIC = "episodic"
    FACT = "fact"
    SOCIAL = "social"
    STRATEGY = "strategy"


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    id: str
    owner_id: str
    kind: MemoryKind
    content: str
    evidence_event_ids: tuple[str, ...]
    created_tick: int

    def __post_init__(self) -> None:
        if not self.id or not self.owner_id or not self.content:
            raise ValueError("memory id, owner_id, and content must be non-empty")
        if not self.evidence_event_ids or any(not item for item in self.evidence_event_ids):
            raise ValueError("memory requires at least one evidence event_id")
        if len(set(self.evidence_event_ids)) != len(self.evidence_event_ids):
            raise ValueError("evidence event_ids must be unique")
        if self.created_tick < 0:
            raise ValueError("created_tick must be non-negative")


class MemoryStore:
    """In-memory grounded record index; it never derives unsupported memories."""

    __slots__ = ("_records", "_by_id", "_by_event")

    def __init__(self, records: Iterable[MemoryRecord] = ()) -> None:
        self._records: list[MemoryRecord] = []
        self._by_id: dict[str, MemoryRecord] = {}
        self._by_event: dict[str, list[MemoryRecord]] = {}
        for record in records:
            self.add(record)

    def add(self, record: MemoryRecord) -> None:
        if record.id in self._by_id:
            raise ValueError(f"duplicate memory record id: {record.id}")
        self._records.append(record)
        self._by_id[record.id] = record
        for event_id in record.evidence_event_ids:
            self._by_event.setdefault(event_id, []).append(record)

    def get(self, record_id: str) -> MemoryRecord:
        return self._by_id[record_id]

    def all(self) -> tuple[MemoryRecord, ...]:
        return tuple(self._records)

    def for_event(self, event_id: str) -> tuple[MemoryRecord, ...]:
        return tuple(self._by_event.get(event_id, ()))

    def for_owner(
        self, owner_id: str, *, kind: MemoryKind | None = None
    ) -> tuple[MemoryRecord, ...]:
        return tuple(
            record
            for record in self._records
            if record.owner_id == owner_id and (kind is None or record.kind is kind)
        )
