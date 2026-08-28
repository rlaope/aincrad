from __future__ import annotations

from dataclasses import replace
from typing import cast

import pytest

from aincrad.content import available_action_intents
from aincrad.domain import (
    ActionIntent,
    ActionKind,
    ActionRejected,
    ActionSucceeded,
    Adventurer,
    EdgeKind,
    Location,
    LocationKind,
    Stats,
    TravelEdge,
    WorldState,
)
from aincrad.domain.rules import apply_intent
from aincrad.simulation import SimulationScheduler, create_initial_world


def _adventurer(location_id: str = "town") -> Adventurer:
    return Adventurer(
        id="mira",
        name="미라",
        location_id=location_id,
        stats=Stats(hp=8, max_hp=10, mp=3, max_mp=5),
    )


def _location(
    location_id: str,
    *,
    kind: LocationKind = LocationKind.HUNTING_GROUND,
    edges: tuple[TravelEdge, ...] = (),
) -> Location:
    return Location(
        id=location_id,
        name=location_id,
        kind=kind,
        region="test-region",
        terrain="test-terrain",
        edges=edges,
    )


def test_travel_edge_requires_exact_enum_safe_target_and_korean_path() -> None:
    edge = TravelEdge("field", EdgeKind.OVERLAND, "비 젖은 둑길")

    assert edge.to == "field"
    assert edge.kind is EdgeKind.OVERLAND
    with pytest.raises(ValueError, match="EdgeKind"):
        TravelEdge("field", "overland", "비 젖은 둑길")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="safe"):
        TravelEdge("bad target", EdgeKind.OVERLAND, "비 젖은 둑길")
    with pytest.raises(ValueError, match="Korean"):
        TravelEdge("field", EdgeKind.OVERLAND, "wet road")


def test_location_edges_are_serialized_and_connections_are_read_only_derived() -> None:
    town = _location("town", edges=(TravelEdge("field", EdgeKind.OVERLAND, "남쪽 길"),))

    assert town.connections == ("field",)
    with pytest.raises((AttributeError, TypeError)):
        town.connections = ("elsewhere",)  # type: ignore[misc]


def test_world_rejects_unknown_self_duplicate_asymmetric_and_kind_mismatched_edges() -> None:
    def make_world(
        town_edges: tuple[TravelEdge, ...], field_edges: tuple[TravelEdge, ...]
    ) -> WorldState:
        return WorldState(
            tick=0,
            locations={
                "town": _location("town", kind=LocationKind.TOWN, edges=town_edges),
                "field": _location("field", edges=field_edges),
            },
            adventurers={"mira": _adventurer()},
        )

    with pytest.raises(ValueError, match="unknown edge target"):
        make_world((TravelEdge("missing", EdgeKind.OVERLAND, "북쪽 길"),), ())
    with pytest.raises(ValueError, match="self"):
        make_world((TravelEdge("town", EdgeKind.OVERLAND, "광장 길"),), ())
    with pytest.raises(ValueError, match="duplicate"):
        make_world(
            (
                TravelEdge("field", EdgeKind.OVERLAND, "동쪽 길"),
                TravelEdge("field", EdgeKind.OVERLAND, "다른 동쪽 길"),
            ),
            (TravelEdge("town", EdgeKind.OVERLAND, "서쪽 길"),),
        )
    with pytest.raises(ValueError, match="asymmetric"):
        make_world((TravelEdge("field", EdgeKind.OVERLAND, "동쪽 길"),), ())
    with pytest.raises(ValueError, match="kind mismatch"):
        make_world(
            (TravelEdge("field", EdgeKind.OVERLAND, "동쪽 길"),),
            (TravelEdge("town", EdgeKind.DUNGEON, "서쪽 길"),),
        )


def test_current_move_accepts_one_adjacent_travel_edge_and_rejects_scene_or_remote_targets(
) -> None:
    world = create_initial_world()

    moved, events = apply_intent(
        world, ActionIntent("rhea-vale", ActionKind.MOVE, target_location_id="mossreach-terraces")
    )
    assert moved.adventurers["rhea-vale"].location_id == "mossreach-terraces"
    assert dict(cast(ActionSucceeded, events[0]).details)["edge_kind"] == "overland"

    remote, remote_events = apply_intent(
        world, ActionIntent("rhea-vale", ActionKind.MOVE, target_location_id="mossreach")
    )
    scene, scene_events = apply_intent(
        world, ActionIntent("rhea-vale", ActionKind.MOVE, target_location_id="emberfall-shop")
    )

    assert remote is world
    assert cast(ActionRejected, remote_events[0]).reason == "location_not_connected"
    assert scene is world
    assert cast(ActionRejected, scene_events[0]).reason == "scene_edge_not_travel"


def test_facility_leaf_returns_to_hub_by_scene_edge_but_hub_cannot_move_into_a_facility() -> None:
    world = create_initial_world()
    actor = world.adventurers["rhea-vale"]
    at_shop = WorldState(
        tick=world.tick,
        locations=world.locations,
        adventurers={actor.id: replace(actor, location_id="emberfall-shop")},
    )

    candidates = available_action_intents(at_shop, actor.id)
    assert ActionIntent(actor.id, ActionKind.MOVE, target_location_id="emberfall") in candidates
    returned, return_events = apply_intent(
        at_shop, ActionIntent(actor.id, ActionKind.MOVE, target_location_id="emberfall")
    )
    assert returned.adventurers[actor.id].location_id == "emberfall"
    assert dict(cast(ActionSucceeded, return_events[0]).details)["edge_kind"] == "scene"

    hub_candidates = available_action_intents(world, actor.id)
    assert (
        ActionIntent(actor.id, ActionKind.MOVE, target_location_id="emberfall-shop")
        not in hub_candidates
    )
    unchanged, rejected = apply_intent(
        world, ActionIntent(actor.id, ActionKind.MOVE, target_location_id="emberfall-shop")
    )
    assert unchanged is world
    assert cast(ActionRejected, rejected[0]).reason == "scene_edge_not_travel"


def test_four_one_edge_moves_reach_vault_one_only_after_four_ticks() -> None:
    world = create_initial_world()
    route = (
        ActionIntent("rhea-vale", ActionKind.MOVE, target_location_id="mossreach-terraces"),
        ActionIntent("rhea-vale", ActionKind.MOVE, target_location_id="mossreach"),
        ActionIntent("rhea-vale", ActionKind.MOVE, target_location_id="mossreach-vaultgate"),
        ActionIntent("rhea-vale", ActionKind.MOVE, target_location_id="vault-1"),
    )

    result = SimulationScheduler(seed=7).run(world, route)

    assert result.final_state.tick == 4
    assert result.final_state.adventurers["rhea-vale"].location_id == "vault-1"
    assert all(isinstance(event, ActionSucceeded) for event in result.events)
    assert [dict(cast(ActionSucceeded, event).details)["edge_kind"] for event in result.events] == [
        "overland",
        "overland",
        "overland",
        "dungeon_gate",
    ]
