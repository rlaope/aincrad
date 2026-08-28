from dataclasses import replace

import pytest

from aincrad.domain import ActionIntent, ActionKind
from aincrad.domain.progression import start_party
from aincrad.simulation import SimulationScheduler, create_initial_world


def test_same_seed_initial_state_and_intents_are_deterministic() -> None:
    initial = create_initial_world()
    intents = (
        ActionIntent("rhea-vale", ActionKind.MOVE, target_location_id="mossreach-terraces"),
        ActionIntent("rhea-vale", ActionKind.MOVE, target_location_id="mossreach"),
        ActionIntent("rhea-vale", ActionKind.GATHER),
        ActionIntent("tovin-reed", ActionKind.REST),
        ActionIntent("sable-quill", ActionKind.WAIT),
        ActionIntent("rhea-vale", ActionKind.MOVE, target_location_id="mossreach-terraces"),
        ActionIntent("rhea-vale", ActionKind.MOVE, target_location_id="emberfall"),
        ActionIntent("rhea-vale", ActionKind.TRADE, quantity=1),
    )

    first = SimulationScheduler(seed=1729).run(initial, intents)
    second = SimulationScheduler(seed=1729).run(initial, intents)

    assert first == second
    assert first.final_state.tick == len(intents)
    assert tuple(event.tick for event in first.events) == tuple(range(len(intents)))


def test_many_seeded_runs_preserve_stat_and_wealth_invariants() -> None:
    intents = (
        ActionIntent("rhea-vale", ActionKind.MOVE, target_location_id="mossreach-terraces"),
        ActionIntent("rhea-vale", ActionKind.MOVE, target_location_id="mossreach"),
        *(ActionIntent("rhea-vale", ActionKind.GATHER) for _ in range(25)),
        ActionIntent("rhea-vale", ActionKind.MOVE, target_location_id="mossreach-terraces"),
        ActionIntent("rhea-vale", ActionKind.MOVE, target_location_id="emberfall"),
        ActionIntent("rhea-vale", ActionKind.TRADE, quantity=10_000),
        *(ActionIntent("tovin-reed", ActionKind.REST) for _ in range(25)),
    )

    for seed in range(50):
        result = SimulationScheduler(seed=seed).run(create_initial_world(), intents)
        for adventurer in result.final_state.adventurers.values():
            assert 0 <= adventurer.stats.hp <= adventurer.stats.max_hp
            assert 0 <= adventurer.stats.mp <= adventurer.stats.max_mp
            assert adventurer.gold >= 0
            assert adventurer.resources >= 0


def test_hourly_batch_processes_three_adventurers_before_advancing_time() -> None:
    initial = create_initial_world()
    intents = (
        ActionIntent("rhea-vale", ActionKind.WAIT),
        ActionIntent("tovin-reed", ActionKind.REST),
        ActionIntent("sable-quill", ActionKind.WAIT),
    )

    result = SimulationScheduler(seed=7).run_hour(initial, intents)

    assert result.final_state.tick == 1
    assert tuple(event.tick for event in result.events) == (0, 0, 0)
    assert tuple(event.next_tick for event in result.events) == (1, 1, 1)


@pytest.mark.parametrize(
    ("intents", "message"),
    [
        ((), "exactly one action"),
        ((ActionIntent("rhea-vale", ActionKind.WAIT),), "exactly one action"),
        (
            (
                ActionIntent("rhea-vale", ActionKind.WAIT),
                ActionIntent("tovin-reed", ActionKind.WAIT),
                ActionIntent("sable-quill", ActionKind.WAIT),
                ActionIntent("outsider", ActionKind.WAIT),
            ),
            "exactly one action",
        ),
    ],
)
def test_hourly_batch_rejects_zero_omitted_and_extra_actors_without_advancing(
    intents: tuple[ActionIntent, ...], message: str
) -> None:
    initial = create_initial_world()

    with pytest.raises(ValueError, match=message):
        SimulationScheduler(seed=7).run_hour(initial, intents)

    assert initial.tick == 0


def test_hourly_batch_requires_only_living_current_party_members() -> None:
    initial = create_initial_world()
    party = start_party("rhea-vale", cap=3)
    party = replace(party, member_ids=("rhea-vale", "tovin-reed"))
    dead = replace(
        initial.adventurers["tovin-reed"],
        stats=replace(initial.adventurers["tovin-reed"].stats, hp=0),
        alive=False,
        death_tick=0,
    )
    world = replace(
        initial,
        adventurers={**initial.adventurers, "tovin-reed": dead},
        party=party,
    )

    result = SimulationScheduler(seed=7).run_hour(
        world, (ActionIntent("rhea-vale", ActionKind.WAIT),)
    )
    assert result.final_state.tick == 1

    with pytest.raises(ValueError, match="exactly one action"):
        SimulationScheduler(seed=7).run_hour(
            world,
            (
                ActionIntent("rhea-vale", ActionKind.WAIT),
                ActionIntent("tovin-reed", ActionKind.WAIT),
            ),
        )
