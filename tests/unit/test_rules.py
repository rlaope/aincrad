from dataclasses import is_dataclass, replace
from typing import cast

import pytest

from aincrad.domain import (
    ActionIntent,
    ActionKind,
    ActionRejected,
    ActionSucceeded,
    Activity,
    Adventurer,
    DomainEvent,
    Location,
    LocationKind,
    Stats,
    WorldState,
)
from aincrad.domain.rules import apply_intent
from aincrad.simulation.scenario import create_initial_world


def test_domain_event_is_an_explicit_dataclass_base_type() -> None:
    assert is_dataclass(DomainEvent)


def test_dead_adventurer_actions_are_rejected_without_state_change() -> None:
    world = make_world()
    dead = replace(
        world.adventurers["mira"],
        stats=Stats(hp=0, max_hp=10, mp=3, max_mp=5),
        alive=False,
        death_tick=0,
        death_cause="fallen_in_battle",
    )
    world = replace(world, adventurers={"mira": dead})

    next_world, events = apply_intent(world, ActionIntent("mira", ActionKind.WAIT))

    assert next_world is world
    assert isinstance(events[0], ActionRejected)
    assert events[0].reason == "adventurer_dead"


def make_world() -> WorldState:
    return WorldState(
        tick=0,
        locations={
            "town": Location("town", "Town", LocationKind.TOWN, ("field",)),
            "field": Location("field", "Field", LocationKind.HUNTING_GROUND, ("town",)),
        },
        adventurers={
            "mira": Adventurer(
                id="mira",
                name="미라",
                location_id="town",
                stats=Stats(hp=8, max_hp=10, mp=3, max_mp=5),
                activity=Activity.IDLE,
                gold=5,
                resources=0,
            )
        },
    )


def test_move_changes_location_and_emits_success_event() -> None:
    world = make_world()

    next_world, events = apply_intent(
        world, ActionIntent("mira", ActionKind.MOVE, target_location_id="field")
    )

    assert next_world.adventurers["mira"].location_id == "field"
    assert next_world.adventurers["mira"].activity is Activity.MOVING
    assert events == (
        ActionSucceeded(
            tick=0,
            adventurer_id="mira",
            action=ActionKind.MOVE,
            next_tick=1,
            target_location_id="field",
            quantity=1,
            details=(("destination", "field"),),
        ),
    )
    assert world.adventurers["mira"].location_id == "town"


def test_move_to_unknown_location_is_rejected_without_state_change() -> None:
    world = make_world()

    next_world, events = apply_intent(
        world, ActionIntent("mira", ActionKind.MOVE, target_location_id="missing")
    )

    assert next_world is world
    assert events == (
        ActionRejected(
            tick=0,
            adventurer_id="mira",
            action=ActionKind.MOVE,
            next_tick=1,
            target_location_id="missing",
            quantity=1,
            reason="unknown_location",
        ),
    )


def test_rest_gather_trade_and_wait_form_a_life_action_slice() -> None:
    world = make_world()

    rested, _ = apply_intent(world, ActionIntent("mira", ActionKind.REST))
    assert rested.adventurers["mira"].stats == Stats(hp=10, max_hp=10, mp=5, max_mp=5)
    assert rested.adventurers["mira"].activity is Activity.RESTING

    at_field, _ = apply_intent(
        rested, ActionIntent("mira", ActionKind.MOVE, target_location_id="field")
    )
    gathered, _ = apply_intent(at_field, ActionIntent("mira", ActionKind.GATHER), gather_yield=2)
    assert gathered.adventurers["mira"].resources == 2
    assert gathered.adventurers["mira"].activity is Activity.GATHERING

    at_town, _ = apply_intent(
        gathered, ActionIntent("mira", ActionKind.MOVE, target_location_id="town")
    )
    traded, _ = apply_intent(at_town, ActionIntent("mira", ActionKind.TRADE, quantity=2))
    assert traded.adventurers["mira"].resources == 0
    assert traded.adventurers["mira"].gold == 9
    assert traded.adventurers["mira"].activity is Activity.TRADING

    waited, _ = apply_intent(traded, ActionIntent("mira", ActionKind.WAIT))
    assert waited.adventurers["mira"].activity is Activity.WAITING


def test_insufficient_trade_and_invalid_action_are_atomic_rejections() -> None:
    world = make_world()
    insufficient, insufficient_events = apply_intent(
        world, ActionIntent("mira", ActionKind.TRADE, quantity=1)
    )
    invalid_intent = ActionIntent("mira", cast(ActionKind, "dance"))
    invalid, invalid_events = apply_intent(world, invalid_intent)

    assert insufficient is world
    assert insufficient_events[0] == ActionRejected(
        tick=0,
        adventurer_id="mira",
        action=ActionKind.TRADE,
        next_tick=1,
        target_location_id=None,
        quantity=1,
        reason="insufficient_resources",
    )
    assert invalid is world
    assert invalid_events[0] == ActionRejected(
        tick=0,
        adventurer_id="mira",
        action=cast(ActionKind, "dance"),
        next_tick=1,
        target_location_id=None,
        quantity=1,
        reason="invalid_action",
    )


@pytest.mark.parametrize(
    "stats",
    (
        (-1, 10, 0, 5),
        (11, 10, 0, 5),
        (0, 10, -1, 5),
        (0, 10, 6, 5),
    ),
)
def test_stats_reject_values_outside_closed_bounds(stats: tuple[int, int, int, int]) -> None:
    with pytest.raises(ValueError):
        Stats(*stats)


def test_wealth_rejects_negative_values() -> None:
    adventurer = make_world().adventurers["mira"]
    with pytest.raises(ValueError):
        replace(adventurer, gold=-1)


def test_contextual_actions_emit_grounded_codes_and_only_mutate_supported_state() -> None:
    world = create_initial_world()

    observed, observed_events = apply_intent(world, ActionIntent("rhea-vale", ActionKind.OBSERVE))
    observed_event = cast(ActionSucceeded, observed_events[0])
    assert observed.adventurers["rhea-vale"].activity is Activity.OBSERVING
    assert dict(observed_event.details) == {
        "location_id": "emberfall",
        "action_id": "emberfall-observe-warm-spring",
        "action_key": "observe",
        "clue_code": "warm-shard-spring",
        "outcome_code": "spring-observation-recorded",
    }

    shopper = replace(world.adventurers["rhea-vale"], location_id="emberfall-shop")
    at_shop = replace(world, adventurers={**world.adventurers, shopper.id: shopper})
    purchased, purchase_events = apply_intent(
        at_shop, ActionIntent("rhea-vale", ActionKind.BUY_SUPPLIES)
    )
    purchase_event = cast(ActionSucceeded, purchase_events[0])
    assert purchased.adventurers["rhea-vale"].gold == shopper.gold - 3
    assert purchased.adventurers["rhea-vale"].resources == shopper.resources
    assert dict(purchase_event.details)["outcome_code"] == "supply-purchase-recorded"
    assert "items" not in dict(purchase_event.details)


@pytest.mark.parametrize(
    ("location_id", "action", "action_id", "outcome_code"),
    (
        (
            "emberfall-shop",
            ActionKind.TALK_ORRIN,
            "emberfall-shop-talk-orrin",
            "orrin-counsel-recorded",
        ),
        (
            "emberfall-inn",
            ActionKind.TALK_BRANN,
            "emberfall-inn-talk-brann",
            "brann-counsel-recorded",
        ),
        (
            "emberfall-quest-hall",
            ActionKind.ASK_VELA_ADVICE,
            "emberfall-quest-hall-ask-vela-advice",
            "vela-advice-recorded",
        ),
        (
            "emberfall-plaza",
            ActionKind.TALK_PELL,
            "emberfall-plaza-talk-pell",
            "pell-directions-recorded",
        ),
        (
            "emberfall-tavern",
            ActionKind.TALK_SENA,
            "emberfall-tavern-talk-sena",
            "sena-rumor-recorded",
        ),
    ),
)
def test_facility_conversations_emit_grounded_events_without_economy_mutation(
    location_id: str, action: ActionKind, action_id: str, outcome_code: str
) -> None:
    world = create_initial_world()
    actor = replace(world.adventurers["rhea-vale"], location_id=location_id)
    world = replace(world, adventurers={**world.adventurers, actor.id: actor})

    next_world, events = apply_intent(world, ActionIntent(actor.id, action))

    event = cast(ActionSucceeded, events[0])
    assert next_world.adventurers[actor.id].gold == actor.gold
    assert next_world.adventurers[actor.id].resources == actor.resources
    assert dict(event.details) == {
        "location_id": location_id,
        "action_id": action_id,
        "action_key": action.value,
        "outcome_code": outcome_code,
    }


def test_unrepresentable_contract_turn_in_is_rejected_without_faking_quest_state() -> None:
    world = create_initial_world()
    quest_member = replace(world.adventurers["rhea-vale"], location_id="emberfall-quest-hall")
    world = replace(world, adventurers={**world.adventurers, quest_member.id: quest_member})

    next_world, events = apply_intent(world, ActionIntent("rhea-vale", ActionKind.TURN_IN_CONTRACT))

    assert next_world is world
    assert isinstance(events[0], ActionRejected)
    assert events[0].reason == "completed_contract_not_representable"


@pytest.mark.parametrize(
    ("location_id", "action", "action_id", "outcome_code", "restore_hp", "restore_mp"),
    (
        (
            "emberfall-inn",
            ActionKind.EAT_INN_MEAL,
            "emberfall-inn-eat-meal",
            "inn-meal-served",
            3,
            1,
        ),
        (
            "emberfall-tavern",
            ActionKind.ORDER_DRINK,
            "emberfall-tavern-order-drink",
            "tavern-drink-served",
            0,
            2,
        ),
    ),
)
def test_paid_facility_services_charge_once_restore_stats_and_record_grounded_effects(
    location_id: str,
    action: ActionKind,
    action_id: str,
    outcome_code: str,
    restore_hp: int,
    restore_mp: int,
) -> None:
    world = create_initial_world()
    actor = replace(
        world.adventurers["rhea-vale"],
        location_id=location_id,
        gold=1,
        stats=Stats(hp=10, max_hp=24, mp=0, max_mp=8),
    )
    world = replace(world, adventurers={**world.adventurers, actor.id: actor})

    next_world, events = apply_intent(world, ActionIntent(actor.id, action))

    served = next_world.adventurers[actor.id]
    event = cast(ActionSucceeded, events[0])
    assert served.gold == 0
    assert served.stats == Stats(
        hp=actor.stats.hp + restore_hp,
        max_hp=actor.stats.max_hp,
        mp=actor.stats.mp + restore_mp,
        max_mp=actor.stats.max_mp,
    )
    assert dict(event.details) == {
        "location_id": location_id,
        "action_id": action_id,
        "action_key": action.value,
        "outcome_code": outcome_code,
        "gold_delta": "-1",
        **({"hp_restored": str(restore_hp)} if restore_hp else {}),
        **({"mp_restored": str(restore_mp)} if restore_mp else {}),
    }


@pytest.mark.parametrize(
    ("location_id", "action"),
    (
        ("emberfall-inn", ActionKind.EAT_INN_MEAL),
        ("emberfall-tavern", ActionKind.ORDER_DRINK),
    ),
)
def test_paid_facility_services_reject_insufficient_gold_without_mutation(
    location_id: str, action: ActionKind
) -> None:
    world = create_initial_world()
    actor = replace(world.adventurers["rhea-vale"], location_id=location_id, gold=0)
    world = replace(world, adventurers={**world.adventurers, actor.id: actor})

    next_world, events = apply_intent(world, ActionIntent(actor.id, action))

    assert next_world is world
    assert isinstance(events[0], ActionRejected)
    assert events[0].reason == "insufficient_gold"


@pytest.mark.parametrize(
    ("location_id", "action"),
    (
        ("vault-1", ActionKind.REST),
        ("emberfall-inn", ActionKind.TRADE),
        ("emberfall-shop", ActionKind.WAIT),
        ("mossreach", ActionKind.REST),
    ),
)
def test_canonical_locations_reject_local_actions_outside_their_catalog(
    location_id: str,
    action: ActionKind,
) -> None:
    world = create_initial_world()
    actor = replace(
        world.adventurers["rhea-vale"],
        location_id=location_id,
        resources=1,
    )
    world = replace(world, adventurers={**world.adventurers, actor.id: actor})

    next_world, events = apply_intent(world, ActionIntent(actor.id, action))

    assert next_world is world
    assert isinstance(events[0], ActionRejected)
    assert events[0].reason == "action_not_available_at_location"


def test_contextual_action_rejects_non_unit_quantity_without_mutation() -> None:
    world = create_initial_world()
    actor = world.adventurers["rhea-vale"]

    next_world, events = apply_intent(
        world,
        ActionIntent(actor.id, ActionKind.OBSERVE, quantity=999),
    )

    assert next_world is world
    assert isinstance(events[0], ActionRejected)
    assert events[0].reason == "invalid_quantity"


@pytest.mark.parametrize("quantity", (True, 0, -1, 2))
def test_move_requires_exact_unit_integer_quantity(quantity: int) -> None:
    world = create_initial_world()
    actor = world.adventurers["rhea-vale"]

    next_world, events = apply_intent(
        world,
        ActionIntent(
            actor.id,
            ActionKind.MOVE,
            target_location_id="emberfall-inn",
            quantity=quantity,
        ),
    )

    assert next_world is world
    assert isinstance(events[0], ActionRejected)
    assert events[0].reason == "invalid_quantity"


def test_contextual_non_move_rejects_unexpected_target_without_mutation() -> None:
    world = create_initial_world()
    actor = world.adventurers["rhea-vale"]

    next_world, events = apply_intent(
        world,
        ActionIntent(
            actor.id,
            ActionKind.OBSERVE,
            target_location_id="emberfall-inn",
        ),
    )

    assert next_world is world
    assert isinstance(events[0], ActionRejected)
    assert events[0].reason == "unexpected_target_location"


def test_facility_entry_and_contextual_action_resolve_atomically_from_emberfall() -> None:
    world = create_initial_world()
    actor = world.adventurers["rhea-vale"]
    intent = ActionIntent(
        actor.id,
        ActionKind.BUY_SUPPLIES,
        target_location_id="emberfall-shop",
    )

    next_world, events = apply_intent(world, intent)

    event = cast(ActionSucceeded, events[0])
    entered = next_world.adventurers[actor.id]
    assert entered.location_id == "emberfall-shop"
    assert entered.gold == actor.gold - 3
    assert event.target_location_id == "emberfall-shop"
    assert dict(event.details)["location_id"] == "emberfall-shop"
    assert dict(event.details)["action_id"] == "emberfall-shop-buy-supplies"


@pytest.mark.parametrize(
    ("intent", "reason"),
    (
        (
            ActionIntent(
                "rhea-vale",
                ActionKind.EAT_INN_MEAL,
                target_location_id="emberfall-inn",
            ),
            "insufficient_gold",
        ),
        (
            ActionIntent(
                "rhea-vale",
                ActionKind.BUY_SUPPLIES,
                target_location_id="mossreach",
            ),
            "unexpected_target_location",
        ),
        (
            ActionIntent(
                "rhea-vale",
                ActionKind.OBSERVE,
                target_location_id="emberfall-shop",
            ),
            "unexpected_target_location",
        ),
        (
            ActionIntent(
                "rhea-vale",
                ActionKind.BUY_SUPPLIES,
                target_location_id="emberfall-shop",
                quantity=True,
            ),
            "invalid_quantity",
        ),
    ),
)
def test_invalid_facility_entry_contextual_intents_are_atomic(
    intent: ActionIntent, reason: str
) -> None:
    world = create_initial_world()
    if reason == "insufficient_gold":
        actor = replace(world.adventurers[intent.adventurer_id], gold=0)
        world = replace(world, adventurers={**world.adventurers, actor.id: actor})

    next_world, events = apply_intent(world, intent)

    assert next_world is world
    assert isinstance(events[0], ActionRejected)
    assert events[0].target_location_id == intent.target_location_id
    assert events[0].reason == reason


def test_hidden_facility_target_is_rejected_without_location_or_economy_mutation() -> None:
    world = create_initial_world()
    town = replace(
        world.locations["emberfall"],
        connections=tuple(
            location_id
            for location_id in world.locations["emberfall"].connections
            if location_id != "emberfall-shop"
        ),
    )
    world = replace(world, locations={**world.locations, town.id: town})
    actor = world.adventurers["rhea-vale"]

    next_world, events = apply_intent(
        world,
        ActionIntent(
            actor.id,
            ActionKind.BUY_SUPPLIES,
            target_location_id="emberfall-shop",
        ),
    )

    assert next_world is world
    assert isinstance(events[0], ActionRejected)
    assert events[0].reason == "unexpected_target_location"
    assert next_world.adventurers[actor.id].gold == actor.gold
    assert next_world.adventurers[actor.id].location_id == actor.location_id


def test_every_fixture_contextual_action_resolves_with_its_grounded_action_id() -> None:
    world = create_initial_world()
    base_actor = world.adventurers["rhea-vale"]

    for location in world.locations.values():
        for configured in location.contextual_actions:
            actor = replace(base_actor, location_id=location.id, resources=1)
            at_location = replace(world, adventurers={**world.adventurers, actor.id: actor})
            next_world, events = apply_intent(at_location, ActionIntent(actor.id, configured.kind))

            if configured.requires_completed_contract:
                assert next_world is at_location
                assert isinstance(events[0], ActionRejected)
                assert events[0].reason == "completed_contract_not_representable"
            else:
                assert isinstance(events[0], ActionSucceeded)
                assert dict(events[0].details)["location_id"] == location.id
                assert dict(events[0].details)["action_id"] == configured.id
