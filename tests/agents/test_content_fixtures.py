from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

from aincrad.content import (
    FixtureSchemaError,
    RuleBasedNPCService,
    ServiceRequest,
    load_world_fixture,
    validate_world_fixture,
)

ROOT = Path(__file__).parents[2]
FIXTURE = ROOT / "fixtures" / "glassfrontier_world.json"


def test_original_world_fixture_has_three_candidate_adventurers() -> None:
    world = load_world_fixture(FIXTURE)

    assert world["schema_version"] == 1
    assert len(world["towns"]) == 1
    assert len(world["hunting_grounds"]) == 1
    assert len(world["adventurers"]) == 3
    assert len({item["id"] for item in world["adventurers"]}) == 3
    assert all(item["location_id"] in world["location_ids"] for item in world["adventurers"])


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("world_id", "other-world", "world_id"),
        ("title", "Other World", "title"),
    ],
)
def test_fixture_validator_enforces_canonical_world_identity(
    field: str, value: str, message: str
) -> None:
    world = json.loads(FIXTURE.read_text(encoding="utf-8"))
    world[field] = value

    with pytest.raises(FixtureSchemaError, match=message):
        validate_world_fixture(world)


def test_emberfall_has_five_explicit_service_facilities() -> None:
    world = load_world_fixture(FIXTURE)
    emberfall = world["towns"][0]

    assert [facility["id"] for facility in emberfall["facilities"]] == [
        "emberfall-shop",
        "emberfall-inn",
        "emberfall-quest-hall",
        "emberfall-plaza",
        "emberfall-tavern",
    ]
    assert {facility["kind"] for facility in emberfall["facilities"]} == {
        "shop",
        "inn",
        "quest_hall",
        "plaza",
        "tavern",
    }
    assert all(facility["description"] for facility in emberfall["facilities"])
    assert all(facility["services"] for facility in emberfall["facilities"])


def test_starless_vault_is_connected_through_boss_and_world_transition() -> None:
    world = load_world_fixture(FIXTURE)
    floors = world["dungeons"][0]["floors"]

    assert [floor["depth"] for floor in floors] == list(range(1, 11))
    assert floors[-1]["kind"] == "boss_room"
    assert floors[-1]["completion"]["next_world_floor"] == 2
    assert floors[-1]["completion"]["transition_id"] == "aurora-lift-floor-2"
    assert floors[-1]["completion"]["rewards"]
    for current, following in zip(floors, floors[1:], strict=False):
        assert following["id"] in current["connections"]
        assert current["id"] in following["connections"]


def test_general_npcs_are_declared_as_rule_based_facility_services() -> None:
    world = load_world_fixture(FIXTURE)

    assert world["npcs"]
    assert {npc["controller"] for npc in world["npcs"]} == {"rules"}
    assert {npc["service"] for npc in world["npcs"]} == {
        "shop",
        "inn",
        "quest_hall",
        "plaza",
        "tavern",
    }
    assert all(npc["rules"] for npc in world["npcs"])
    assert all(
        cast(str, npc["location_id"]).startswith("emberfall-") for npc in world["npcs"]
    )


def test_rule_based_shop_is_deterministic_and_rejects_unknown_operations() -> None:
    service = RuleBasedNPCService(
        npc_id="npc-orrin",
        service="shop",
        rules={"buy:field-ration": {"gold_delta": -3, "items": ["field-ration"]}},
    )
    request = ServiceRequest("rhea", "buy", item_id="field-ration")

    assert service.handle(request) == service.handle(request)
    assert service.handle(request).effects == (("gold_delta", -3), ("items", ("field-ration",)))
    with pytest.raises(LookupError):
        service.handle(ServiceRequest("rhea", "sell", item_id="dragon-heart"))


def test_fixture_validator_rejects_broken_location_reference() -> None:
    world = json.loads(FIXTURE.read_text(encoding="utf-8"))
    world["adventurers"][0]["location_id"] = "nowhere"

    with pytest.raises(FixtureSchemaError, match="location"):
        validate_world_fixture(world)


def test_fixture_validator_requires_one_npc_for_each_facility() -> None:
    world = json.loads(FIXTURE.read_text(encoding="utf-8"))
    world["npcs"][-1]["location_id"] = "emberfall-shop"
    world["npcs"][-1]["service"] = "shop"

    with pytest.raises(FixtureSchemaError, match="one rule-based NPC"):
        validate_world_fixture(world)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda world: world["dungeons"][0]["floors"][3].update(depth=8), "depths"),
        (
            lambda world: world["dungeons"][0]["floors"][4]["connections"].append("missing-room"),
            "unknown connection",
        ),
        (
            lambda world: world["dungeons"][0]["floors"][-1]["completion"].update(
                next_world_floor="two"
            ),
            "next_world_floor",
        ),
    ],
)
def test_fixture_validator_reports_invalid_dungeon_content(
    mutate: Callable[[dict[str, Any]], None], message: str
) -> None:
    world = json.loads(FIXTURE.read_text(encoding="utf-8"))
    mutate(world)

    with pytest.raises(FixtureSchemaError, match=message):
        validate_world_fixture(world)
