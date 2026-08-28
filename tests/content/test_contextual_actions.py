from __future__ import annotations

from aincrad.content import (
    action_catalog_from_fixture,
    available_action_intents,
    contextual_action_for_intent,
    load_packaged_world_fixture,
)
from aincrad.domain import ActionKind
from aincrad.simulation.scenario import create_initial_world


def test_fixture_catalog_covers_every_glass_frontier_location_with_canonical_actions() -> None:
    fixture = load_packaged_world_fixture()

    catalog = action_catalog_from_fixture(fixture)

    assert set(catalog) == set(fixture["location_ids"])
    assert all(
        action.label_ko and action.description_ko
        for actions in catalog.values()
        for action in actions
    )
    assert [action.kind for action in catalog["emberfall"]] == [ActionKind.OBSERVE]
    assert [action.kind for action in catalog["emberfall-shop"]] == [
        ActionKind.BUY_SUPPLIES,
        ActionKind.SELL_SALVAGE,
    ]
    assert [action.kind for action in catalog["emberfall-quest-hall"]] == [
        ActionKind.LIST_CONTRACTS,
        ActionKind.TURN_IN_CONTRACT,
    ]
    assert [action.kind for action in catalog["mossreach"]] == [
        ActionKind.HUNT,
        ActionKind.GATHER,
        ActionKind.SCOUT,
        ActionKind.CAMP,
    ]
    for depth in range(1, 10):
        assert [action.kind for action in catalog[f"vault-{depth}"]] == [
            ActionKind.SCOUT,
            ActionKind.SEARCH,
            ActionKind.FIGHT,
        ]
    assert [action.kind for action in catalog["vault-10"]] == [
        ActionKind.SCOUT,
        ActionKind.SEARCH,
        ActionKind.CHALLENGE,
    ]


def test_available_actions_expose_connected_moves_but_hide_unrepresentable_turn_ins() -> None:
    world = create_initial_world()
    actor_id = "rhea-vale"

    town_intents = available_action_intents(world, actor_id)
    assert {(intent.action, intent.target_location_id) for intent in town_intents} == {
        (ActionKind.MOVE, "emberfall-shop"),
        (ActionKind.MOVE, "emberfall-inn"),
        (ActionKind.MOVE, "emberfall-quest-hall"),
        (ActionKind.MOVE, "emberfall-plaza"),
        (ActionKind.MOVE, "emberfall-tavern"),
        (ActionKind.MOVE, "mossreach"),
        (ActionKind.OBSERVE, None),
    }

    quest_hall = world.adventurers[actor_id]
    world = world.__class__(
        tick=world.tick,
        locations=world.locations,
        adventurers={actor_id: quest_hall.__class__(
            id=quest_hall.id,
            name=quest_hall.name,
            location_id="emberfall-quest-hall",
            stats=quest_hall.stats,
            activity=quest_hall.activity,
            gold=quest_hall.gold,
            resources=quest_hall.resources,
            character_class=quest_hall.character_class,
            level=quest_hall.level,
            exp=quest_hall.exp,
            alive=quest_hall.alive,
            death_tick=quest_hall.death_tick,
            death_cause=quest_hall.death_cause,
        )},
    )

    assert [intent.action for intent in available_action_intents(world, actor_id)] == [
        ActionKind.MOVE,
        ActionKind.LIST_CONTRACTS,
    ]


def test_contextual_action_lookup_resolves_location_specific_display_metadata() -> None:
    world = create_initial_world()
    intent = available_action_intents(world, "rhea-vale")[-1]

    action = contextual_action_for_intent(world, intent)

    assert action is not None
    assert action.id == "emberfall-observe-warm-spring"
    assert action.label_ko
    assert action.description_ko
