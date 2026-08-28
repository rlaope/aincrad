from dataclasses import replace

import pytest

from aincrad.cli import _starting_world
from aincrad.domain import ActionIntent, ActionKind, ActionSucceeded, CharacterClass, DomainEvent
from aincrad.simulation import SimulationScheduler
from aincrad.simulation.runtime import action_awards_xp


def _details(event: DomainEvent) -> dict[str, str]:
    assert isinstance(event, ActionSucceeded)
    return dict(event.details)


def test_successful_gather_awards_bounded_xp_and_spends_mp() -> None:
    world = _starting_world(CharacterClass.MAGE)
    hero = replace(world.adventurers["hero"], location_id="mossreach")
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


@pytest.mark.parametrize(
    ("intent", "location_id", "starting_stats"),
    (
        (
            ActionIntent("hero", ActionKind.MOVE, target_location_id="mossreach"),
            "emberfall",
            None,
        ),
        (ActionIntent("hero", ActionKind.OBSERVE), "emberfall", None),
        (ActionIntent("hero", ActionKind.LODGE), "emberfall-inn", (20, 1)),
    ),
    ids=("move", "observe", "lodge"),
)
def test_successful_passive_actions_award_exactly_zero_xp(
    intent: ActionIntent,
    location_id: str,
    starting_stats: tuple[int, int] | None,
) -> None:
    world = _starting_world(CharacterClass.WARRIOR)
    hero = replace(world.adventurers["hero"], location_id=location_id)
    if starting_stats is not None:
        hp, mp = starting_stats
        hero = replace(hero, stats=replace(hero.stats, hp=hp, mp=mp))
        world = replace(world, adventurers={hero.id: hero})

    result = SimulationScheduler(seed=23).run_hour(
        world, (replace(intent, adventurer_id=hero.id),)
    )

    progressed = result.final_state.adventurers[hero.id]
    details = _details(result.events[0])
    assert details["xp_awarded"] == "0"
    assert progressed.exp == hero.exp


def test_successful_town_trade_awards_exactly_zero_xp() -> None:
    world = _starting_world(CharacterClass.WARRIOR)
    hero = replace(
        world.adventurers["hero"],
        location_id="emberfall-shop",
        resources=1,
    )
    world = replace(world, adventurers={hero.id: hero})

    result = SimulationScheduler(seed=23).run_hour(
        world, (ActionIntent(hero.id, ActionKind.SELL_SALVAGE, quantity=1),)
    )

    progressed = result.final_state.adventurers[hero.id]
    details = _details(result.events[0])
    assert details["xp_awarded"] == "0"
    assert progressed.exp == hero.exp


@pytest.mark.parametrize(
    "action",
    (
        ActionKind.GATHER,
        ActionKind.HUNT,
        ActionKind.SCOUT,
        ActionKind.FIGHT,
        ActionKind.SEARCH,
        ActionKind.CHALLENGE,
        ActionKind.TURN_IN_CONTRACT,
    ),
)
def test_meaningful_contextual_actions_are_xp_eligible(action: ActionKind) -> None:
    assert action_awards_xp(action) is True


def test_lodge_restores_mp_and_records_exact_progression_details() -> None:
    world = _starting_world(CharacterClass.WARRIOR)
    hero = world.adventurers["hero"]
    depleted = replace(
        hero,
        location_id="emberfall-inn",
        stats=replace(hero.stats, hp=20, mp=1),
    )
    world = replace(world, adventurers={depleted.id: depleted})

    result = SimulationScheduler(seed=2).run_hour(
        world, (ActionIntent(depleted.id, ActionKind.LODGE),)
    )

    restored = result.final_state.adventurers[depleted.id]
    details = _details(result.events[0])
    assert restored.stats.mp > depleted.stats.mp
    assert details["mp_restored"] == str(restored.stats.mp - depleted.stats.mp)
    assert details["hp_restored"] == str(restored.stats.hp - depleted.stats.hp)


def test_dungeon_fight_applies_canonical_damage_before_awarding_xp() -> None:
    world = _starting_world(CharacterClass.WARRIOR)
    hero = replace(world.adventurers["hero"], location_id="vault-1")
    world = replace(world, adventurers={hero.id: hero})

    result = SimulationScheduler(seed=29).run_hour(
        world,
        (ActionIntent(hero.id, ActionKind.FIGHT),),
    )

    fought = result.final_state.adventurers[hero.id]
    details = _details(result.events[0])
    assert details["damage"] == "1"
    assert fought.stats.hp == hero.stats.hp - 1
    assert 1 <= int(details["xp_awarded"]) <= 25


def test_fatal_dungeon_fight_records_permanent_death_and_zero_xp() -> None:
    world = _starting_world(CharacterClass.WARRIOR)
    hero = world.adventurers["hero"]
    fragile = replace(
        hero,
        location_id="vault-1",
        stats=replace(hero.stats, hp=1),
    )
    world = replace(world, adventurers={fragile.id: fragile})

    result = SimulationScheduler(seed=29).run_hour(
        world,
        (ActionIntent(fragile.id, ActionKind.FIGHT),),
    )

    fallen = result.final_state.adventurers[fragile.id]
    details = _details(result.events[0])
    assert fallen.alive is False
    assert fallen.death_tick == 0
    assert fallen.death_cause == "vault-1-guardian"
    assert details["life_event"] == "story-end-permanent-death"
    assert details["xp_awarded"] == "0"


def test_dungeon_hazard_can_cause_permanent_death() -> None:
    world = _starting_world(CharacterClass.MAGE)
    hero = world.adventurers["hero"]
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


def test_scheduler_does_not_apply_movement_specific_companion_events() -> None:
    world = _starting_world(CharacterClass.ARCHER)

    moved = SimulationScheduler(seed=5).run_hour(
        world,
        (ActionIntent("hero", ActionKind.MOVE, target_location_id="mossreach"),),
    )

    party = moved.final_state.party
    assert party is not None
    assert party.member_ids == ("hero",)
    assert "rhea-vale" in moved.final_state.adventurers
    assert "life_event" not in _details(moved.events[0])
