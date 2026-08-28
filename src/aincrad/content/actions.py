"""Canonical fixture-backed contextual actions for The Glass Frontier."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import cast

from aincrad.domain.models import ActionIntent, ActionKind, ContextualAction, WorldState

_EXPECTED_ACTION_KINDS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
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
)

EXPECTED_FACILITY_SERVICES: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
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
)


def expected_action_kinds(location_id: str) -> tuple[str, ...]:
    """Return the non-MOVE action keys required by the canonical location."""

    return _EXPECTED_ACTION_KINDS[location_id]


def _required_text(raw: Mapping[str, object], field: str) -> str:
    value = raw[field]
    if not isinstance(value, str):
        raise ValueError(f"fixture action {field} must be text")
    return value


def _optional_text(raw: Mapping[str, object], field: str) -> str | None:
    value = raw.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"fixture action {field} must be text")
    return value


def _integer(raw: Mapping[str, object], field: str) -> int:
    value = raw.get(field, 0)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"fixture action {field} must be an integer")
    return value


def _contextual_action(raw: Mapping[str, object]) -> ContextualAction:
    kind = ActionKind(_required_text(raw, "kind"))
    return ContextualAction(
        id=_required_text(raw, "id"),
        kind=kind,
        label_ko=_required_text(raw, "label_ko"),
        description_ko=_required_text(raw, "description_ko"),
        service=_optional_text(raw, "service"),
        clue_code=_optional_text(raw, "clue_code"),
        encounter_code=_optional_text(raw, "encounter_code"),
        outcome_code=_optional_text(raw, "outcome_code"),
        requires_completed_contract=raw.get("requires_completed_contract", False) is True,
        gold_delta=_integer(raw, "gold_delta"),
        gold_per_resource=_integer(raw, "gold_per_resource"),
        resource_delta=_integer(raw, "resource_delta"),
        restore_hp=_integer(raw, "restore_hp"),
        restore_mp=_integer(raw, "restore_mp"),
    )


def action_catalog_from_fixture(
    fixture: Mapping[str, object],
) -> Mapping[str, tuple[ContextualAction, ...]]:
    """Build immutable location action metadata from a validated world fixture."""

    towns = cast(Sequence[Mapping[str, object]], fixture["towns"])
    grounds = cast(Sequence[Mapping[str, object]], fixture["hunting_grounds"])
    dungeons = cast(Sequence[Mapping[str, object]], fixture["dungeons"])
    locations: list[Mapping[str, object]] = []
    for town in towns:
        locations.append(town)
        locations.extend(cast(Sequence[Mapping[str, object]], town["facilities"]))
    locations.extend(grounds)
    for dungeon in dungeons:
        locations.extend(cast(Sequence[Mapping[str, object]], dungeon["floors"]))
    return MappingProxyType(
        {
            _required_text(location, "id"): tuple(
                _contextual_action(action)
                for action in cast(Sequence[Mapping[str, object]], location["actions"])
            )
            for location in locations
        }
    )


def contextual_action_for_intent(
    world: WorldState, intent: ActionIntent
) -> ContextualAction | None:
    """Resolve exactly one local contextual action, returning None on ambiguity or mismatch."""

    actor = world.adventurers.get(intent.adventurer_id)
    if actor is None or not isinstance(intent.action, ActionKind):
        return None
    matches = tuple(
        action
        for action in world.locations[actor.location_id].contextual_actions
        if action.kind is intent.action
    )
    return matches[0] if len(matches) == 1 else None


def available_action_intents(world: WorldState, adventurer_id: str) -> tuple[ActionIntent, ...]:
    """Offer connected movement and actions currently representable by WorldState."""

    adventurer = world.adventurers.get(adventurer_id)
    if adventurer is None or not adventurer.can_act:
        return ()
    location = world.locations[adventurer.location_id]
    moves = tuple(
        ActionIntent(adventurer_id, ActionKind.MOVE, target_location_id=destination)
        for destination in location.connections
    )
    local = tuple(
        ActionIntent(adventurer_id, action.kind) for action in location.contextual_actions
    )
    return (*moves, *local)
