from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from aincrad.content.actions import action_catalog_from_fixture, interaction_catalog_from_fixture
from aincrad.content.fixtures import load_packaged_world_fixture
from aincrad.domain import (
    Adventurer,
    CharacterClass,
    EdgeKind,
    Location,
    LocationKind,
    Stats,
    TravelEdge,
    WorldState,
)

_CHARACTER_CLASSES = {
    "vanguard": CharacterClass.WARRIOR,
    "pathfinder": CharacterClass.ARCHER,
    "arcanist": CharacterClass.MAGE,
}


def _legacy_edge_kind(location_id: str, target_id: str) -> EdgeKind:
    endpoints = frozenset((location_id, target_id))
    if location_id.startswith("emberfall-") or target_id.startswith("emberfall-"):
        return EdgeKind.SCENE
    if endpoints == {"mossreach", "vault-1"}:
        return EdgeKind.DUNGEON_GATE
    if location_id.startswith("vault-") and target_id.startswith("vault-"):
        return EdgeKind.DUNGEON
    return EdgeKind.OVERLAND


def _legacy_geography(location_id: str) -> tuple[str, str]:
    if location_id.startswith("emberfall-"):
        return "emberfall-town", "town-facility"
    if location_id == "emberfall":
        return "emberfall-town", "shard-spring"
    if location_id == "mossreach":
        return "mossreach-wilds", "glass-upland"
    return "starless-vault", "vault-depth"


def _record_edges(record: Mapping[str, object], *, content_revision: str) -> tuple[TravelEdge, ...]:
    if content_revision == "current":
        return tuple(
            TravelEdge(edge["to"], EdgeKind(edge["kind"]), edge["path_ko"])
            for edge in cast(Sequence[Mapping[str, str]], record["edges"])
        )
    location_id = cast(str, record["id"])
    return tuple(
        TravelEdge(target_id, _legacy_edge_kind(location_id, target_id), "기록된 연결 길")
        for target_id in cast(Sequence[str], record["connections"])
    )


def create_initial_world(*, content_revision: str = "current") -> WorldState:
    """Create a deterministic initial state from one trusted content revision."""

    fixture = load_packaged_world_fixture(revision=content_revision)
    catalog = action_catalog_from_fixture(fixture)
    interaction_catalog = interaction_catalog_from_fixture(fixture)
    locations: dict[str, Location] = {}
    town = fixture["towns"][0]
    location_records = [
        town,
        *town["facilities"],
        *fixture["hunting_grounds"],
        *fixture["dungeons"][0]["floors"],
    ]
    for record in location_records:
        record_data = cast(Mapping[str, object], record)
        location_id = record["id"]
        raw_kind = record["kind"]
        kind = (
            LocationKind.TOWN
            if raw_kind == "town" or location_id.startswith("emberfall-")
            else LocationKind.HUNTING_GROUND
            if raw_kind == "hunting_ground"
            else LocationKind.DUNGEON
        )
        completion = record.get("completion")
        completion_data = cast(dict[str, object], completion) if completion is not None else {}
        region, terrain = (
            (cast(str, record_data["region"]), cast(str, record_data["terrain"]))
            if content_revision == "current"
            else _legacy_geography(location_id)
        )
        locations[location_id] = Location(
            id=location_id,
            name=record["name"],
            kind=kind,
            region=region,
            terrain=terrain,
            edges=_record_edges(record, content_revision=content_revision),
            stage=cast(int | None, record.get("depth")),
            is_boss_room=raw_kind == "boss_room",
            boss_id=cast(str | None, completion_data.get("boss_id")),
            transition_id=cast(str | None, completion_data.get("transition_id")),
            next_world_floor=cast(int | None, completion_data.get("next_world_floor")),
            description=record["description"],
            services=tuple(cast(Sequence[str], record.get("services", []))),
            contextual_actions=catalog[location_id],
            interactions=interaction_catalog.get(location_id, ()),
        )
    adventurers: dict[str, Adventurer] = {}
    for candidate in fixture["adventurers"]:
        data = cast(Mapping[str, object], candidate)
        candidate_id = cast(str, data["id"])
        stats = cast(Mapping[str, int], data["stats"])
        adventurers[candidate_id] = Adventurer(
            id=candidate_id,
            name=cast(str, data["name"]),
            location_id=cast(str, data["location_id"]),
            stats=Stats(
                hp=stats["hp"],
                max_hp=stats["max_hp"],
                mp=stats["mp"],
                max_mp=stats["max_mp"],
            ),
            gold=5,
            character_class=_CHARACTER_CLASSES[cast(str, data["role"])],
        )
    return WorldState(tick=0, locations=locations, adventurers=adventurers)
