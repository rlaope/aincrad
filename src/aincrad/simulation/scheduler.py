from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from random import Random

from aincrad.domain import ActionIntent, ActionKind, DomainEvent, WorldState
from aincrad.domain.rules import apply_intent


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
