import pytest

from aincrad.domain.models import Adventurer, Stats
from aincrad.domain.progression import (
    MAX_LEVEL,
    XP_CURVE,
    PartyState,
    apply_damage,
    award_exp,
    recruit,
    remove,
    restore_stats,
    start_party,
)


def hero(*, level: int = 1, exp: int = 0) -> Adventurer:
    return Adventurer(
        id="hero",
        name="Hero",
        location_id="town",
        stats=Stats(hp=37, max_hp=100, mp=11, max_mp=40),
        level=level,
        exp=exp,
    )


def test_exp_remainder_must_be_canonical_for_its_level() -> None:
    for level, requirement in enumerate(XP_CURVE[:-1], start=1):
        with pytest.raises(ValueError, match="experience"):
            hero(level=level, exp=requirement)

    with pytest.raises(ValueError, match="experience"):
        hero(level=MAX_LEVEL, exp=1)


def test_awards_preserve_level_and_exp_bounds_for_many_inputs() -> None:
    amounts = (0, 1, 124, 125, 10_000, 1_000_000, 10**12)
    for level in range(1, MAX_LEVEL + 1):
        for amount in amounts:
            progressed = award_exp(hero(level=level), amount)
            assert level <= progressed.level <= MAX_LEVEL
            if progressed.level == MAX_LEVEL:
                assert progressed.exp == 0
            else:
                assert 0 <= progressed.exp < XP_CURVE[progressed.level - 1]


def test_stat_transitions_never_escape_hp_or_mp_bounds() -> None:
    for amount in (0, 1, 37, 100, 10**9):
        damaged = apply_damage(hero(), amount, tick=amount)
        assert 0 <= damaged.stats.hp <= damaged.stats.max_hp

        restored = restore_stats(hero(), hp=amount, mp=amount)
        assert 0 <= restored.stats.hp <= restored.stats.max_hp
        assert 0 <= restored.stats.mp <= restored.stats.max_mp


def test_party_operations_are_deterministic_and_never_exceed_cap() -> None:
    recruits = ("a", "b", "a", "c")
    first = start_party("hero", cap=4)
    second = start_party("hero", cap=4)
    for member_id in recruits:
        first = recruit(first, member_id)
        second = recruit(second, member_id)

    assert first == second == PartyState("hero", ("hero", "a", "b", "c"), 4)
    assert len(first.member_ids) <= first.cap

    for member_id in ("b", "missing", "a"):
        first = remove(first, member_id)
        second = remove(second, member_id)
    assert first == second
    assert first.member_ids == ("hero", "c")
