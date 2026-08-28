from pathlib import Path

from aincrad.cli import _starting_world
from aincrad.content import load_packaged_world_fixture
from aincrad.content.events import LIFE_EVENT_CATALOG, LifeEventType
from aincrad.domain import CharacterClass
from aincrad.simulation.scenario import create_initial_world

ROOT = Path(__file__).parents[2]

def test_initial_scenario_exposes_the_three_fixture_candidate_adventurers() -> None:
    world = create_initial_world()

    assert set(world.adventurers) == {"rhea-vale", "tovin-reed", "sable-quill"}
    assert {
        "emberfall",
        "emberfall-shop",
        "emberfall-inn",
        "emberfall-quest-hall",
        "emberfall-plaza",
        "emberfall-tavern",
        "mossreach",
    }.issubset(world.locations)
    dungeon = [world.locations[f"vault-{depth}"] for depth in range(1, 11)]
    assert [location.stage for location in dungeon] == list(range(1, 11))
    assert dungeon[-1].is_boss_room is True
    assert dungeon[-1].next_world_floor == 2


def test_live_start_keeps_candidates_but_party_contains_only_stable_hero() -> None:
    world = _starting_world(CharacterClass.WARRIOR)

    assert set(world.adventurers) == {"hero", "rhea-vale", "tovin-reed", "sable-quill"}
    assert world.party is not None
    assert world.party.selected_hero_id == "hero"
    assert world.party.member_ids == ("hero",)


def test_every_declared_location_connection_exists() -> None:
    world = create_initial_world()

    for location in world.locations.values():
        assert set(location.connections).issubset(world.locations)


def test_all_five_emberfall_facilities_are_reachable_without_self_edges() -> None:
    world = create_initial_world()
    facility_ids = {
        "emberfall-shop",
        "emberfall-inn",
        "emberfall-quest-hall",
        "emberfall-plaza",
        "emberfall-tavern",
    }

    assert facility_ids.issubset(world.locations["emberfall"].connections)
    for facility_id in facility_ids:
        assert world.locations[facility_id].connections == ("emberfall",)
        assert facility_id not in world.locations[facility_id].connections


def test_runtime_location_names_match_the_canonical_fixture() -> None:
    fixture = load_packaged_world_fixture()
    world = create_initial_world()
    town = fixture["towns"][0]
    fixture_locations = [
        town,
        *town["facilities"],
        *fixture["hunting_grounds"],
        *fixture["dungeons"][0]["floors"],
    ]

    assert {
        location["id"]: location["name"] for location in fixture_locations
    } == {location.id: location.name for location in world.locations.values()}


def test_runtime_vault_completion_matches_fixture_and_catalog() -> None:
    fixture = load_packaged_world_fixture()
    completion = fixture["dungeons"][0]["floors"][-1]["completion"]
    vault = create_initial_world().locations["vault-10"]
    boss_clear = next(
        event
        for event in LIFE_EVENT_CATALOG
        if event.event_type is LifeEventType.BOSS_ROOM_CLEAR
    )
    transition = next(
        event
        for event in LIFE_EVENT_CATALOG
        if event.event_type is LifeEventType.NEXT_FLOOR_TRANSITION
    )

    assert vault.boss_id == completion["boss_id"] == boss_clear.triggers["boss_id"]
    assert (
        vault.transition_id
        == completion["transition_id"]
        == transition.effects["transition_id"]
    )
    assert (
        vault.next_world_floor
        == completion["next_world_floor"]
        == transition.effects["next_world_floor"]
        == 2
    )


def test_architecture_distinguishes_candidates_from_the_selected_live_hero() -> None:
    architecture = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")

    assert "후보 모험가 3명" in architecture
    assert "선택된 영웅 1명" in architecture
    assert "세 모험가가 각각" not in architecture
