from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from aincrad.domain import StoryIntent as ExportedStoryIntent
from aincrad.domain.story import (
    StoryCharacterView,
    StoryIntent,
    StoryIntentKind,
    StoryPerception,
    StoryQuestView,
    StoryRecentEventView,
    StoryRelationshipView,
    build_story_perception,
    story_candidate_id,
)


def test_story_intent_kind_is_closed_and_versioned() -> None:
    assert ExportedStoryIntent is StoryIntent
    assert StoryIntentKind.VERSION == 1
    assert tuple(kind.value for kind in StoryIntentKind) == (
        "no_op",
        "offer_quest",
        "complete_quest",
        "recruit_companion",
        "depart_companion",
    )
    with pytest.raises(ValueError):
        StoryIntentKind("invent_twist")


def test_story_intent_is_immutable_and_has_deterministic_candidate_id() -> None:
    candidate_id = story_candidate_id(
        kind=StoryIntentKind.OFFER_QUEST,
        tick=7,
        hero_id="hero-1",
        reason_code="quest.available",
        quest_id="quest-1",
    )
    intent = StoryIntent(
        version=1,
        candidate_id=candidate_id,
        kind=StoryIntentKind.OFFER_QUEST,
        tick=7,
        hero_id="hero-1",
        reason_code="quest.available",
        quest_id="quest-1",
    )

    assert candidate_id == story_candidate_id(
        kind=StoryIntentKind.OFFER_QUEST,
        tick=7,
        hero_id="hero-1",
        reason_code="quest.available",
        quest_id="quest-1",
    )
    assert len(candidate_id) == 64
    with pytest.raises(FrozenInstanceError):
        intent.tick = 8  # type: ignore[misc]


def _intent(
    kind: StoryIntentKind,
    *,
    quest_id: str | None = None,
    companion_id: str | None = None,
    version: int = 1,
    hero_id: str = "hero-1",
    reason_code: str = "story.allowed",
) -> StoryIntent:
    candidate_id = story_candidate_id(
        version=1,
        kind=kind,
        tick=3,
        hero_id=hero_id,
        reason_code=reason_code,
        quest_id=quest_id,
        companion_id=companion_id,
    )
    return StoryIntent(
        version=version,
        candidate_id=candidate_id,
        kind=kind,
        tick=3,
        hero_id=hero_id,
        reason_code=reason_code,
        quest_id=quest_id,
        companion_id=companion_id,
    )


@pytest.mark.parametrize(
    ("kind", "quest_id", "companion_id"),
    [
        (StoryIntentKind.NO_OP, "quest-1", None),
        (StoryIntentKind.NO_OP, None, "companion-1"),
        (StoryIntentKind.OFFER_QUEST, None, None),
        (StoryIntentKind.COMPLETE_QUEST, None, None),
        (StoryIntentKind.RECRUIT_COMPANION, None, None),
        (StoryIntentKind.DEPART_COMPANION, None, None),
        (StoryIntentKind.OFFER_QUEST, "quest-1", "companion-1"),
    ],
)
def test_story_intent_rejects_wrong_fields_for_kind(
    kind: StoryIntentKind, quest_id: str | None, companion_id: str | None
) -> None:
    with pytest.raises(ValueError):
        _intent(kind, quest_id=quest_id, companion_id=companion_id)


def test_candidate_id_helper_rejects_forbidden_kind_fields() -> None:
    with pytest.raises(ValueError):
        story_candidate_id(
            kind=StoryIntentKind.NO_OP,
            tick=0,
            hero_id="hero-1",
            reason_code="idle.safe",
            quest_id="quest-1",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [("hero_id", "../hero"), ("hero_id", "Hero One"), ("reason_code", "unsafe\nreason")],
)
def test_story_intent_rejects_noncanonical_identifiers(field: str, value: str) -> None:
    kwargs = {field: value}
    with pytest.raises(ValueError):
        _intent(StoryIntentKind.NO_OP, **kwargs)


@pytest.mark.parametrize("version", [0, 2, True])
def test_story_intent_rejects_unknown_or_non_integer_version(version: int) -> None:
    with pytest.raises(ValueError):
        _intent(StoryIntentKind.NO_OP, version=version)


def test_story_intent_rejects_string_kind_control() -> None:
    with pytest.raises(TypeError):
        StoryIntent(
            version=1,
            candidate_id="0" * 64,
            kind="no_op",  # type: ignore[arg-type]
            tick=0,
            hero_id="hero-1",
            reason_code="idle.safe",
        )


def test_story_perception_views_are_frozen_and_tuple_backed() -> None:
    perception = StoryPerception(
        version=1,
        tick=9,
        hero_id="hero-1",
        characters=(StoryCharacterView("companion-1", (("alive", True),)),),
        quests=(StoryQuestView("quest-1", (("status", "active"),)),),
        relationships=(
            StoryRelationshipView("hero-1", "companion-1", (("trust", 3),)),
        ),
        recent_events=(
            StoryRecentEventView("event-1", 8, "quest_offered", (("quest_id", "quest-1"),)),
        ),
    )

    assert isinstance(perception.characters, tuple)
    assert isinstance(perception.characters[0].fields, tuple)
    with pytest.raises(FrozenInstanceError):
        perception.tick = 10  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        perception.characters[0].character_id = "changed"  # type: ignore[misc]


def test_story_perception_builder_detaches_nested_source_mappings() -> None:
    character = {"id": "companion-1", "tags": ["mage"], "stats": {"hp": 10}}
    quest = {"id": "quest-1", "status": "active"}
    relationship = {"source_id": "hero-1", "target_id": "companion-1", "trust": 3}
    event = {"id": "event-1", "tick": 8, "kind": "quest_offered", "subjects": ["quest-1"]}

    perception = build_story_perception(
        version=1,
        tick=9,
        hero_id="hero-1",
        characters=[character],
        quests=[quest],
        relationships=[relationship],
        recent_events=[event],
    )
    character["tags"].append("mutated")  # type: ignore[union-attr]
    character["stats"]["hp"] = 0  # type: ignore[index]
    quest["status"] = "mutated"
    relationship["trust"] = -99
    event["subjects"].append("mutated")  # type: ignore[union-attr]

    assert perception == StoryPerception(
        version=1,
        tick=9,
        hero_id="hero-1",
        characters=(
            StoryCharacterView(
                "companion-1", (("stats", (("hp", 10),)), ("tags", ("mage",)))
            ),
        ),
        quests=(StoryQuestView("quest-1", (("status", "active"),)),),
        relationships=(
            StoryRelationshipView("hero-1", "companion-1", (("trust", 3),)),
        ),
        recent_events=(
            StoryRecentEventView(
                "event-1", 8, "quest_offered", (("subjects", ("quest-1",)),)
            ),
        ),
    )
