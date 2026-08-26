from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from random import Random

from aincrad.domain import ActionIntent, ActionKind, DomainEvent, WorldState
from aincrad.domain.rules import apply_intent

from .runtime import apply_action_progression, apply_life_events


@dataclass(frozen=True, slots=True)
class SimulationClock:
    tick: int = 0

    def advance(self) -> SimulationClock:
        return SimulationClock(self.tick + 1)


@dataclass(frozen=True, slots=True)
class SimulationResult:
    final_state: WorldState
    events: tuple[DomainEvent, ...]


@dataclass(frozen=True, slots=True)
class SimulationScheduler:
    seed: int

    def run_hour(
        self, initial_state: WorldState, intents: Iterable[ActionIntent]
    ) -> SimulationResult:
        hourly_intents = tuple(intents)
        actor_ids = tuple(intent.adventurer_id for intent in hourly_intents)
        if len(actor_ids) != len(set(actor_ids)):
            raise ValueError("each adventurer may submit at most one action per hour")
        party = initial_state.party
        if party is None:  # WorldState normalizes this, retained for type narrowing.
            raise ValueError("world has no runtime party")
        expected_actor_ids = {
            member_id
            for member_id in party.member_ids
            if initial_state.adventurers[member_id].alive
        }
        if not expected_actor_ids:
            raise ValueError("hourly batch cannot be empty")
        if set(actor_ids) != expected_actor_ids or len(actor_ids) != len(expected_actor_ids):
            raise ValueError(
                "hourly batch requires exactly one action from every living current party member"
            )

        random = Random(self.seed + initial_state.tick)
        world = initial_state
        events: list[DomainEvent] = []
        next_tick = initial_state.tick + 1
        for intent in hourly_intents:
            gather_yield = random.randint(1, 3) if intent.action is ActionKind.GATHER else 1
            before_action = world
            world, emitted = apply_intent(world, intent, gather_yield=gather_yield)
            progressed: list[DomainEvent] = []
            for event in emitted:
                destination = intent.target_location_id
                is_dungeon_move = (
                    intent.action is ActionKind.MOVE
                    and destination is not None
                    and destination in world.locations
                    and world.locations[destination].kind.value == "dungeon"
                )
                hazard_damage = (
                    random.randint(
                        1,
                        before_action.adventurers[intent.adventurer_id].stats.max_hp,
                    )
                    if is_dungeon_move
                    else 0
                )
                world, event = apply_action_progression(
                    before_action,
                    world,
                    event,
                    xp_award=random.randint(1, 25),
                    hazard_damage=hazard_damage,
                )
                progressed.append(event)
            emitted = tuple(progressed)
            if any(event.tick != initial_state.tick for event in emitted):
                raise ValueError("hourly actions must share the same tick")
            if any(event.next_tick != next_tick for event in emitted):
                raise ValueError("hourly actions must share the next tick")
            events.extend(emitted)
        world, finalized_events = apply_life_events(world, tuple(events))
        return SimulationResult(replace(world, tick=next_tick), finalized_events)

    def run(
        self, initial_state: WorldState, intents: Iterable[ActionIntent]
    ) -> SimulationResult:
        random = Random(self.seed)
        world = initial_state
        clock = SimulationClock(initial_state.tick)
        events: list[DomainEvent] = []
        for intent in intents:
            gather_yield = random.randint(1, 3) if intent.action is ActionKind.GATHER else 1
            world, emitted = apply_intent(world, intent, gather_yield=gather_yield)
            events.extend(emitted)
            clock = clock.advance()
            if any(event.next_tick != clock.tick for event in emitted):
                raise ValueError("domain event did not record the scheduler tick transition")
            world = replace(world, tick=clock.tick)
        return SimulationResult(world, tuple(events))
