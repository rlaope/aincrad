from __future__ import annotations

from dataclasses import replace

from .models import MAX_LEVEL as _MAX_LEVEL
from .models import XP_CURVE as _XP_CURVE
from .models import Activity, Adventurer, PartyState, Stats

MAX_LEVEL = _MAX_LEVEL
XP_CURVE = _XP_CURVE


def start_party(selected_hero_id: str, *, cap: int) -> PartyState:
    """Start a party containing exactly one explicitly selected hero."""
    return PartyState(selected_hero_id, (selected_hero_id,), cap)


def recruit(party: PartyState, adventurer_id: str) -> PartyState:
    """Append a new member in recruitment order without exceeding the cap."""
    if not adventurer_id:
        raise ValueError("adventurer id cannot be empty")
    if adventurer_id in party.member_ids:
        return party
    if len(party.member_ids) >= party.cap:
        raise ValueError("party cap has been reached")
    return replace(party, member_ids=(*party.member_ids, adventurer_id))


def remove(party: PartyState, adventurer_id: str) -> PartyState:
    """Remove a member while preserving order and the selected hero."""
    if adventurer_id == party.selected_hero_id:
        raise ValueError("selected hero cannot be removed")
    if adventurer_id not in party.member_ids:
        return party
    remaining = tuple(member for member in party.member_ids if member != adventurer_id)
    return replace(party, member_ids=remaining)


def exp_to_next_level(level: int) -> int:
    """Return the XP requirement associated with a level from 1 through 100."""
    if not 1 <= level <= MAX_LEVEL:
        raise ValueError(f"level must be between 1 and {MAX_LEVEL}")
    return XP_CURVE[level - 1]


def award_exp(adventurer: Adventurer, amount: int) -> Adventurer:
    """Award non-negative XP, applying every level-up and the level-100 cap."""
    if amount < 0:
        raise ValueError("experience awards cannot be negative")
    if not adventurer.alive:
        raise ValueError("dead adventurers cannot progress")
    if adventurer.level == MAX_LEVEL or amount == 0:
        return adventurer

    level = adventurer.level
    exp = adventurer.exp + amount
    while level < MAX_LEVEL and exp >= exp_to_next_level(level):
        exp -= exp_to_next_level(level)
        level += 1

    if level == MAX_LEVEL:
        exp = 0
    return replace(adventurer, level=level, exp=exp)


def mark_dead(adventurer: Adventurer, *, tick: int, cause: str | None = None) -> Adventurer:
    """Permanently mark an adventurer dead while preserving the first death record."""
    if not adventurer.alive:
        return adventurer
    return replace(
        adventurer,
        stats=replace(adventurer.stats, hp=0),
        activity=Activity.IDLE,
        alive=False,
        death_tick=tick,
        death_cause=cause,
    )


def apply_damage(
    adventurer: Adventurer,
    amount: int,
    *,
    tick: int,
    cause: str | None = "hp_depleted",
) -> Adventurer:
    """Apply bounded HP damage and make zero HP a permanent death."""
    if amount < 0:
        raise ValueError("damage cannot be negative")
    if not adventurer.alive:
        return adventurer

    hp = max(0, adventurer.stats.hp - amount)
    damaged = replace(adventurer, stats=replace(adventurer.stats, hp=hp))
    if hp == 0:
        return mark_dead(damaged, tick=tick, cause=cause)
    return damaged


def restore_stats(adventurer: Adventurer, *, hp: int = 0, mp: int = 0) -> Adventurer:
    """Restore HP and MP without exceeding either maximum."""
    if hp < 0 or mp < 0:
        raise ValueError("restoration cannot be negative")
    if not adventurer.alive:
        raise ValueError("dead adventurers cannot restore stats")
    if hp == 0 and mp == 0:
        return adventurer

    stats = adventurer.stats
    restored = Stats(
        hp=min(stats.max_hp, stats.hp + hp),
        max_hp=stats.max_hp,
        mp=min(stats.max_mp, stats.mp + mp),
        max_mp=stats.max_mp,
    )
    return replace(adventurer, stats=restored)


def spend_mp(adventurer: Adventurer, amount: int) -> Adventurer:
    """Spend available MP without allowing an underflow."""
    if amount < 0:
        raise ValueError("MP cost cannot be negative")
    if not adventurer.alive:
        raise ValueError("dead adventurers cannot spend MP")
    if amount > adventurer.stats.mp:
        raise ValueError("insufficient MP")
    if amount == 0:
        return adventurer
    return replace(adventurer, stats=replace(adventurer.stats, mp=adventurer.stats.mp - amount))
