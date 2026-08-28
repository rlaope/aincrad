from __future__ import annotations

from dataclasses import replace

from .events import ActionRejected, ActionSucceeded, DomainEvent
from .models import (
    ActionIntent,
    ActionKind,
    Activity,
    Adventurer,
    ContextualAction,
    EdgeKind,
    LocationKind,
    TravelEdge,
    WorldState,
)
from .progression import apply_damage, restore_stats

_CONTEXTUAL_ACTIVITY = {
    ActionKind.OBSERVE: Activity.OBSERVING,
    ActionKind.SCOUT: Activity.SCOUTING,
    ActionKind.SEARCH: Activity.SEARCHING,
    ActionKind.FIGHT: Activity.FIGHTING,
    ActionKind.HUNT: Activity.FIGHTING,
    ActionKind.CHALLENGE: Activity.FIGHTING,
    ActionKind.CAMP: Activity.CAMPING,
    ActionKind.GATHER: Activity.GATHERING,
}


def _contextual_action(
    adventurer: Adventurer, world: WorldState, action: ActionKind | str
) -> ContextualAction | None:
    if not isinstance(action, ActionKind):
        return None
    matches = tuple(
        configured
        for configured in world.locations[adventurer.location_id].contextual_actions
        if configured.kind is action
    )
    return matches[0] if len(matches) == 1 else None


def _edge_to(world: WorldState, source_id: str, target_id: str) -> TravelEdge | None:
    return next(
        (edge for edge in world.locations[source_id].edges if edge.to == target_id),
        None,
    )


def _is_scene_facility_target(world: WorldState, source_id: str, target_id: str) -> bool:
    target = world.locations.get(target_id)
    edge = _edge_to(world, source_id, target_id)
    return (
        target is not None
        and edge is not None
        and edge.kind is EdgeKind.SCENE
        and bool(target.services)
    )


def _is_scene_egress(world: WorldState, source_id: str, target_id: str) -> bool:
    """Allow a facility occupant to leave through its sole scene edge."""

    source = world.locations[source_id]
    target = world.locations[target_id]
    edge = _edge_to(world, source_id, target_id)
    return (
        edge is not None
        and edge.kind is EdgeKind.SCENE
        and bool(source.services)
        and not target.services
    )


def _apply_contextual_action(
    world: WorldState,
    intent: ActionIntent,
    adventurer: Adventurer,
    action: ContextualAction,
) -> tuple[WorldState, tuple[DomainEvent, ...]]:
    if action.requires_completed_contract:
        return _rejected(world, intent, "completed_contract_not_representable")
    if action.gold_per_resource and intent.quantity <= 0:
        return _rejected(world, intent, "invalid_quantity")
    if action.gold_delta < 0 and adventurer.gold < -action.gold_delta:
        return _rejected(world, intent, "insufficient_gold")
    if action.gold_per_resource and adventurer.resources < intent.quantity:
        return _rejected(world, intent, "insufficient_resources")

    gold_delta = action.gold_delta
    resources = adventurer.resources + action.resource_delta
    if action.gold_per_resource:
        gold_delta += action.gold_per_resource * intent.quantity
        resources -= intent.quantity
    updated = replace(
        adventurer,
        gold=adventurer.gold + gold_delta,
        resources=resources,
        activity=_CONTEXTUAL_ACTIVITY.get(action.kind, Activity.SERVICING),
    )
    before_stats = updated.stats
    updated = restore_stats(updated, hp=action.restore_hp, mp=action.restore_mp)
    encounter_damage = (
        1 if action.kind is ActionKind.FIGHT else 3 if action.kind is ActionKind.CHALLENGE else 0
    )
    if encounter_damage:
        updated = apply_damage(
            updated,
            min(updated.stats.hp, encounter_damage),
            tick=world.tick,
            cause=action.encounter_code or "contextual_encounter",
        )
    details: list[tuple[str, str]] = [
        ("location_id", adventurer.location_id),
        ("action_id", action.id),
        ("action_key", action.kind.value),
    ]
    if action.clue_code is not None:
        details.append(("clue_code", action.clue_code))
    if action.encounter_code is not None:
        details.append(("encounter_code", action.encounter_code))
    if action.outcome_code is not None:
        details.append(("outcome_code", action.outcome_code))
    if gold_delta:
        details.append(("gold_delta", str(gold_delta)))
    if action.resource_delta:
        details.append(("resources_gathered", str(action.resource_delta)))
    if action.gold_per_resource:
        details.append(("resources_sold", str(intent.quantity)))
    if action.restore_hp:
        details.append(("hp_restored", str(updated.stats.hp - before_stats.hp)))
    if action.restore_mp:
        details.append(("mp_restored", str(updated.stats.mp - before_stats.mp)))
    if encounter_damage:
        details.append(("damage", str(min(before_stats.hp, encounter_damage))))
        if not updated.alive:
            details.append(("life_event", "story-end-permanent-death"))
    return _succeeded(world, intent, updated, tuple(details))


def _apply_interaction(
    world: WorldState, intent: ActionIntent, adventurer: Adventurer
) -> tuple[WorldState, tuple[DomainEvent, ...]]:
    selection = intent.interaction
    if selection is None:
        return _rejected(world, intent, "missing_interaction")
    location = world.locations[adventurer.location_id]
    incident = next(
        (item for item in location.interactions if item.id == selection.incident_id),
        None,
    )
    if incident is None:
        return _rejected(world, intent, "unknown_interaction")
    prompts = {prompt.id: prompt for prompt in incident.prompts}
    current_prompt_id = incident.entry_prompt_id
    terminal = None
    for index, (prompt_id, response_id) in enumerate(selection.path):
        if prompt_id != current_prompt_id:
            return _rejected(world, intent, "invalid_interaction_path")
        prompt = prompts.get(prompt_id)
        if prompt is None:
            return _rejected(world, intent, "invalid_interaction_path")
        response = next((item for item in prompt.responses if item.id == response_id), None)
        if response is None:
            return _rejected(world, intent, "invalid_interaction_path")
        if response.terminal is not None:
            if index != len(selection.path) - 1:
                return _rejected(world, intent, "invalid_interaction_path")
            terminal = response.terminal
        elif response.next_prompt_id is not None:
            if index == len(selection.path) - 1:
                return _rejected(world, intent, "incomplete_interaction_path")
            current_prompt_id = response.next_prompt_id
        else:
            return _rejected(world, intent, "invalid_interaction_path")
    if terminal is None:
        return _rejected(world, intent, "incomplete_interaction_path")
    if terminal.gold_delta < 0 and adventurer.gold < -terminal.gold_delta:
        return _rejected(world, intent, "insufficient_gold")
    updated = replace(
        adventurer,
        gold=adventurer.gold + terminal.gold_delta,
        resources=adventurer.resources + terminal.resource_delta,
        activity=Activity.SERVICING,
    )
    details: list[tuple[str, str]] = [
        ("location_id", location.id),
        ("incident_id", incident.id),
        ("prompt_path", "/".join(prompt_id for prompt_id, _ in selection.path)),
        ("response_id", selection.path[-1][1]),
        ("outcome_code", terminal.outcome_code),
    ]
    if terminal.gold_delta:
        details.append(("gold_delta", str(terminal.gold_delta)))
    if terminal.resource_delta:
        details.append(("resource_delta", str(terminal.resource_delta)))
    return _succeeded(world, intent, updated, tuple(details))


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
    world: WorldState,
    intent: ActionIntent,
    *,
    gather_yield: int = 1,
    legacy_connection_moves: bool = False,
) -> tuple[WorldState, tuple[DomainEvent, ...]]:
    adventurer = world.adventurers.get(intent.adventurer_id)
    if adventurer is None:
        return _rejected(world, intent, "unknown_adventurer")
    if not adventurer.can_act:
        return _rejected(world, intent, "adventurer_dead")
    if type(intent.quantity) is not int or intent.quantity <= 0:
        return _rejected(world, intent, "invalid_quantity")
    if intent.action is ActionKind.MOVE and intent.quantity != 1:
        return _rejected(world, intent, "invalid_quantity")
    if intent.action is not ActionKind.ENGAGE_INCIDENT and intent.interaction is not None:
        return _rejected(world, intent, "unexpected_interaction")
    if intent.action is ActionKind.ENGAGE_INCIDENT:
        if intent.quantity != 1:
            return _rejected(world, intent, "invalid_quantity")
        if intent.interaction is None:
            return _rejected(world, intent, "missing_interaction")
        if intent.target_location_id is not None:
            if not _is_scene_facility_target(
                world, adventurer.location_id, intent.target_location_id
            ):
                return _rejected(world, intent, "unexpected_target_location")
            return _apply_interaction(
                world, intent, replace(adventurer, location_id=intent.target_location_id)
            )
        return _apply_interaction(world, intent, adventurer)
    if intent.action is not ActionKind.MOVE and intent.target_location_id is not None:
        target_is_connected_facility = _is_scene_facility_target(
            world, adventurer.location_id, intent.target_location_id
        )
        if not target_is_connected_facility:
            return _rejected(world, intent, "unexpected_target_location")
        target_action = _contextual_action(
            replace(adventurer, location_id=intent.target_location_id), world, intent.action
        )
        if target_action is None:
            return _rejected(world, intent, "unexpected_target_location")
        if intent.quantity != 1:
            return _rejected(world, intent, "invalid_quantity")
        return _apply_contextual_action(
            world,
            intent,
            replace(adventurer, location_id=intent.target_location_id),
            target_action,
        )

    contextual_action = _contextual_action(adventurer, world, intent.action)
    if contextual_action is not None:
        if intent.quantity != 1:
            return _rejected(world, intent, "invalid_quantity")
        return _apply_contextual_action(world, intent, adventurer, contextual_action)
    location = world.locations[adventurer.location_id]
    if location.contextual_actions and intent.action is not ActionKind.MOVE:
        return _rejected(world, intent, "action_not_available_at_location")

    if intent.action is ActionKind.MOVE:
        destination = intent.target_location_id
        if type(destination) is not str:
            return _rejected(world, intent, "invalid_target_location")
        if destination not in world.locations:
            return _rejected(world, intent, "unknown_location")
        edge = _edge_to(world, adventurer.location_id, destination)
        if edge is None:
            return _rejected(world, intent, "location_not_connected")
        if (
            edge.kind is EdgeKind.SCENE
            and not legacy_connection_moves
            and not _is_scene_egress(world, adventurer.location_id, destination)
        ):
            return _rejected(world, intent, "scene_edge_not_travel")
        return _succeeded(
            world,
            intent,
            replace(adventurer, location_id=destination, activity=Activity.MOVING),
            (("destination", destination),)
            if legacy_connection_moves
            else (("destination", destination), ("edge_kind", edge.kind.value)),
        )

    if intent.action is ActionKind.REST:
        return _succeeded(
            world,
            intent,
            replace(restore_stats(adventurer, hp=2, mp=2), activity=Activity.RESTING),
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
