from __future__ import annotations

import json
from pathlib import Path

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


def test_original_world_fixture_has_required_places_and_three_adventurers() -> None:
    world = load_world_fixture(FIXTURE)

    assert world["schema_version"] == 1
    assert len(world["towns"]) == 1
    assert len(world["hunting_grounds"]) == 1
    assert [floor["depth"] for floor in world["dungeons"][0]["floors"]] == [1, 2, 3]
    assert len(world["adventurers"]) == 3
    assert len({item["id"] for item in world["adventurers"]}) == 3
    assert all(item["location_id"] in world["location_ids"] for item in world["adventurers"])


def test_general_npcs_are_declared_as_rule_based_services() -> None:
    world = load_world_fixture(FIXTURE)

    assert world["npcs"]
    assert {npc["controller"] for npc in world["npcs"]} == {"rules"}
    assert {npc["service"] for npc in world["npcs"]} == {"shop", "healer", "inn"}


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
