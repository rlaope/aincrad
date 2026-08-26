from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType


class LocationKind(StrEnum):
    TOWN = "town"
    HUNTING_GROUND = "hunting_ground"
    DUNGEON = "dungeon"


class Activity(StrEnum):
    IDLE = "idle"
    MOVING = "moving"
    RESTING = "resting"
    GATHERING = "gathering"
    TRADING = "trading"
    WAITING = "waiting"


class ActionKind(StrEnum):
    MOVE = "move"
    REST = "rest"
    GATHER = "gather"
    TRADE = "trade"
    WAIT = "wait"


@dataclass(frozen=True, slots=True)
class Stats:
    hp: int
    max_hp: int
    mp: int
    max_mp: int

    def __post_init__(self) -> None:
        if self.max_hp < 0 or self.max_mp < 0:
            raise ValueError("maximum stats cannot be negative")
        if not 0 <= self.hp <= self.max_hp:
            raise ValueError("hp must be between zero and max_hp")
        if not 0 <= self.mp <= self.max_mp:
            raise ValueError("mp must be between zero and max_mp")


@dataclass(frozen=True, slots=True)
class Location:
    id: str
    name: str
    kind: LocationKind
    connections: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Adventurer:
    id: str
    name: str
    location_id: str
    stats: Stats
    activity: Activity = Activity.IDLE
    gold: int = 0
    resources: int = 0

    def __post_init__(self) -> None:
        if self.gold < 0 or self.resources < 0:
            raise ValueError("wealth cannot be negative")


@dataclass(frozen=True, slots=True)
class ActionIntent:
    adventurer_id: str
    action: ActionKind | str
    target_location_id: str | None = None
    quantity: int = 1


@dataclass(frozen=True, slots=True)
class WorldState:
    tick: int
    locations: Mapping[str, Location] = field(default_factory=dict)
    adventurers: Mapping[str, Adventurer] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.tick < 0:
            raise ValueError("tick cannot be negative")
        locations = dict(self.locations)
        adventurers = dict(self.adventurers)
        if any(key != value.id for key, value in locations.items()):
            raise ValueError("location keys must match ids")
        if any(key != value.id for key, value in adventurers.items()):
            raise ValueError("adventurer keys must match ids")
        if any(a.location_id not in locations for a in adventurers.values()):
            raise ValueError("every adventurer must occupy an existing location")
        object.__setattr__(self, "locations", MappingProxyType(locations))
        object.__setattr__(self, "adventurers", MappingProxyType(adventurers))
