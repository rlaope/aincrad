from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


class FixtureSchemaError(ValueError):
    pass


def validate_world_fixture(world: Mapping[str, Any]) -> None:
    required = {"schema_version", "towns", "hunting_grounds", "dungeons", "adventurers", "npcs"}
    missing = required.difference(world)
    if missing:
        raise FixtureSchemaError(f"missing fields: {', '.join(sorted(missing))}")
    if world["schema_version"] != 1:
        raise FixtureSchemaError("unsupported schema_version")
    if len(world["towns"]) != 1 or len(world["hunting_grounds"]) != 1:
        raise FixtureSchemaError("fixture requires exactly one town and one hunting ground")
    if len(world["dungeons"]) != 1:
        raise FixtureSchemaError("fixture requires exactly one dungeon")
    if [floor.get("depth") for floor in world["dungeons"][0].get("floors", [])] != [1, 2, 3]:
        raise FixtureSchemaError("dungeon floors must have depths 1, 2, and 3")
    if len(world["adventurers"]) != 3:
        raise FixtureSchemaError("fixture requires exactly three adventurers")

    places = [*world["towns"], *world["hunting_grounds"], *world["dungeons"][0]["floors"]]
    location_ids = [place.get("id") for place in places]
    if any(not item for item in location_ids) or len(location_ids) != len(set(location_ids)):
        raise FixtureSchemaError("location ids must be non-empty and unique")
    adventurer_ids = [item.get("id") for item in world["adventurers"]]
    if any(not item for item in adventurer_ids) or len(adventurer_ids) != len(set(adventurer_ids)):
        raise FixtureSchemaError("adventurer ids must be non-empty and unique")
    if any(item.get("location_id") not in location_ids for item in world["adventurers"]):
        raise FixtureSchemaError("adventurer location must reference a known location")
    if any(npc.get("controller") != "rules" for npc in world["npcs"]):
        raise FixtureSchemaError("general NPC controller must be rules")


def load_world_fixture(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as stream:
        world = json.load(stream)
    if not isinstance(world, dict):
        raise FixtureSchemaError("world fixture root must be an object")
    validate_world_fixture(world)
    result = dict(world)
    result["location_ids"] = tuple(
        [item["id"] for item in world["towns"]]
        + [item["id"] for item in world["hunting_grounds"]]
        + [item["id"] for item in world["dungeons"][0]["floors"]]
    )
    return result
