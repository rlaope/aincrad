from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return tuple(sorted((str(key), _freeze(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class ServiceRequest:
    actor_id: str
    operation: str
    item_id: str | None = None


@dataclass(frozen=True, slots=True)
class ServiceResponse:
    npc_id: str
    actor_id: str
    operation: str
    effects: tuple[tuple[str, Any], ...]


@dataclass(frozen=True, slots=True)
class RuleBasedNPCService:
    """Deterministic service table for ordinary NPCs; no AI policy is involved."""

    npc_id: str
    service: str
    rules: Mapping[str, Mapping[str, Any]]

    def handle(self, request: ServiceRequest) -> ServiceResponse:
        key = request.operation
        if request.item_id is not None:
            key = f"{key}:{request.item_id}"
        try:
            configured_effects = self.rules[key]
        except KeyError as error:
            raise LookupError(f"unsupported {self.service} operation: {key}") from error
        effects = tuple(
            sorted((str(name), _freeze(value)) for name, value in configured_effects.items())
        )
        return ServiceResponse(self.npc_id, request.actor_id, request.operation, effects)
