from __future__ import annotations

import pytest

from aincrad.agents import MemoryKind, MemoryRecord, MemoryStore


@pytest.mark.parametrize(
    "kind",
    [
        MemoryKind.TASK,
        MemoryKind.EPISODIC,
        MemoryKind.FACT,
        MemoryKind.SOCIAL,
        MemoryKind.STRATEGY,
    ],
)
def test_every_memory_kind_requires_event_evidence(kind: MemoryKind) -> None:
    record = MemoryRecord(
        id=f"memory-{kind.value}",
        owner_id="rhea",
        kind=kind,
        content=f"grounded {kind.value}",
        evidence_event_ids=("event-0042",),
        created_tick=42,
    )

    assert record.evidence_event_ids == ("event-0042",)


def test_memory_without_evidence_is_rejected() -> None:
    with pytest.raises(ValueError, match="evidence"):
        MemoryRecord("m-1", "rhea", MemoryKind.FACT, "unsupported", (), 1)


def test_store_traces_records_back_to_events_and_preserves_order() -> None:
    first = MemoryRecord("m-1", "rhea", MemoryKind.FACT, "wolves roam at dusk", ("e-7",), 7)
    second = MemoryRecord("m-2", "rhea", MemoryKind.STRATEGY, "bring fire", ("e-7", "e-9"), 9)
    store = MemoryStore()

    store.add(first)
    store.add(second)

    assert store.get("m-1") is first
    assert store.for_event("e-7") == (first, second)
    assert store.for_owner("rhea", kind=MemoryKind.STRATEGY) == (second,)
    assert store.all() == (first, second)


def test_store_rejects_duplicate_record_ids() -> None:
    record = MemoryRecord("m-1", "rhea", MemoryKind.TASK, "return home", ("e-1",), 1)
    store = MemoryStore((record,))

    with pytest.raises(ValueError, match="duplicate"):
        store.add(record)
