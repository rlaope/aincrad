from __future__ import annotations

import pytest

from aincrad.content import (
    action_catalog_from_fixture,
    available_action_intents,
    contextual_action_for_intent,
    load_packaged_world_fixture,
)
from aincrad.domain import ActionIntent, ActionKind
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
        ActionKind.BROWSE_GOODS,
        ActionKind.BUY_SUPPLIES,
        ActionKind.SELL_SALVAGE,
        ActionKind.TALK_ORRIN,
    ]
    assert [action.kind for action in catalog["emberfall-quest-hall"]] == [
        ActionKind.LIST_CONTRACTS,
        ActionKind.TURN_IN_CONTRACT,
        ActionKind.ASK_VELA_ADVICE,
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
        adventurers={
            actor_id: quest_hall.__class__(
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
            )
        },
    )

    assert [intent.action for intent in available_action_intents(world, actor_id)] == [
        ActionKind.MOVE,
        ActionKind.LIST_CONTRACTS,
        ActionKind.TURN_IN_CONTRACT,
        ActionKind.ASK_VELA_ADVICE,
    ]


def test_contextual_action_lookup_resolves_location_specific_display_metadata() -> None:
    world = create_initial_world()
    intent = available_action_intents(world, "rhea-vale")[-1]

    action = contextual_action_for_intent(world, intent)

    assert action is not None
    assert action.id == "emberfall-observe-warm-spring"
    assert action.label_ko
    assert action.description_ko


@pytest.mark.parametrize(
    ("location_id", "kind", "action_id"),
    (
        ("emberfall-shop", ActionKind.TALK_ORRIN, "emberfall-shop-talk-orrin"),
        ("emberfall-inn", ActionKind.TALK_BRANN, "emberfall-inn-talk-brann"),
        (
            "emberfall-quest-hall",
            ActionKind.ASK_VELA_ADVICE,
            "emberfall-quest-hall-ask-vela-advice",
        ),
        ("emberfall-plaza", ActionKind.TALK_PELL, "emberfall-plaza-talk-pell"),
        ("emberfall-tavern", ActionKind.TALK_SENA, "emberfall-tavern-talk-sena"),
    ),
)
def test_each_emberfall_resident_has_one_replayable_conversation_action(
    location_id: str, kind: ActionKind, action_id: str
) -> None:
    world = create_initial_world()
    actor = world.adventurers["rhea-vale"]
    at_facility = world.__class__(
        tick=world.tick,
        locations=world.locations,
        adventurers={
            actor.id: actor.__class__(
                id=actor.id,
                name=actor.name,
                location_id=location_id,
                stats=actor.stats,
                activity=actor.activity,
                gold=actor.gold,
                resources=actor.resources,
                character_class=actor.character_class,
                level=actor.level,
                exp=actor.exp,
                alive=actor.alive,
                death_tick=actor.death_tick,
                death_cause=actor.death_cause,
            )
        },
    )

    available = available_action_intents(at_facility, actor.id)
    resolved = contextual_action_for_intent(at_facility, ActionIntent(actor.id, kind))

    assert ActionIntent(actor.id, kind) in available
    assert resolved is not None
    assert resolved.id == action_id
    assert resolved.outcome_code is not None


@pytest.mark.parametrize(
    ("location_id", "kind", "action_id", "label_ko"),
    (
        (
            "emberfall-shop",
            ActionKind.BROWSE_GOODS,
            "emberfall-shop-browse-goods",
            "상품 목록 보기",
        ),
        (
            "emberfall-tavern",
            ActionKind.VIEW_TAVERN_MENU,
            "emberfall-tavern-view-menu",
            "메뉴 보기",
        ),
    ),
)
def test_read_only_facility_catalog_actions_have_concrete_menu_labels(
    location_id: str, kind: ActionKind, action_id: str, label_ko: str
) -> None:
    fixture = load_packaged_world_fixture()
    catalog = action_catalog_from_fixture(fixture)

    action = next(item for item in catalog[location_id] if item.kind is kind)

    assert action.id == action_id
    assert action.label_ko == label_ko
    assert action.outcome_code is not None
    assert action.gold_delta == action.resource_delta == action.restore_hp == action.restore_mp == 0
