from __future__ import annotations

from dataclasses import dataclass

from .models import ActionKind


@dataclass(frozen=True, slots=True)
class DomainEvent:
    tick: int
    adventurer_id: str
    action: ActionKind | str
    next_tick: int
    target_location_id: str | None
    quantity: int


@dataclass(frozen=True, slots=True)
class ActionSucceeded(DomainEvent):
    details: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class ActionRejected(DomainEvent):
    reason: str
