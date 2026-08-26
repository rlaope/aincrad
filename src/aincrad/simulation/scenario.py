from __future__ import annotations

from aincrad.domain import (
    Activity,
    Adventurer,
    Location,
    LocationKind,
    Stats,
    WorldState,
)


def create_initial_world() -> WorldState:
    locations = {
        "emberfall": Location(
            "emberfall",
            "Emberfall",
            LocationKind.TOWN,
            (
                "emberfall-shop",
                "emberfall-inn",
                "emberfall-quest-hall",
                "emberfall-plaza",
                "emberfall-tavern",
                "mossreach",
            ),
        ),
        "emberfall-shop": Location(
            "emberfall-shop", "Cinderstock Exchange", LocationKind.TOWN, ("emberfall",)
        ),
        "emberfall-inn": Location(
            "emberfall-inn", "The Quiet Wick", LocationKind.TOWN, ("emberfall",)
        ),
        "emberfall-quest-hall": Location(
            "emberfall-quest-hall", "Wayfinder Assembly", LocationKind.TOWN, ("emberfall",)
        ),
        "emberfall-plaza": Location(
            "emberfall-plaza", "Prismwake Square", LocationKind.TOWN, ("emberfall",)
        ),
        "emberfall-tavern": Location(
            "emberfall-tavern", "The Copper Comet", LocationKind.TOWN, ("emberfall",)
        ),
        "mossreach": Location(
            "mossreach",
            "Mossreach Wilds",
            LocationKind.HUNTING_GROUND,
            ("emberfall", "vault-1"),
        ),
    }
    dungeon_names = (
        "Echo Gallery",
        "Flooded Archive",
        "Nightglass Causeway",
        "Hushed Reservoir",
        "Sable Orrery",
        "Gloam Workshop",
        "Ashen Conservatory",
        "Inverted Belfry",
        "Crownless Antechamber",
        "Chamber of the Null Cartographer",
    )
    for stage, name in enumerate(dungeon_names, start=1):
        previous = "mossreach" if stage == 1 else f"vault-{stage - 1}"
        connections = (previous,) if stage == 10 else (previous, f"vault-{stage + 1}")
        locations[f"vault-{stage}"] = Location(
            f"vault-{stage}",
            name,
            LocationKind.DUNGEON,
            connections,
            stage=stage,
            is_boss_room=stage == 10,
            boss_id="null-cartographer" if stage == 10 else None,
            transition_id="aurora-lift-floor-2" if stage == 10 else None,
            next_world_floor=2 if stage == 10 else None,
        )
    adventurers = {
        "rhea-vale": Adventurer(
            "rhea-vale",
            "Rhea Vale",
            "emberfall",
            Stats(hp=24, max_hp=24, mp=6, max_mp=6),
            Activity.IDLE,
            gold=5,
        ),
        "tovin-reed": Adventurer(
            "tovin-reed",
            "Tovin Reed",
            "emberfall",
            Stats(hp=18, max_hp=18, mp=10, max_mp=10),
            Activity.IDLE,
            gold=5,
        ),
        "sable-quill": Adventurer(
            "sable-quill",
            "Sable Quill",
            "emberfall",
            Stats(hp=14, max_hp=14, mp=18, max_mp=18),
            Activity.IDLE,
            gold=5,
        ),
    }
    return WorldState(tick=0, locations=locations, adventurers=adventurers)
