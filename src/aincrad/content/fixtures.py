from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal, NotRequired, TypedDict, cast

FacilityKind = Literal["shop", "inn", "quest_hall", "plaza", "tavern"]
FloorKind = Literal["dungeon_floor", "boss_room"]


class FacilityFixture(TypedDict):
    id: str
    kind: FacilityKind
    name: str
    description: str
    services: list[str]
    connections: list[str]


class TownFixture(TypedDict):
    id: str
    name: str
    kind: Literal["town"]
    description: str
    connections: list[str]
    facilities: list[FacilityFixture]


class CompletionFixture(TypedDict):
    boss_id: str
    rewards: list[str]
    transition_id: str
    next_world_floor: int
    unlock_description: str


class FloorFixture(TypedDict):
    id: str
    depth: int
    kind: FloorKind
    name: str
    description: str
    connections: list[str]
    completion: NotRequired[CompletionFixture]


class DungeonFixture(TypedDict):
    id: str
    name: str
    floors: list[FloorFixture]


class WorldFixture(TypedDict):
    schema_version: int
    world_id: str
    title: str
    towns: list[TownFixture]
    hunting_grounds: list[dict[str, object]]
    dungeons: list[DungeonFixture]
    adventurers: list[dict[str, object]]
    npcs: list[dict[str, object]]


class LoadedWorldFixture(WorldFixture):
    location_ids: tuple[str, ...]


class FixtureSchemaError(ValueError):
    """Raised when a content fixture violates the supported world schema."""


def _object(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise FixtureSchemaError(f"{field} must be an object")
    return cast(Mapping[str, object], value)


def _objects(value: object, field: str) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        raise FixtureSchemaError(f"{field} must be a list")
    if any(not isinstance(item, Mapping) for item in value):
        raise FixtureSchemaError(f"{field} entries must be objects")
    return [cast(Mapping[str, object], item) for item in value]


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FixtureSchemaError(f"{field} must be a non-empty string")
    return value


def _texts(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise FixtureSchemaError(f"{field} must be a non-empty list")
    return [_text(item, f"{field} entry") for item in value]


def _connections(place: Mapping[str, object], field: str) -> list[str]:
    value = place.get("connections")
    if not isinstance(value, list):
        raise FixtureSchemaError(f"{field}.connections must be a list")
    return [_text(item, f"{field}.connections entry") for item in value]


def _validate_facilities(town: Mapping[str, object]) -> list[Mapping[str, object]]:
    facilities = _objects(town.get("facilities"), "town.facilities")
    expected_kinds: set[str] = {"shop", "inn", "quest_hall", "plaza", "tavern"}
    if len(facilities) != 5 or {item.get("kind") for item in facilities} != expected_kinds:
        raise FixtureSchemaError(
            "Emberfall facilities must contain shop, inn, quest_hall, plaza, and tavern"
        )
    for facility in facilities:
        facility_id = _text(facility.get("id"), "facility.id")
        _text(facility.get("description"), f"facility {facility_id}.description")
        _texts(facility.get("services"), f"facility {facility_id}.services")
        _connections(facility, f"facility {facility_id}")
    return facilities


def _validate_dungeon(dungeon: Mapping[str, object]) -> list[Mapping[str, object]]:
    floors = _objects(dungeon.get("floors"), "dungeon.floors")
    depths = [item.get("depth") for item in floors]
    if depths != list(range(1, 11)):
        raise FixtureSchemaError("dungeon floor depths must be consecutive integers 1 through 10")
    for floor in floors:
        floor_id = _text(floor.get("id"), "dungeon floor.id")
        _text(floor.get("description"), f"dungeon floor {floor_id}.description")
        _connections(floor, f"dungeon floor {floor_id}")
    if any(floor.get("kind") != "dungeon_floor" for floor in floors[:-1]):
        raise FixtureSchemaError("dungeon depths 1 through 9 must be dungeon_floor")
    boss = floors[-1]
    if boss.get("kind") != "boss_room":
        raise FixtureSchemaError("dungeon depth 10 must be boss_room")
    completion = _object(boss.get("completion"), "boss_room.completion")
    _text(completion.get("boss_id"), "boss_room.completion.boss_id")
    _texts(completion.get("rewards"), "boss_room.completion.rewards")
    _text(completion.get("transition_id"), "boss_room.completion.transition_id")
    _text(completion.get("unlock_description"), "boss_room.completion.unlock_description")
    next_floor = completion.get("next_world_floor")
    if not isinstance(next_floor, int) or isinstance(next_floor, bool) or next_floor != 2:
        raise FixtureSchemaError("boss_room.completion.next_world_floor must be integer 2")
    return floors


def _unique_ids(items: Sequence[Mapping[str, object]], field: str) -> list[str]:
    ids = [_text(item.get("id"), f"{field}.id") for item in items]
    if len(ids) != len(set(ids)):
        raise FixtureSchemaError(f"{field} ids must be unique")
    return ids


def validate_world_fixture(world: object) -> WorldFixture:
    root = _object(world, "world fixture root")
    required = {
        "schema_version",
        "world_id",
        "title",
        "towns",
        "hunting_grounds",
        "dungeons",
        "adventurers",
        "npcs",
    }
    missing = required.difference(root)
    if missing:
        raise FixtureSchemaError(f"missing fields: {', '.join(sorted(missing))}")
    if root["schema_version"] != 1:
        raise FixtureSchemaError("unsupported schema_version")
    if root["world_id"] != "glassfrontier":
        raise FixtureSchemaError("world_id must be glassfrontier")
    if root["title"] != "The Glass Frontier":
        raise FixtureSchemaError("title must be The Glass Frontier")

    towns = _objects(root["towns"], "towns")
    grounds = _objects(root["hunting_grounds"], "hunting_grounds")
    dungeons = _objects(root["dungeons"], "dungeons")
    adventurers = _objects(root["adventurers"], "adventurers")
    npcs = _objects(root["npcs"], "npcs")
    if len(towns) != 1 or len(grounds) != 1:
        raise FixtureSchemaError("fixture requires exactly one town and one hunting ground")
    if towns[0].get("id") != "emberfall":
        raise FixtureSchemaError("fixture town must be Emberfall")
    if len(dungeons) != 1 or dungeons[0].get("id") != "starless-vault":
        raise FixtureSchemaError("fixture requires exactly one Starless Vault dungeon")
    if len(adventurers) != 3:
        raise FixtureSchemaError("fixture requires exactly three candidate adventurers")

    facilities = _validate_facilities(towns[0])
    floors = _validate_dungeon(dungeons[0])
    places = [*towns, *facilities, *grounds, *floors]
    location_ids = _unique_ids(places, "location")
    known_locations = set(location_ids)
    for place in places:
        place_id = cast(str, place["id"])
        unknown = set(_connections(place, f"location {place_id}")) - known_locations
        if unknown:
            unknown_id = sorted(unknown)[0]
            raise FixtureSchemaError(f"location {place_id} has unknown connection: {unknown_id}")
    for current, following in zip(floors, floors[1:], strict=False):
        if following["id"] not in _connections(current, f"floor {current['id']}"):
            raise FixtureSchemaError("dungeon floor connections must link each depth forward")
        if current["id"] not in _connections(following, f"floor {following['id']}"):
            raise FixtureSchemaError("dungeon floor connections must link each depth backward")

    _unique_ids(adventurers, "adventurer")
    if any(item.get("location_id") not in known_locations for item in adventurers):
        raise FixtureSchemaError("adventurer location must reference a known location")

    facility_by_id = {cast(str, item["id"]): item for item in facilities}
    if len(npcs) != 5 or {npc.get("location_id") for npc in npcs} != set(facility_by_id):
        raise FixtureSchemaError("fixture requires one rule-based NPC for each Emberfall facility")
    _unique_ids(npcs, "NPC")
    for npc in npcs:
        npc_id = _text(npc.get("id"), "NPC.id")
        if npc.get("controller") != "rules":
            raise FixtureSchemaError("general NPC controller must be rules")
        location_id = _text(npc.get("location_id"), "NPC.location_id")
        if location_id not in facility_by_id:
            raise FixtureSchemaError(f"NPC {npc_id} location must reference an Emberfall facility")
        facility = facility_by_id[location_id]
        if npc.get("service") != facility.get("kind"):
            raise FixtureSchemaError(f"NPC {npc_id} service must match its facility kind")
        rules = npc.get("rules")
        if not isinstance(rules, Mapping) or not rules:
            raise FixtureSchemaError(f"NPC {npc_id} rules must be a non-empty object")

    return cast(WorldFixture, root)


def load_world_fixture(path: str | Path) -> LoadedWorldFixture:
    try:
        with Path(path).open(encoding="utf-8") as stream:
            raw: object = json.load(stream)
    except json.JSONDecodeError as error:
        raise FixtureSchemaError(f"invalid JSON fixture: {error.msg}") from error
    world = validate_world_fixture(raw)
    result = cast(LoadedWorldFixture, dict(world))
    result["location_ids"] = tuple(
        [item["id"] for item in world["towns"]]
        + [facility["id"] for item in world["towns"] for facility in item["facilities"]]
        + [cast(str, item["id"]) for item in world["hunting_grounds"]]
        + [floor["id"] for dungeon in world["dungeons"] for floor in dungeon["floors"]]
    )
    return result
