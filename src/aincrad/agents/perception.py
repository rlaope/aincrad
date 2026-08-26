from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, TypeAlias

FrozenValue: TypeAlias = (
    str
    | int
    | float
    | bool
    | None
    | tuple["FrozenValue", ...]
    | tuple[tuple[str, "FrozenValue"], ...]
)
FrozenFields: TypeAlias = tuple[tuple[str, FrozenValue], ...]


def _freeze(value: Any) -> FrozenValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return tuple(sorted((str(key), _freeze(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    raise TypeError(f"observations must be JSON-compatible, got {type(value).__name__}")


def _fields(values: Mapping[str, Any]) -> FrozenFields:
    return tuple(sorted((str(key), _freeze(value)) for key, value in values.items()))


@dataclass(frozen=True, slots=True)
class Observation:
    """Explicit visibility boundary produced by the trusted world engine."""

    tick: int
    actor_id: str
    location_id: str
    self_state: Mapping[str, Any]
    visible_entities: tuple[Mapping[str, Any], ...] = ()
    visible_entity_fields: tuple[str, ...] = ("id", "kind", "display_name")


@dataclass(frozen=True, slots=True)
class Perception:
    """Detached immutable input for an AI policy."""

    tick: int
    actor_id: str
    location_id: str
    self_state: FrozenFields
    visible_entities: tuple[FrozenFields, ...] = ()



def perceive(observation: Observation) -> Perception:
    """Copy only explicitly observable fields; never expose a WorldState object."""

    allowed = frozenset(observation.visible_entity_fields)
    entities = tuple(
        _fields({key: value for key, value in entity.items() if key in allowed})
        for entity in observation.visible_entities
    )
    return Perception(
        tick=observation.tick,
        actor_id=observation.actor_id,
        location_id=observation.location_id,
        self_state=_fields(observation.self_state),
        visible_entities=entities,
    )
