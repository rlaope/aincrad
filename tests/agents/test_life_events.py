from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from aincrad.content.events import (
    LIFE_EVENT_CATALOG,
    LifeEventCatalogError,
    LifeEventTemplate,
    LifeEventType,
    validate_life_event_catalog,
)
from aincrad.content.fixtures import load_world_fixture

ROOT = Path(__file__).parents[2]
FIXTURE = ROOT / "fixtures" / "glassfrontier_world.json"


def test_catalog_contains_one_typed_template_for_each_life_event() -> None:
    expected_types = {
        LifeEventType.COMPANION_RECRUITMENT,
        LifeEventType.COMPANION_DEPARTURE,
        LifeEventType.PERMANENT_CHARACTER_DEATH,
        LifeEventType.QUEST_OFFER,
        LifeEventType.QUEST_COMPLETION,
        LifeEventType.BOSS_ROOM_CLEAR,
        LifeEventType.NEXT_FLOOR_TRANSITION,
    }

    assert isinstance(LIFE_EVENT_CATALOG, tuple)
    assert {template.event_type for template in LIFE_EVENT_CATALOG} == expected_types
    assert all(isinstance(template, LifeEventTemplate) for template in LIFE_EVENT_CATALOG)
    assert all(template.id for template in LIFE_EVENT_CATALOG)
    assert all(template.triggers for template in LIFE_EVENT_CATALOG)
    assert all(template.display_text_ko for template in LIFE_EVENT_CATALOG)
    assert all(template.effects for template in LIFE_EVENT_CATALOG)
    assert len({template.id for template in LIFE_EVENT_CATALOG}) == len(LIFE_EVENT_CATALOG)
    assert validate_life_event_catalog(LIFE_EVENT_CATALOG) == LIFE_EVENT_CATALOG


def test_companion_events_identify_companion_and_party_effects() -> None:
    companion_events = {
        template.event_type: template
        for template in LIFE_EVENT_CATALOG
        if template.event_type
        in {LifeEventType.COMPANION_RECRUITMENT, LifeEventType.COMPANION_DEPARTURE}
    }

    assert companion_events[LifeEventType.COMPANION_RECRUITMENT].effects == {
        "companion_id": "rhea-vale",
        "party_action": "add",
    }
    assert companion_events[LifeEventType.COMPANION_DEPARTURE].effects == {
        "companion_id": "rhea-vale",
        "party_action": "remove",
    }
    assert companion_events[LifeEventType.COMPANION_DEPARTURE].triggers[
        "companion_id"
    ] == "rhea-vale"


def test_permanent_death_ends_the_character_story() -> None:
    death = next(
        template
        for template in LIFE_EVENT_CATALOG
        if template.event_type is LifeEventType.PERMANENT_CHARACTER_DEATH
    )

    assert death.effects["character_status"] == "dead"
    assert death.effects["story_state"] == "ended"


def test_validator_rejects_duplicate_ids() -> None:
    duplicate = LIFE_EVENT_CATALOG[0]

    with pytest.raises(LifeEventCatalogError, match="duplicate event id"):
        validate_life_event_catalog((*LIFE_EVENT_CATALOG, duplicate))


def test_validator_rejects_unsupported_event_type() -> None:
    unsupported = LifeEventTemplate(
        id="weather-change",
        event_type=cast(LifeEventType, "weather_change"),
        triggers={"hour": 12},
        display_text_ko="비가 내립니다.",
        effects={"weather": "rain"},
    )

    with pytest.raises(LifeEventCatalogError, match="unsupported event type"):
        validate_life_event_catalog((unsupported,))


@pytest.mark.parametrize(
    ("template", "field"),
    [
        (replace(LIFE_EVENT_CATALOG[0], triggers={}), "triggers"),
        (replace(LIFE_EVENT_CATALOG[0], effects={}), "effects"),
    ],
)
def test_validator_rejects_missing_trigger_or_effect_data(
    template: LifeEventTemplate, field: str
) -> None:
    with pytest.raises(LifeEventCatalogError, match=field):
        validate_life_event_catalog((template,))


def test_validator_rejects_next_floor_transition_without_boss_clear() -> None:
    transition = next(
        template
        for template in LIFE_EVENT_CATALOG
        if template.event_type is LifeEventType.NEXT_FLOOR_TRANSITION
    )
    invalid_transition = replace(transition, triggers={"current_world_floor": 1})
    catalog = tuple(
        invalid_transition if template is transition else template
        for template in LIFE_EVENT_CATALOG
    )

    with pytest.raises(LifeEventCatalogError, match="boss clear"):
        validate_life_event_catalog(catalog)


@pytest.mark.parametrize(
    "template",
    [
        replace(LIFE_EVENT_CATALOG[0], id=""),
        replace(LIFE_EVENT_CATALOG[0], id="bad\nidentifier"),
        replace(LIFE_EVENT_CATALOG[0], display_text_ko="English only."),
        replace(LIFE_EVENT_CATALOG[0], display_text_ko="한국어\x1b[31m"),
    ],
)
def test_validator_rejects_unsafe_ids_and_non_korean_or_control_text(
    template: LifeEventTemplate,
) -> None:
    with pytest.raises(LifeEventCatalogError, match="id|display_text_ko"):
        validate_life_event_catalog((template,))


def test_validator_checks_every_id_occurrence_in_triggers_and_effects() -> None:
    invalid_completion = replace(
        LIFE_EVENT_CATALOG[4],
        effects={"quest_id": "bad\nquest", "quest_state": "completed"},
    )
    catalog = (*LIFE_EVENT_CATALOG[:4], invalid_completion, *LIFE_EVENT_CATALOG[5:])

    with pytest.raises(LifeEventCatalogError, match="quest_id"):
        validate_life_event_catalog(catalog)


@pytest.mark.parametrize(
    "template",
    [
        replace(LIFE_EVENT_CATALOG[0], triggers={"quest_id": "echoes-at-emberfall"}),
        replace(
            LIFE_EVENT_CATALOG[0],
            triggers={"quest_id": "echoes-at-emberfall", "relationship_at_least": True},
        ),
        replace(
            LIFE_EVENT_CATALOG[0],
            effects={"companion_id": "rhea-companion", "party_action": "invite"},
        ),
        replace(
            LIFE_EVENT_CATALOG[2],
            triggers={"character_hp_at_most": "0", "permadeath_enabled": True},
        ),
        replace(
            LIFE_EVENT_CATALOG[2],
            triggers={"character_hp_at_most": 1, "permadeath_enabled": True},
        ),
        replace(
            LIFE_EVENT_CATALOG[3],
            triggers={"location_id": "emberfall-quest-hall", "quest_available": 1},
        ),
        replace(
            LIFE_EVENT_CATALOG[4],
            effects={"quest_id": "echoes-at-emberfall", "quest_state": "done"},
        ),
        replace(
            LIFE_EVENT_CATALOG[5],
            triggers={"boss_id": "null-cartographer", "boss_hp_at_most": 1},
        ),
        replace(
            LIFE_EVENT_CATALOG[5],
            effects={"boss_room_id": "vault-10", "boss_cleared": 1},
        ),
        replace(
            LIFE_EVENT_CATALOG[6],
            effects={"transition_id": "aurora-lift-floor-2", "next_world_floor": True},
        ),
    ],
)
def test_validator_enforces_event_specific_trigger_and_effect_schema(
    template: LifeEventTemplate,
) -> None:
    with pytest.raises(LifeEventCatalogError, match="trigger|effect|party_action"):
        validate_life_event_catalog((template,))


def test_validator_rejects_incoherent_quest_and_companion_references() -> None:
    recruitment = replace(
        LIFE_EVENT_CATALOG[0],
        triggers={"quest_id": "missing-quest", "relationship_at_least": 60},
    )
    departure = replace(
        LIFE_EVENT_CATALOG[1],
        triggers={"companion_id": "other", "relationship_below": 20},
        effects={"companion_id": "other", "party_action": "remove"},
    )

    with pytest.raises(LifeEventCatalogError, match="quest reference"):
        validate_life_event_catalog((recruitment, *LIFE_EVENT_CATALOG[1:]))
    with pytest.raises(LifeEventCatalogError, match="companion reference"):
        validate_life_event_catalog(
            (LIFE_EVENT_CATALOG[0], departure, *LIFE_EVENT_CATALOG[2:])
        )


def test_template_deeply_copies_and_freezes_nested_trigger_and_effect_values() -> None:
    nested_trigger: dict[str, Any] = {"outer": {"items": ["first"]}}
    nested_effect: dict[str, Any] = {"outer": [{"state": "original"}]}
    template = LifeEventTemplate(
        id="deep-freeze-proof",
        event_type=LifeEventType.QUEST_OFFER,
        triggers=nested_trigger,
        display_text_ko="깊은 불변성을 검증합니다.",
        effects=nested_effect,
    )

    nested_trigger["outer"]["items"].append("mutated")
    nested_effect["outer"][0]["state"] = "mutated"
    frozen_trigger = cast(Any, template.triggers["outer"])
    frozen_effect = cast(Any, template.effects["outer"])

    assert frozen_trigger["items"] == ("first",)
    assert frozen_effect[0]["state"] == "original"
    with pytest.raises(TypeError):
        frozen_trigger["items"] = ()
    with pytest.raises(TypeError):
        frozen_effect[0]["state"] = "changed"


def test_catalog_boss_transition_references_match_validated_world_fixture() -> None:
    world = load_world_fixture(FIXTURE)
    boss_clear = next(
        event for event in LIFE_EVENT_CATALOG if event.event_type is LifeEventType.BOSS_ROOM_CLEAR
    )
    transition = next(
        event
        for event in LIFE_EVENT_CATALOG
        if event.event_type is LifeEventType.NEXT_FLOOR_TRANSITION
    )

    assert boss_clear.triggers["boss_id"] == "null-cartographer"
    assert boss_clear.effects["boss_room_id"] == "vault-10"
    assert transition.effects["transition_id"] == "aurora-lift-floor-2"
    assert validate_life_event_catalog(LIFE_EVENT_CATALOG, world=world) == LIFE_EVENT_CATALOG


@pytest.mark.parametrize(
    ("event_index", "triggers", "effects"),
    [
        (
            5,
            {"boss_id": "wrong-boss", "boss_hp_at_most": 0},
            {"boss_room_id": "vault-10", "boss_cleared": True},
        ),
        (
            5,
            {"boss_id": "null-cartographer", "boss_hp_at_most": 0},
            {"boss_room_id": "wrong-room", "boss_cleared": True},
        ),
        (
            6,
            {"boss_clear_event_id": "boss-clear-starless-vault"},
            {"transition_id": "wrong-transition", "next_world_floor": 2},
        ),
    ],
)
def test_validator_rejects_catalog_boss_metadata_that_disagrees_with_world(
    event_index: int, triggers: dict[str, object], effects: dict[str, object]
) -> None:
    world = load_world_fixture(FIXTURE)
    invalid = replace(LIFE_EVENT_CATALOG[event_index], triggers=triggers, effects=effects)
    catalog = tuple(
        invalid if index == event_index else event
        for index, event in enumerate(LIFE_EVENT_CATALOG)
    )

    with pytest.raises(LifeEventCatalogError, match="world fixture"):
        validate_life_event_catalog(catalog, world=world)
