from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from aincrad.content.events import (
    LIFE_EVENT_CATALOG,
    LifeEventTemplate,
    LifeEventType,
    validate_life_event_catalog,
)
from aincrad.domain.models import (
    Adventurer,
    Location,
    LocationKind,
    PartyState,
    Stats,
    WorldState,
)
from aincrad.domain.story import (
    QuestState,
    StoryIntent,
    StoryIntentKind,
    StoryRecentEventView,
    StoryResolution,
    StoryResolutionEvent,
    StoryState,
    story_candidate_id,
)
from aincrad.simulation.story import (
    StoryResolutionError,
    build_story_perception,
    generate_story_candidates,
    resolve_story_intent,
    validate_story_intent,
)


def _adventurer(adventurer_id: str, *, alive: bool = True) -> Adventurer:
    return Adventurer(
        id=adventurer_id,
        name=adventurer_id,
        location_id="hall",
        stats=Stats(hp=10 if alive else 0, max_hp=10, mp=5, max_mp=5),
        alive=alive,
        death_tick=None if alive else 0,
    )


def _world(*, members: tuple[str, ...] = ("hero",), cap: int = 3) -> WorldState:
    return WorldState(
        tick=4,
        locations={"hall": Location("hall", "Hall", LocationKind.TOWN)},
        adventurers={
            "hero": _adventurer("hero"),
            "rhea": _adventurer("rhea"),
            "fallen": _adventurer("fallen", alive=False),
        },
        party=PartyState("hero", members, cap),
    )


def _templates() -> tuple[LifeEventTemplate, ...]:
    return validate_life_event_catalog(
        (
            LifeEventTemplate(
                "recruit-any",
                LifeEventType.COMPANION_RECRUITMENT,
                {"quest_id": "quest-a", "relationship_at_least": 60},
                "동료가 합류합니다.",
                {"companion_id": "rhea", "party_action": "add"},
            ),
            LifeEventTemplate(
                "depart-any",
                LifeEventType.COMPANION_DEPARTURE,
                {"companion_id": "rhea", "relationship_below": 20},
                "동료가 떠납니다.",
                {"companion_id": "rhea", "party_action": "remove"},
            ),
            LifeEventTemplate(
                "offer-any",
                LifeEventType.QUEST_OFFER,
                {"location_id": "hall", "quest_available": True},
                "새 의뢰가 나타납니다.",
                {"quest_id": "quest-a", "quest_state": "offered"},
            ),
            LifeEventTemplate(
                "complete-any",
                LifeEventType.QUEST_COMPLETION,
                {"quest_id": "quest-a", "objectives_complete": True},
                "의뢰를 완료합니다.",
                {"quest_id": "quest-a", "quest_state": "completed"},
            ),
        )
    )


def test_story_state_is_canonical_immutable_and_mapping_safe() -> None:
    quest_states = {"quest-b": QuestState.COMPLETED, "quest-a": QuestState.OFFERED}
    relationships = {("hero", "rhea"): 60}

    state = StoryState(quest_states=quest_states, relationship_scores=relationships)
    quest_states["quest-a"] = QuestState.COMPLETED
    relationships[("hero", "rhea")] = 0

    assert state.quest_states == (
        ("quest-a", QuestState.OFFERED),
        ("quest-b", QuestState.COMPLETED),
    )
    assert state.relationship_scores == (("hero", "rhea", 60),)
    assert state.quest_state("quest-a") is QuestState.OFFERED
    assert state.relationship_score("hero", "rhea") == 60
    assert StoryState(
        quest_states=state.quest_states,
        relationship_scores=state.relationship_scores,
    ).quest_states == state.quest_states
    with pytest.raises(FrozenInstanceError):
        state.quest_states = ()  # type: ignore[misc]


def test_build_perception_uses_only_explicit_whitelisted_story_facts() -> None:
    recent = StoryRecentEventView("action-1", 3, "action_succeeded", (("action", "wait"),))
    perception = build_story_perception(
        _world(),
        StoryState(
            quest_states={"quest-a": QuestState.OFFERED},
            relationship_scores={("hero", "rhea"): 60},
        ),
        recent_events=(recent,),
    )

    assert perception.tick == 4
    assert perception.hero_id == "hero"
    assert perception.characters[0].fields == (
        ("alive", False),
        ("in_party", False),
        ("location_id", "hall"),
    )
    assert perception.characters[-1].character_id == "rhea"
    assert perception.quests[0].fields == (("status", "offered"),)
    assert perception.relationships[0].fields == (("score", 60),)
    assert perception.recent_events == (recent,)


def test_generate_candidates_requires_explicit_facts_and_is_template_generic_and_sorted() -> None:
    world = _world()
    story = StoryState()

    without_facts = generate_story_candidates(world, story, reversed(_templates()))
    candidates = generate_story_candidates(
        world,
        story,
        reversed(_templates()),
        available_location_ids=("hall",),
        available_quest_ids=("quest-a",),
    )

    assert {candidate.kind.value for candidate in without_facts} == {"no_op"}
    assert {candidate.kind.value for candidate in candidates} == {"no_op", "offer_quest"}
    assert candidates == tuple(sorted(candidates, key=lambda candidate: candidate.candidate_id))
    offer = next(candidate for candidate in candidates if candidate.kind.value == "offer_quest")
    assert offer.quest_id == "quest-a"
    assert offer.reason_code == "template.offer-any"


def test_offer_resolution_returns_typed_event_and_records_exact_ids() -> None:
    world = _world()
    story = StoryState()
    candidates = generate_story_candidates(
        world,
        story,
        _templates(),
        available_location_ids=("hall",),
        available_quest_ids=("quest-a",),
    )
    offer = next(candidate for candidate in candidates if candidate.quest_id == "quest-a")

    result = resolve_story_intent(
        world,
        story,
        offer,
        _templates(),
        available_location_ids=("hall",),
        available_quest_ids=("quest-a",),
    )

    assert isinstance(result, StoryResolution)
    assert isinstance(result.event, StoryResolutionEvent)
    assert result.world is world
    assert result.story.quest_state("quest-a") is QuestState.OFFERED
    assert result.story.resolved_candidate_ids == (offer.candidate_id,)
    assert result.story.resolved_template_ids == ("offer-any",)
    assert result.event.template_id == "offer-any"


def test_complete_resolution_requires_offered_quest_and_explicit_objective_fact() -> None:
    world = _world()
    story = StoryState(quest_states={"quest-a": QuestState.OFFERED})
    without_evidence = generate_story_candidates(world, story, _templates())
    candidates = generate_story_candidates(
        world,
        story,
        _templates(),
        completed_objective_quest_ids=("quest-a",),
    )
    completion = next(
        candidate for candidate in candidates if candidate.kind is StoryIntentKind.COMPLETE_QUEST
    )

    result = resolve_story_intent(
        world,
        story,
        completion,
        _templates(),
        completed_objective_quest_ids=("quest-a",),
    )

    assert all(
        candidate.kind is not StoryIntentKind.COMPLETE_QUEST
        for candidate in without_evidence
    )
    assert result.story.quest_state("quest-a") is QuestState.COMPLETED
    assert result.world is world


def test_recruitment_and_departure_update_only_party_membership() -> None:
    world = _world()
    recruit_story = StoryState(
        quest_states={"quest-a": QuestState.COMPLETED},
        relationship_scores={("hero", "rhea"): 60},
    )
    recruit = next(
        candidate
        for candidate in generate_story_candidates(world, recruit_story, _templates())
        if candidate.kind is StoryIntentKind.RECRUIT_COMPANION
    )
    recruited = resolve_story_intent(world, recruit_story, recruit, _templates())

    assert recruited.world.party is not None
    assert recruited.world.party.member_ids == ("hero", "rhea")
    assert recruited.world.adventurers == world.adventurers

    depart_story = StoryState(
        quest_states={"quest-a": QuestState.COMPLETED},
        relationship_scores={("hero", "rhea"): 19},
        resolved_candidate_ids=recruited.story.resolved_candidate_ids,
        resolved_template_ids=recruited.story.resolved_template_ids,
    )
    depart = next(
        candidate
        for candidate in generate_story_candidates(recruited.world, depart_story, _templates())
        if candidate.kind is StoryIntentKind.DEPART_COMPANION
    )
    departed = resolve_story_intent(recruited.world, depart_story, depart, _templates())

    assert departed.world.party is not None
    assert departed.world.party.member_ids == ("hero",)
    assert "rhea" in departed.world.adventurers
    assert departed.world.adventurers["rhea"] is world.adventurers["rhea"]


def test_candidate_gates_enforce_cap_liveness_membership_and_relationship_thresholds() -> None:
    story = StoryState(
        quest_states={"quest-a": QuestState.COMPLETED},
        relationship_scores={("hero", "rhea"): 59},
    )
    full_world = _world(members=("hero",), cap=1)
    dead_world = replace(
        _world(),
        adventurers={
            **_world().adventurers,
            "rhea": _adventurer("rhea", alive=False),
        },
    )
    missing_world = replace(
        _world(),
        adventurers={
            "hero": _adventurer("hero"),
            "fallen": _adventurer("fallen", alive=False),
        },
    )

    assert all(
        candidate.kind is not StoryIntentKind.RECRUIT_COMPANION
        for candidate in generate_story_candidates(_world(), story, _templates())
    )
    eligible_story = StoryState(
        quest_states={"quest-a": QuestState.COMPLETED},
        relationship_scores={("hero", "rhea"): 60},
    )
    for blocked_world in (
        full_world,
        dead_world,
        missing_world,
        _world(members=("hero", "rhea")),
    ):
        assert all(
            candidate.kind is not StoryIntentKind.RECRUIT_COMPANION
            for candidate in generate_story_candidates(blocked_world, eligible_story, _templates())
        )
    absent_relationship = StoryState(quest_states={"quest-a": QuestState.COMPLETED})
    assert all(
        candidate.kind is not StoryIntentKind.DEPART_COMPANION
        for candidate in generate_story_candidates(
            _world(members=("hero", "rhea")), absent_relationship, _templates()
        )
    )


def test_permanent_death_and_boss_templates_are_never_discretionary_candidates() -> None:
    candidates = generate_story_candidates(
        _world(),
        StoryState(),
        LIFE_EVENT_CATALOG,
        available_location_ids=("emberfall-quest-hall", "vault-10"),
        available_quest_ids=("echoes-at-emberfall",),
        completed_objective_quest_ids=("echoes-at-emberfall",),
    )

    assert all(
        candidate.kind
        in {
            StoryIntentKind.NO_OP,
            StoryIntentKind.OFFER_QUEST,
            StoryIntentKind.COMPLETE_QUEST,
            StoryIntentKind.RECRUIT_COMPANION,
            StoryIntentKind.DEPART_COMPANION,
        }
        for candidate in candidates
    )
    assert all("boss" not in candidate.reason_code for candidate in candidates)
    assert all("death" not in candidate.reason_code for candidate in candidates)


def test_invalid_exact_membership_proposal_fails_without_mutation() -> None:
    world = _world()
    story = StoryState()
    candidate_id = story_candidate_id(
        kind=StoryIntentKind.NO_OP,
        tick=world.tick,
        hero_id="hero",
        reason_code="story.unlisted",
    )
    unlisted = StoryIntent(
        version=1,
        candidate_id=candidate_id,
        kind=StoryIntentKind.NO_OP,
        tick=world.tick,
        hero_id="hero",
        reason_code="story.unlisted",
    )

    with pytest.raises(StoryResolutionError, match="exact legal candidate"):
        resolve_story_intent(world, story, unlisted, _templates())

    assert world.party is not None
    assert world.party.member_ids == ("hero",)
    assert story == StoryState()


def test_validate_story_intent_returns_only_the_exact_supplied_member() -> None:
    candidates = generate_story_candidates(_world(), StoryState(), _templates())
    selected = candidates[0]

    assert validate_story_intent(selected, candidates) is selected

    different_id = story_candidate_id(
        kind=selected.kind,
        tick=selected.tick,
        hero_id=selected.hero_id,
        reason_code="story.changed",
    )
    different = StoryIntent(
        version=1,
        candidate_id=different_id,
        kind=selected.kind,
        tick=selected.tick,
        hero_id=selected.hero_id,
        reason_code="story.changed",
    )
    with pytest.raises(StoryResolutionError, match="exact legal candidate"):
        validate_story_intent(different, candidates)


def test_no_op_resolves_without_template_or_world_mutation() -> None:
    world = _world()
    story = StoryState()
    no_op = next(
        candidate
        for candidate in generate_story_candidates(world, story, _templates())
        if candidate.kind is StoryIntentKind.NO_OP
    )

    result = resolve_story_intent(world, story, no_op, _templates())

    assert result.world is world
    assert result.event.template_id is None
    assert result.story.resolved_candidate_ids == (no_op.candidate_id,)
    assert result.story.resolved_template_ids == ()
