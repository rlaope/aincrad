from dataclasses import replace

from aincrad.cli import _starting_world
from aincrad.domain import ActionIntent, ActionKind, ActionSucceeded, CharacterClass, DomainEvent
from aincrad.simulation import SimulationScheduler


def _details(event: DomainEvent) -> dict[str, str]:
    assert isinstance(event, ActionSucceeded)
    return dict(event.details)


def test_successful_gather_awards_bounded_xp_and_spends_mp() -> None:
    world = _starting_world(CharacterClass.MAGE)
    hero = replace(world.adventurers["hero-mage"], location_id="mossreach")
    world = replace(world, adventurers={hero.id: hero})

    result = SimulationScheduler(seed=7).run_hour(
        world, (ActionIntent(hero.id, ActionKind.GATHER),)
    )

    progressed = result.final_state.adventurers[hero.id]
    details = _details(result.events[0])
    assert 1 <= int(details["xp_awarded"]) <= 25
    assert progressed.exp == int(details["exp"])
    assert progressed.stats.mp == hero.stats.mp - int(details["mp_spent"])
    assert int(details["mp_spent"]) > 0


def test_rest_restores_mp_and_records_exact_progression_details() -> None:
    world = _starting_world(CharacterClass.WARRIOR)
    hero = world.adventurers["hero-warrior"]
    depleted = replace(hero, stats=replace(hero.stats, hp=20, mp=1))
    world = replace(world, adventurers={depleted.id: depleted})

    result = SimulationScheduler(seed=2).run_hour(
        world, (ActionIntent(depleted.id, ActionKind.REST),)
    )

    restored = result.final_state.adventurers[depleted.id]
    details = _details(result.events[0])
    assert restored.stats.mp > depleted.stats.mp
    assert details["mp_restored"] == str(restored.stats.mp - depleted.stats.mp)
    assert details["hp_restored"] == str(restored.stats.hp - depleted.stats.hp)


def test_dungeon_hazard_can_cause_permanent_death() -> None:
    world = _starting_world(CharacterClass.MAGE)
    hero = world.adventurers["hero-mage"]
    fragile = replace(
        hero,
        location_id="mossreach",
        stats=replace(hero.stats, hp=1),
    )
    world = replace(world, adventurers={fragile.id: fragile})

    result = SimulationScheduler(seed=1).run_hour(
        world,
        (ActionIntent(fragile.id, ActionKind.MOVE, target_location_id="vault-1"),),
    )

    fallen = result.final_state.adventurers[fragile.id]
    details = _details(result.events[0])
    assert fallen.alive is False
    assert fallen.death_tick == 0
    assert fallen.death_cause == "dungeon_hazard"
    assert details["life_event"] == "story-end-permanent-death"
    assert details["alive"] == "false"
    assert details["damage"] == "1"


def test_recruitment_and_departure_change_runtime_party_after_complete_batches() -> None:
    world = _starting_world(CharacterClass.ARCHER)
    scheduler = SimulationScheduler(seed=5)

    recruited = scheduler.run_hour(
        world,
        (
            ActionIntent(
                "hero-archer", ActionKind.MOVE, target_location_id="mossreach"
            ),
        ),
    )
    party = recruited.final_state.party
    assert party is not None
    assert party.member_ids == ("hero-archer", "rhea-companion")
    assert "rhea-companion" in recruited.final_state.adventurers
    assert _details(recruited.events[0])["life_event"] == "companion-recruit-rhea"

    departed = scheduler.run_hour(
        recruited.final_state,
        (
            ActionIntent(
                "hero-archer", ActionKind.MOVE, target_location_id="emberfall"
            ),
            ActionIntent("rhea-companion", ActionKind.WAIT),
        ),
    )
    party = departed.final_state.party
    assert party is not None
    assert party.member_ids == ("hero-archer",)
    assert "rhea-companion" not in departed.final_state.adventurers
    assert _details(departed.events[0])["life_event"] == "companion-depart-rhea"
