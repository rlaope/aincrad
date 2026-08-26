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


def test_domain_event_is_an_explicit_dataclass_base_type() -> None:
    assert is_dataclass(DomainEvent)


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
            details=(('destination', 'field'),),
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
    gathered, _ = apply_intent(
        at_field, ActionIntent("mira", ActionKind.GATHER), gather_yield=2
    )
    assert gathered.adventurers["mira"].resources == 2
    assert gathered.adventurers["mira"].activity is Activity.GATHERING

    at_town, _ = apply_intent(
        gathered, ActionIntent("mira", ActionKind.MOVE, target_location_id="town")
    )
    traded, _ = apply_intent(
        at_town, ActionIntent("mira", ActionKind.TRADE, quantity=2)
    )
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
