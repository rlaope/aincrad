from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, replace
from random import Random

from aincrad.domain import ActionIntent, ActionKind, DomainEvent, WorldState
from aincrad.domain.rules import apply_intent

from .runtime import action_awards_xp, apply_action_progression


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
    legacy_all_actions_award_xp: bool = False

    def run_hour(
        self, initial_state: WorldState, intents: Iterable[ActionIntent]
    ) -> SimulationResult:
        submitted = tuple(intents)
        party = initial_state.party
        if party is None:  # WorldState normalizes this, retained for type narrowing.
            raise ValueError("world has no runtime party")
        order = {actor_id: index for index, actor_id in enumerate(party.member_ids)}
        hourly_intents = tuple(
            sorted(submitted, key=lambda intent: order.get(intent.adventurer_id, len(order)))
        )
        actor_ids = tuple(intent.adventurer_id for intent in hourly_intents)
        if len(actor_ids) != len(set(actor_ids)):
            raise ValueError("each adventurer may submit at most one action per hour")
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

        world = initial_state
        events: list[DomainEvent] = []
        next_tick = initial_state.tick + 1
        for intent in hourly_intents:
            random = _actor_random(
                self.seed, initial_state.tick, "action", intent.adventurer_id
            )
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
                    xp_award=(
                        random.randint(1, 25)
                        if self.legacy_all_actions_award_xp
                        or action_awards_xp(intent.action)
                        else 0
                    ),
                    hazard_damage=hazard_damage,
                    legacy_all_actions_award_xp=self.legacy_all_actions_award_xp,
                )
                progressed.append(event)
            emitted = tuple(progressed)
            if any(event.tick != initial_state.tick for event in emitted):
                raise ValueError("hourly actions must share the same tick")
            if any(event.next_tick != next_tick for event in emitted):
                raise ValueError("hourly actions must share the next tick")
            events.extend(emitted)
        return SimulationResult(replace(world, tick=next_tick), tuple(events))

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


def _actor_random(seed: int, tick: int, channel: str, actor_id: str) -> Random:
    """Return an actor-local RNG independent of proposal arrival order."""

    material = f"{seed}\0{tick}\0{channel}\0{actor_id}".encode()
    return Random(int.from_bytes(hashlib.sha256(material).digest(), "big"))
