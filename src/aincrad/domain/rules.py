from __future__ import annotations

from dataclasses import replace

from .events import ActionRejected, ActionSucceeded, DomainEvent
from .models import (
    ActionIntent,
    ActionKind,
    Activity,
    Adventurer,
    LocationKind,
    Stats,
    WorldState,
)


def _rejected(
    world: WorldState, intent: ActionIntent, reason: str
) -> tuple[WorldState, tuple[DomainEvent, ...]]:
    return world, (
        ActionRejected(
            tick=world.tick,
            adventurer_id=intent.adventurer_id,
            action=intent.action,
            next_tick=world.tick + 1,
            target_location_id=intent.target_location_id,
            quantity=intent.quantity,
            reason=reason,
        ),
    )


def _succeeded(
    world: WorldState,
    intent: ActionIntent,
    adventurer: Adventurer,
    details: tuple[tuple[str, str], ...] = (),
) -> tuple[WorldState, tuple[DomainEvent, ...]]:
    adventurers = dict(world.adventurers)
    adventurers[adventurer.id] = adventurer
    next_world = replace(world, adventurers=adventurers)
    return next_world, (
        ActionSucceeded(
            tick=world.tick,
            adventurer_id=adventurer.id,
            action=intent.action,
            next_tick=world.tick + 1,
            target_location_id=intent.target_location_id,
            quantity=intent.quantity,
            details=details,
        ),
    )


def apply_intent(
    world: WorldState, intent: ActionIntent, *, gather_yield: int = 1
) -> tuple[WorldState, tuple[DomainEvent, ...]]:
    adventurer = world.adventurers.get(intent.adventurer_id)
    if adventurer is None:
        return _rejected(world, intent, "unknown_adventurer")

    if intent.action is ActionKind.MOVE:
        destination = intent.target_location_id
        if destination not in world.locations:
            return _rejected(world, intent, "unknown_location")
        if destination not in world.locations[adventurer.location_id].connections:
            return _rejected(world, intent, "location_not_connected")
        return _succeeded(
            world,
            intent,
            replace(adventurer, location_id=destination, activity=Activity.MOVING),
            (("destination", destination),),
        )

    if intent.action is ActionKind.REST:
        stats = adventurer.stats
        restored = Stats(
            hp=min(stats.max_hp, stats.hp + 2),
            max_hp=stats.max_hp,
            mp=min(stats.max_mp, stats.mp + 2),
            max_mp=stats.max_mp,
        )
        return _succeeded(
            world, intent, replace(adventurer, stats=restored, activity=Activity.RESTING)
        )

    if intent.action is ActionKind.GATHER:
        location = world.locations[adventurer.location_id]
        if location.kind is not LocationKind.HUNTING_GROUND:
            return _rejected(world, intent, "gather_not_allowed")
        if gather_yield < 0:
            return _rejected(world, intent, "invalid_gather_yield")
        return _succeeded(
            world,
            intent,
            replace(
                adventurer,
                resources=adventurer.resources + gather_yield,
                activity=Activity.GATHERING,
            ),
            (("resources_gathered", str(gather_yield)),),
        )

    if intent.action is ActionKind.TRADE:
        location = world.locations[adventurer.location_id]
        if location.kind is not LocationKind.TOWN:
            return _rejected(world, intent, "trade_not_allowed")
        if intent.quantity <= 0:
            return _rejected(world, intent, "invalid_quantity")
        if adventurer.resources < intent.quantity:
            return _rejected(world, intent, "insufficient_resources")
        return _succeeded(
            world,
            intent,
            replace(
                adventurer,
                resources=adventurer.resources - intent.quantity,
                gold=adventurer.gold + intent.quantity * 2,
                activity=Activity.TRADING,
            ),
            (("resources_sold", str(intent.quantity)),),
        )

    if intent.action is ActionKind.WAIT:
        return _succeeded(world, intent, replace(adventurer, activity=Activity.WAITING))

    return _rejected(world, intent, "invalid_action")
