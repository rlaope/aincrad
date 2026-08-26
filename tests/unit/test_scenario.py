from aincrad.simulation.scenario import create_initial_world


def test_initial_scenario_matches_the_glass_frontier_party() -> None:
    world = create_initial_world()

    assert set(world.adventurers) == {"rhea-vale", "tovin-reed", "sable-quill"}
    assert set(world.locations) == {
        "emberfall",
        "mossreach",
        "vault-1",
        "vault-2",
        "vault-3",
    }
