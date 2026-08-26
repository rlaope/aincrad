from __future__ import annotations

from dataclasses import replace

from aincrad.domain import (
    ActionKind,
    ActionSucceeded,
    Adventurer,
    CharacterClass,
    DomainEvent,
    Stats,
    WorldState,
)
from aincrad.domain.progression import apply_damage, award_exp, recruit, remove, spend_mp

_COMPANION_ID = "rhea-companion"
_RECRUIT_EVENT = "companion-recruit-rhea"
_DEPART_EVENT = "companion-depart-rhea"
_DEATH_EVENT = "story-end-permanent-death"


def _set_adventurer(world: WorldState, adventurer: Adventurer) -> WorldState:
    return replace(world, adventurers={**world.adventurers, adventurer.id: adventurer})


def apply_action_progression(
    before: WorldState,
    after: WorldState,
    event: DomainEvent,
    *,
    xp_award: int,
    hazard_damage: int,
) -> tuple[WorldState, DomainEvent]:
    """Apply deterministic live progression and preserve every input in event details."""
    if not isinstance(event, ActionSucceeded):
        return after, event
    if not 1 <= xp_award <= 25:
        raise ValueError("runtime XP award must be between 1 and 25")
    if hazard_damage < 0:
        raise ValueError("runtime hazard damage cannot be negative")

    previous = before.adventurers[event.adventurer_id]
    adventurer = after.adventurers[event.adventurer_id]
    details = list(event.details)

    if event.action is ActionKind.REST:
        details.extend(
            (
                ("hp_restored", str(adventurer.stats.hp - previous.stats.hp)),
                ("mp_restored", str(adventurer.stats.mp - previous.stats.mp)),
            )
        )
    if event.action is ActionKind.GATHER:
        mp_spent = min(1, adventurer.stats.mp)
        adventurer = spend_mp(adventurer, mp_spent)
        details.append(("mp_spent", str(mp_spent)))
    destination = event.target_location_id
    if (
        event.action is ActionKind.MOVE
        and destination is not None
        and after.locations[destination].kind.value == "dungeon"
    ):
        actual_damage = min(adventurer.stats.hp, hazard_damage)
        adventurer = apply_damage(
            adventurer,
            actual_damage,
            tick=event.tick,
            cause="dungeon_hazard",
        )
        details.append(("damage", str(actual_damage)))
        if not adventurer.alive:
            details.append(("life_event", _DEATH_EVENT))

    if adventurer.alive:
        adventurer = award_exp(adventurer, xp_award)
        details.append(("xp_awarded", str(xp_award)))
    else:
        details.append(("xp_awarded", "0"))
    details.extend(
        (
            ("character_class", adventurer.character_class.value),
            ("level", str(adventurer.level)),
            ("exp", str(adventurer.exp)),
            ("mp", str(adventurer.stats.mp)),
            ("hp", str(adventurer.stats.hp)),
            ("alive", str(adventurer.alive).lower()),
        )
    )
    after = _set_adventurer(after, adventurer)
    return after, replace(event, details=tuple(details))


def apply_life_events(
    world: WorldState, events: tuple[DomainEvent, ...]
) -> tuple[WorldState, tuple[DomainEvent, ...]]:
    """Apply deterministic membership effects only after the whole action batch."""
    party = world.party
    if party is None:
        raise ValueError("world has no runtime party")
    changed_events = list(events)
    hero_event_index = next(
        (
            index
            for index, event in enumerate(events)
            if event.adventurer_id == party.selected_hero_id
            and isinstance(event, ActionSucceeded)
        ),
        None,
    )
    if hero_event_index is None:
        return world, events
    hero_event = events[hero_event_index]
    if not isinstance(hero_event, ActionSucceeded):
        return world, events

    if (
        hero_event.action is ActionKind.MOVE
        and hero_event.target_location_id == "mossreach"
        and _COMPANION_ID not in party.member_ids
        and len(party.member_ids) < party.cap
    ):
        companion = Adventurer(
            id=_COMPANION_ID,
            name="Rhea Vale",
            location_id="mossreach",
            stats=Stats(24, 24, 8, 8),
            gold=5,
            character_class=CharacterClass.TANK,
        )
        party = recruit(party, companion.id)
        world = replace(
            world,
            adventurers={**world.adventurers, companion.id: companion},
            party=party,
        )
        changed_events[hero_event_index] = replace(
            hero_event,
            details=(
                *hero_event.details,
                ("life_event", _RECRUIT_EVENT),
                ("party_action", "add"),
                ("companion_id", companion.id),
                ("companion_class", companion.character_class.value),
            ),
        )
    elif (
        hero_event.action is ActionKind.MOVE
        and hero_event.target_location_id == "emberfall"
        and _COMPANION_ID in party.member_ids
    ):
        party = remove(party, _COMPANION_ID)
        adventurers = dict(world.adventurers)
        del adventurers[_COMPANION_ID]
        world = replace(world, adventurers=adventurers, party=party)
        changed_events[hero_event_index] = replace(
            hero_event,
            details=(
                *hero_event.details,
                ("life_event", _DEPART_EVENT),
                ("party_action", "remove"),
                ("companion_id", _COMPANION_ID),
            ),
        )
    return world, tuple(changed_events)
