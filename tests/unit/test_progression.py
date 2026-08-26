from dataclasses import replace

import pytest

from aincrad.domain.models import Activity, Adventurer, CharacterClass, Stats
from aincrad.domain.progression import (
    MAX_LEVEL,
    XP_CURVE,
    PartyState,
    apply_damage,
    award_exp,
    exp_to_next_level,
    mark_dead,
    recruit,
    remove,
    restore_stats,
    spend_mp,
    start_party,
)


def hero(
    *,
    stats: Stats | None = None,
    activity: Activity = Activity.IDLE,
    level: int = 1,
    exp: int = 0,
    alive: bool = True,
    death_tick: int | None = None,
    death_cause: str | None = None,
) -> Adventurer:
    return Adventurer(
        id="hero",
        name="Hero",
        location_id="town",
        stats=stats or Stats(hp=10, max_hp=10, mp=5, max_mp=5),
        activity=activity,
        level=level,
        exp=exp,
        alive=alive,
        death_tick=death_tick,
        death_cause=death_cause,
    )


def test_character_class_has_four_stable_values() -> None:
    assert tuple(CharacterClass) == (
        CharacterClass.WARRIOR,
        CharacterClass.ARCHER,
        CharacterClass.MAGE,
        CharacterClass.TANK,
    )
    assert tuple(member.value for member in CharacterClass) == (
        "warrior",
        "archer",
        "mage",
        "tank",
    )


def test_existing_adventurer_constructor_gets_safe_progression_defaults() -> None:
    adventurer = hero()

    assert adventurer.character_class is CharacterClass.WARRIOR
    assert adventurer.level == 1
    assert adventurer.exp == 0
    assert adventurer.alive is True
    assert adventurer.death_tick is None
    assert adventurer.death_cause is None
    assert adventurer.can_act is True


def test_adventurer_rejects_invalid_progression_and_death_metadata() -> None:
    with pytest.raises(ValueError, match="level"):
        hero(level=0)
    with pytest.raises(ValueError, match="experience"):
        hero(exp=-1)
    with pytest.raises(ValueError, match="death metadata"):
        hero(alive=True, death_tick=3)
    with pytest.raises(ValueError, match="death tick"):
        hero(alive=False)
    with pytest.raises(ValueError, match="zero hp"):
        hero(alive=False, death_tick=3)


def test_dead_adventurer_cannot_be_given_an_active_activity() -> None:
    dead = hero(
        stats=Stats(hp=0, max_hp=10, mp=0, max_mp=5),
        alive=False,
        death_tick=7,
        death_cause="fallen_in_battle",
    )

    assert dead.can_act is False
    with pytest.raises(ValueError, match="cannot act"):
        replace(dead, activity=Activity.MOVING)


def test_xp_curve_is_explicit_slow_and_strictly_increasing_through_level_100() -> None:
    assert MAX_LEVEL == 100
    assert len(XP_CURVE) == MAX_LEVEL
    assert XP_CURVE[0] >= 100
    assert all(
        later > earlier for earlier, later in zip(XP_CURVE, XP_CURVE[1:], strict=False)
    )
    assert XP_CURVE[-1] >= XP_CURVE[0] * 50
    assert exp_to_next_level(1) == XP_CURVE[0]
    assert exp_to_next_level(MAX_LEVEL) == XP_CURVE[-1]


def test_award_exp_handles_multiple_levels_and_keeps_remainder() -> None:
    amount = exp_to_next_level(1) + exp_to_next_level(2) + 17

    progressed = award_exp(hero(), amount)

    assert progressed.level == 3
    assert progressed.exp == 17


def test_award_exp_has_a_hard_level_cap() -> None:
    capped = award_exp(hero(level=99), exp_to_next_level(99) + 10**9)

    assert capped.level == MAX_LEVEL
    assert capped.exp == 0
    assert award_exp(capped, 1) is capped


def test_award_exp_rejects_negative_awards_and_dead_progression() -> None:
    with pytest.raises(ValueError, match="negative"):
        award_exp(hero(), -1)

    dead = hero(
        stats=Stats(hp=0, max_hp=10, mp=0, max_mp=5),
        alive=False,
        death_tick=2,
    )
    with pytest.raises(ValueError, match="dead"):
        award_exp(dead, 100)


def test_hp_and_mp_changes_stay_within_closed_bounds() -> None:
    damaged = apply_damage(hero(), 10_000, tick=4, cause="dragon")

    assert damaged.stats.hp == 0
    assert damaged.alive is False
    assert damaged.death_tick == 4
    assert damaged.death_cause == "dragon"

    restored = restore_stats(hero(stats=Stats(7, 10, 3, 5)), hp=99, mp=99)
    assert restored.stats == Stats(hp=10, max_hp=10, mp=5, max_mp=5)

    spent = spend_mp(restored, 5)
    assert spent.stats.mp == 0
    with pytest.raises(ValueError, match="insufficient"):
        spend_mp(spent, 1)


def test_death_is_idempotent_and_permanent() -> None:
    dead = mark_dead(hero(), tick=8, cause="boss")

    assert mark_dead(dead, tick=9, cause="later") is dead
    with pytest.raises(ValueError, match="dead"):
        restore_stats(dead, hp=1)
    with pytest.raises(ValueError, match="dead"):
        spend_mp(dead, 1)


def test_stat_operations_reject_negative_amounts() -> None:
    with pytest.raises(ValueError, match="negative"):
        apply_damage(hero(), -1, tick=0)
    with pytest.raises(ValueError, match="negative"):
        restore_stats(hero(), hp=-1)
    with pytest.raises(ValueError, match="negative"):
        spend_mp(hero(), -1)


def test_party_starts_with_exactly_the_selected_hero() -> None:
    party = start_party("hero", cap=3)

    assert party == PartyState(selected_hero_id="hero", member_ids=("hero",), cap=3)


def test_party_recruitment_is_ordered_idempotent_and_capped() -> None:
    party = start_party("hero", cap=3)
    party = recruit(party, "mage")
    party = recruit(party, "tank")

    assert party.member_ids == ("hero", "mage", "tank")
    assert recruit(party, "mage") is party
    with pytest.raises(ValueError, match="cap"):
        recruit(party, "archer")


def test_party_removal_is_deterministic_and_preserves_selected_hero() -> None:
    party = recruit(recruit(start_party("hero", cap=4), "mage"), "tank")

    assert remove(party, "mage").member_ids == ("hero", "tank")
    assert remove(party, "missing") is party
    with pytest.raises(ValueError, match="selected hero"):
        remove(party, "hero")


def test_party_state_rejects_invalid_caps_duplicates_and_missing_hero() -> None:
    with pytest.raises(ValueError, match="positive"):
        start_party("hero", cap=0)
    with pytest.raises(ValueError, match="unique"):
        PartyState("hero", ("hero", "hero"), 3)
    with pytest.raises(ValueError, match="selected hero"):
        PartyState("hero", ("mage",), 3)
