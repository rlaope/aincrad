from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from importlib.resources import as_file, files
from pathlib import Path
from typing import Literal, NotRequired, TypedDict, cast

from .actions import EXPECTED_FACILITY_SERVICES, expected_action_kinds

FacilityKind = Literal["shop", "inn", "quest_hall", "plaza", "tavern"]
FloorKind = Literal["dungeon_floor", "boss_room"]


class ActionFixture(TypedDict):
    id: str
    kind: str
    label_ko: str
    description_ko: str
    outcome_code: str
    service: NotRequired[str]
    clue_code: NotRequired[str]
    encounter_code: NotRequired[str]
    requires_completed_contract: NotRequired[bool]
    gold_delta: NotRequired[int]
    gold_per_resource: NotRequired[int]
    resource_delta: NotRequired[int]
    restore_hp: NotRequired[int]
    restore_mp: NotRequired[int]


class FacilityFixture(TypedDict):
    id: str
    kind: FacilityKind
    name: str
    description: str
    services: list[str]
    actions: list[ActionFixture]
    connections: list[str]
    interactions: NotRequired[list[dict[str, object]]]


class TownFixture(TypedDict):
    id: str
    name: str
    kind: Literal["town"]
    description: str
    actions: list[ActionFixture]
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
    actions: list[ActionFixture]
    connections: list[str]
    completion: NotRequired[CompletionFixture]


class DungeonFixture(TypedDict):
    id: str
    name: str
    floors: list[FloorFixture]


class HuntingGroundFixture(TypedDict):
    id: str
    name: str
    kind: Literal["hunting_ground"]
    description: str
    actions: list[ActionFixture]
    connections: list[str]


class WorldFixture(TypedDict):
    schema_version: int
    world_id: str
    title: str
    towns: list[TownFixture]
    hunting_grounds: list[HuntingGroundFixture]
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


def _integer(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise FixtureSchemaError(f"{field} must be an integer")
    return value


def _validate_actions(
    place: Mapping[str, object],
    field: str,
    *,
    expected_kinds_for: Callable[[str], tuple[str, ...]] | None = None,
) -> None:
    location_id = _text(place.get("id"), f"{field}.id")
    resolver = expected_action_kinds if expected_kinds_for is None else expected_kinds_for
    try:
        expected_kinds = resolver(location_id)
    except KeyError as error:
        raise FixtureSchemaError(
            f"location {location_id} has no canonical action coverage"
        ) from error
    actions = _objects(place.get("actions"), f"location {location_id}.actions")
    actual_kinds = [
        _text(action.get("kind"), f"location {location_id}.actions.kind") for action in actions
    ]
    if tuple(actual_kinds) != expected_kinds:
        raise FixtureSchemaError(f"location {location_id} actions must match canonical coverage")
    action_ids = [
        _text(action.get("id"), f"location {location_id}.actions.id") for action in actions
    ]
    if len(action_ids) != len(set(action_ids)):
        raise FixtureSchemaError(f"location {location_id} action ids must be unique")
    for action in actions:
        action_id = _text(action.get("id"), f"location {location_id}.actions.id")
        _text(action.get("label_ko"), f"action {action_id}.label_ko")
        _text(action.get("description_ko"), f"action {action_id}.description_ko")
        _text(action.get("outcome_code"), f"action {action_id}.outcome_code")
        for code in ("clue_code", "encounter_code", "service"):
            if code in action:
                _text(action[code], f"action {action_id}.{code}")
        if "requires_completed_contract" in action and not isinstance(
            action["requires_completed_contract"], bool
        ):
            raise FixtureSchemaError(
                f"action {action_id}.requires_completed_contract must be boolean"
            )
        for number in (
            "gold_delta",
            "gold_per_resource",
            "resource_delta",
            "restore_hp",
            "restore_mp",
        ):
            if number in action:
                _integer(action[number], f"action {action_id}.{number}")


def _validate_facilities(
    town: Mapping[str, object],
    *,
    expected_kinds_for: Callable[[str], tuple[str, ...]] | None,
    expected_facility_services: Mapping[str, tuple[str, ...]] | None,
) -> list[Mapping[str, object]]:
    facilities = _objects(town.get("facilities"), "town.facilities")
    expected_kinds: set[str] = {"shop", "inn", "quest_hall", "plaza", "tavern"}
    if len(facilities) != 5 or {item.get("kind") for item in facilities} != expected_kinds:
        raise FixtureSchemaError(
            "Emberfall facilities must contain shop, inn, quest_hall, plaza, and tavern"
        )
    for facility in facilities:
        facility_id = _text(facility.get("id"), "facility.id")
        _text(facility.get("description"), f"facility {facility_id}.description")
        services = tuple(_texts(facility.get("services"), f"facility {facility_id}.services"))
        facility_services = (
            EXPECTED_FACILITY_SERVICES
            if expected_facility_services is None
            else expected_facility_services
        )
        if services != facility_services[facility_id]:
            raise FixtureSchemaError(
                f"facility {facility_id} services must match canonical coverage"
            )
        _validate_actions(facility, "facility", expected_kinds_for=expected_kinds_for)
        action_services = tuple(
            _text(action.get("service"), f"facility {facility_id}.actions.service")
            for action in _objects(facility.get("actions"), f"facility {facility_id}.actions")
        )
        if action_services != services:
            raise FixtureSchemaError(f"facility {facility_id} actions must cover its services")
        _connections(facility, f"facility {facility_id}")
    return facilities


def _validate_dungeon(
    dungeon: Mapping[str, object], *, expected_kinds_for: Callable[[str], tuple[str, ...]] | None
) -> list[Mapping[str, object]]:
    floors = _objects(dungeon.get("floors"), "dungeon.floors")
    depths = [item.get("depth") for item in floors]
    if depths != list(range(1, 11)):
        raise FixtureSchemaError("dungeon floor depths must be consecutive integers 1 through 10")
    for floor in floors:
        floor_id = _text(floor.get("id"), "dungeon floor.id")
        _text(floor.get("description"), f"dungeon floor {floor_id}.description")
        _validate_actions(floor, "dungeon floor", expected_kinds_for=expected_kinds_for)
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


def _validate_interactions(
    facilities: Sequence[Mapping[str, object]], npcs: Sequence[Mapping[str, object]]
) -> None:
    npc_locations = {str(npc["id"]): str(npc["location_id"]) for npc in npcs}
    incident_ids: set[str] = set()
    for facility in facilities:
        raw_interactions = facility.get("interactions", [])
        if not isinstance(raw_interactions, list):
            raise FixtureSchemaError("facility interactions must be a list")
        for incident in _objects(raw_interactions, "facility.interactions"):
            if set(incident) != {"id", "npc_id", "title_ko", "entry_prompt_id", "prompts"}:
                raise FixtureSchemaError("interaction keys must be exact")
            incident_id = _text(incident["id"], "interaction.id")
            if incident_id in incident_ids:
                raise FixtureSchemaError("interaction ids must be world-unique")
            incident_ids.add(incident_id)
            npc_id = _text(incident["npc_id"], "interaction.npc_id")
            if npc_locations.get(npc_id) != facility["id"]:
                raise FixtureSchemaError("interaction NPC must be resident at its facility")
            entry = _text(incident["entry_prompt_id"], "interaction.entry_prompt_id")
            prompts = _objects(incident["prompts"], "interaction.prompts")
            prompt_ids = {_text(prompt.get("id"), "interaction.prompt.id") for prompt in prompts}
            if entry not in prompt_ids or not prompts or len(prompt_ids) != len(prompts):
                raise FixtureSchemaError("interaction prompts must be unique and have an entry")
            reachable = {entry}
            outcomes: set[str] = set()
            for prompt in prompts:
                if set(prompt) != {"id", "text_ko", "responses"}:
                    raise FixtureSchemaError("interaction prompt keys must be exact")
                responses = _objects(prompt["responses"], "interaction.responses")
                response_ids: set[str] = set()
                aliases: set[str] = set()
                for response in responses:
                    if set(response) - {
                        "id",
                        "label_ko",
                        "aliases_ko",
                        "next_prompt_id",
                        "terminal",
                    }:
                        raise FixtureSchemaError("interaction response has unknown keys")
                    response_id = _text(response.get("id"), "interaction.response.id")
                    if response_id in response_ids:
                        raise FixtureSchemaError("interaction response ids must be unique")
                    response_ids.add(response_id)
                    _text(response.get("label_ko"), "interaction.response.label_ko")
                    raw_aliases = response.get("aliases_ko", [])
                    if not isinstance(raw_aliases, list):
                        raise FixtureSchemaError("interaction aliases must be a list")
                    for alias in raw_aliases:
                        alias = _text(alias, "interaction alias")
                        normalized = " ".join(unicodedata.normalize("NFC", alias).strip().split())
                        if (
                            len(normalized) > 24
                            or any(ord(char) < 32 or ord(char) == 127 for char in normalized)
                            or not re.search("[가-힣]", normalized)
                            or normalized in aliases
                        ):
                            raise FixtureSchemaError("interaction alias is invalid or ambiguous")
                        aliases.add(normalized)
                    has_next = "next_prompt_id" in response
                    has_terminal = "terminal" in response
                    if has_next == has_terminal:
                        raise FixtureSchemaError(
                            "response requires exactly one next prompt or terminal"
                        )
                    if has_next:
                        next_id = _text(response["next_prompt_id"], "interaction.next_prompt_id")
                        if next_id not in prompt_ids:
                            raise FixtureSchemaError("interaction edge references unknown prompt")
                        reachable.add(next_id)
                    else:
                        terminal = _object(response["terminal"], "interaction.terminal")
                        if set(terminal) != {"outcome_code", "gold_delta", "resource_delta"}:
                            raise FixtureSchemaError("interaction terminal keys must be exact")
                        outcome = _text(terminal["outcome_code"], "interaction.outcome_code")
                        if outcome in outcomes:
                            raise FixtureSchemaError("interaction outcomes must be unique")
                        outcomes.add(outcome)
                        _integer(terminal["gold_delta"], "interaction.gold_delta")
                        _integer(terminal["resource_delta"], "interaction.resource_delta")
            if reachable != prompt_ids or not outcomes:
                raise FixtureSchemaError("interaction graph must be reachable and terminal")


def validate_world_fixture(
    world: object,
    *,
    expected_kinds_for: Callable[[str], tuple[str, ...]] | None = None,
    expected_facility_services: Mapping[str, tuple[str, ...]] | None = None,
) -> WorldFixture:
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

    facilities = _validate_facilities(
        towns[0],
        expected_kinds_for=expected_kinds_for,
        expected_facility_services=expected_facility_services,
    )
    floors = _validate_dungeon(dungeons[0], expected_kinds_for=expected_kinds_for)
    _validate_actions(towns[0], "town", expected_kinds_for=expected_kinds_for)
    for ground in grounds:
        ground_id = _text(ground.get("id"), "hunting ground.id")
        _text(ground.get("description"), f"hunting ground {ground_id}.description")
        _validate_actions(ground, "hunting ground", expected_kinds_for=expected_kinds_for)
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

    _validate_interactions(facilities, npcs)
    return cast(WorldFixture, root)


def load_world_fixture(
    path: str | Path,
    *,
    expected_kinds_for: Callable[[str], tuple[str, ...]] | None = None,
    expected_facility_services: Mapping[str, tuple[str, ...]] | None = None,
) -> LoadedWorldFixture:
    try:
        with Path(path).open(encoding="utf-8") as stream:
            raw: object = json.load(stream)
    except json.JSONDecodeError as error:
        raise FixtureSchemaError(f"invalid JSON fixture: {error.msg}") from error
    world = validate_world_fixture(
        raw,
        expected_kinds_for=expected_kinds_for,
        expected_facility_services=expected_facility_services,
    )
    result = cast(LoadedWorldFixture, dict(world))
    result["location_ids"] = tuple(
        [item["id"] for item in world["towns"]]
        + [facility["id"] for item in world["towns"] for facility in item["facilities"]]
        + [item["id"] for item in world["hunting_grounds"]]
        + [floor["id"] for dungeon in world["dungeons"] for floor in dungeon["floors"]]
    )
    return result


_RULES_V2_ACTION_KINDS: Mapping[str, tuple[str, ...]] = {
    "emberfall": ("observe",),
    "emberfall-shop": ("buy_supplies", "sell_salvage"),
    "emberfall-inn": ("lodge", "store_belongings"),
    "emberfall-quest-hall": ("list_contracts", "turn_in_contract"),
    "emberfall-plaza": ("read_notices", "request_directions"),
    "emberfall-tavern": ("buy_meal", "hear_rumor"),
    "mossreach": ("hunt", "gather", "scout", "camp"),
    **{f"vault-{depth}": ("scout", "search", "fight") for depth in range(1, 10)},
    "vault-10": ("scout", "search", "challenge"),
}

_RULES_V2_FACILITY_SERVICES: Mapping[str, tuple[str, ...]] = {
    "emberfall-shop": ("buy_supplies", "sell_salvage"),
    "emberfall-inn": ("rest", "store_belongings"),
    "emberfall-quest-hall": ("list_contracts", "turn_in_contract"),
    "emberfall-plaza": ("read_notices", "request_directions"),
    "emberfall-tavern": ("buy_meal", "hear_rumor"),
}


def _rules_v2_expected_action_kinds(location_id: str) -> tuple[str, ...]:
    return _RULES_V2_ACTION_KINDS[location_id]


_RULES_V3_ACTION_KINDS: Mapping[str, tuple[str, ...]] = {
    "emberfall": ("observe",),
    "emberfall-shop": ("browse_goods", "buy_supplies", "sell_salvage", "talk_orrin"),
    "emberfall-inn": ("eat_inn_meal", "lodge", "store_belongings", "talk_brann"),
    "emberfall-quest-hall": ("list_contracts", "turn_in_contract", "ask_vela_advice"),
    "emberfall-plaza": ("read_notices", "request_directions", "talk_pell"),
    "emberfall-tavern": (
        "view_tavern_menu",
        "order_drink",
        "buy_meal",
        "hear_rumor",
        "talk_sena",
    ),
    "mossreach": ("hunt", "gather", "scout", "camp"),
    **{f"vault-{depth}": ("scout", "search", "fight") for depth in range(1, 10)},
    "vault-10": ("scout", "search", "challenge"),
}

_RULES_V3_FACILITY_SERVICES: Mapping[str, tuple[str, ...]] = {
    "emberfall-shop": ("browse_goods", "buy_supplies", "sell_salvage", "talk_orrin"),
    "emberfall-inn": ("eat_inn_meal", "rest", "store_belongings", "talk_brann"),
    "emberfall-quest-hall": ("list_contracts", "turn_in_contract", "ask_vela_advice"),
    "emberfall-plaza": ("read_notices", "request_directions", "talk_pell"),
    "emberfall-tavern": (
        "view_tavern_menu",
        "order_drink",
        "buy_meal",
        "hear_rumor",
        "talk_sena",
    ),
}


def _rules_v3_expected_action_kinds(location_id: str) -> tuple[str, ...]:
    return _RULES_V3_ACTION_KINDS[location_id]


_PACKAGED_WORLD_RESOURCES: Mapping[str, str] = {
    "current": "glassfrontier_world.json",
    "rules-v2": "glassfrontier_world_rules_v2.json",
    "rules-v3": "glassfrontier_world_rules_v3.json",
    "rules-v4": "glassfrontier_world_rules_v4.json",
}


def load_packaged_world_fixture(*, revision: str = "current") -> LoadedWorldFixture:
    """Load one validated, trusted world revision from package resources."""

    try:
        resource_name = _PACKAGED_WORLD_RESOURCES[revision]
    except KeyError as error:
        raise ValueError(f"unsupported content revision: {revision!r}") from error
    resource = files("aincrad.content").joinpath("data", resource_name)
    with as_file(resource) as path:
        return load_world_fixture(
            path,
            expected_kinds_for=(
                _rules_v2_expected_action_kinds
                if revision == "rules-v2"
                else _rules_v3_expected_action_kinds
                if revision in {"rules-v3", "rules-v4"}
                else None
            ),
            expected_facility_services=(
                _RULES_V2_FACILITY_SERVICES
                if revision == "rules-v2"
                else _RULES_V3_FACILITY_SERVICES
                if revision in {"rules-v3", "rules-v4"}
                else None
            ),
        )
