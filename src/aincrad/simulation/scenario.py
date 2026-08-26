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
            "emberfall", "Emberfall", LocationKind.TOWN, ("mossreach",)
        ),
        "mossreach": Location(
            "mossreach",
            "Mossreach Wilds",
            LocationKind.HUNTING_GROUND,
            ("emberfall", "vault-1"),
        ),
        "vault-1": Location(
            "vault-1", "Echo Gallery", LocationKind.DUNGEON, ("mossreach", "vault-2")
        ),
        "vault-2": Location(
            "vault-2", "Flooded Archive", LocationKind.DUNGEON, ("vault-1", "vault-3")
        ),
        "vault-3": Location(
            "vault-3", "Nightglass Crucible", LocationKind.DUNGEON, ("vault-2",)
        ),
    }
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
