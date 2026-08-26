from aincrad.domain import ActionIntent, ActionKind
from aincrad.simulation import SimulationScheduler, create_initial_world


def test_same_seed_initial_state_and_intents_are_deterministic() -> None:
    initial = create_initial_world()
    intents = (
        ActionIntent("rhea-vale", ActionKind.MOVE, target_location_id="mossreach"),
        ActionIntent("rhea-vale", ActionKind.GATHER),
        ActionIntent("tovin-reed", ActionKind.REST),
        ActionIntent("sable-quill", ActionKind.WAIT),
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
        ActionIntent("rhea-vale", ActionKind.MOVE, target_location_id="mossreach"),
        *(ActionIntent("rhea-vale", ActionKind.GATHER) for _ in range(25)),
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
