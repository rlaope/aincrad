from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace

from aincrad.content.events import LifeEventTemplate, LifeEventType, validate_life_event_catalog
from aincrad.domain.models import WorldState
from aincrad.domain.story import (
    STORY_INTENT_VERSION,
    QuestState,
    StoryCharacterView,
    StoryIntent,
    StoryIntentKind,
    StoryPerception,
    StoryQuestView,
    StoryRecentEventView,
    StoryRelationshipView,
    StoryResolution,
    StoryResolutionEvent,
    StoryState,
    story_candidate_id,
)


class StoryResolutionError(ValueError):
    """Raised when a proposal is not an exact currently legal candidate."""


def build_story_perception(
    world: WorldState,
    story: StoryState,
    *,
    recent_events: Iterable[StoryRecentEventView] = (),
) -> StoryPerception:
    """Project only explicit, story-safe facts from immutable runtime state."""

    party = world.party
    if party is None:  # WorldState normalizes this, but keep the boundary fail-closed.
        raise ValueError("story perception requires a party")
    members = frozenset(party.member_ids)
    return StoryPerception(
        version=STORY_INTENT_VERSION,
        tick=world.tick,
        hero_id=party.selected_hero_id,
        characters=tuple(
            StoryCharacterView(
                adventurer_id,
                (
                    ("alive", adventurer.alive),
                    ("in_party", adventurer_id in members),
                    ("location_id", adventurer.location_id),
                ),
            )
            for adventurer_id, adventurer in sorted(world.adventurers.items())
        ),
        quests=tuple(
            StoryQuestView(quest_id, (("status", quest_state.value),))
            for quest_id, quest_state in story.quest_states
        ),
        relationships=tuple(
            StoryRelationshipView(source_id, target_id, (("score", score),))
            for source_id, target_id, score in story.relationship_scores
        ),
        recent_events=tuple(recent_events),
    )


def generate_story_candidates(
    world: WorldState,
    story: StoryState,
    templates: Iterable[LifeEventTemplate],
    *,
    available_location_ids: Iterable[str] = (),
    available_quest_ids: Iterable[str] = (),
    completed_objective_quest_ids: Iterable[str] = (),
) -> tuple[StoryIntent, ...]:
    """Generate only legal discretionary intents from validated generic templates."""

    party = world.party
    if party is None:
        raise ValueError("story candidates require a party")
    validated = validate_life_event_catalog(tuple(templates))
    locations = frozenset(available_location_ids)
    available_quests = frozenset(available_quest_ids)
    completed_objectives = frozenset(completed_objective_quest_ids)
    candidates = [_make_intent(world.tick, party.selected_hero_id, StoryIntentKind.NO_OP)]
    for template in validated:
        candidate = _candidate_for_template(
            world,
            story,
            template,
            locations=locations,
            available_quests=available_quests,
            completed_objectives=completed_objectives,
        )
        if candidate is not None:
            candidates.append(candidate)
    unresolved = (
        candidate
        for candidate in candidates
        if candidate.candidate_id not in story.resolved_candidate_ids
    )
    return tuple(sorted(unresolved, key=lambda candidate: candidate.candidate_id))


def validate_story_intent(
    selected: StoryIntent, candidates: Iterable[StoryIntent]
) -> StoryIntent:
    """Return the canonical exact member or reject an unlisted proposal."""

    for candidate in candidates:
        if candidate == selected:
            return candidate
    raise StoryResolutionError("selected story intent is not an exact legal candidate")


def resolve_story_intent(
    world: WorldState,
    story: StoryState,
    selected: StoryIntent,
    templates: Iterable[LifeEventTemplate],
    *,
    available_location_ids: Iterable[str] = (),
    available_quest_ids: Iterable[str] = (),
    completed_objective_quest_ids: Iterable[str] = (),
) -> StoryResolution:
    """Validate exact membership, then atomically resolve one story intent."""

    template_tuple = tuple(templates)
    candidates = generate_story_candidates(
        world,
        story,
        template_tuple,
        available_location_ids=available_location_ids,
        available_quest_ids=available_quest_ids,
        completed_objective_quest_ids=completed_objective_quest_ids,
    )
    selected = validate_story_intent(selected, candidates)

    party = world.party
    if party is None:
        raise StoryResolutionError("story resolution requires a party")
    next_world = world
    quest_states = dict(story.quest_states)
    template_id: str | None = None
    if selected.kind is not StoryIntentKind.NO_OP:
        template = next(
            (
                item
                for item in template_tuple
                if selected.reason_code == f"template.{item.id}"
            ),
            None,
        )
        if template is None:
            raise StoryResolutionError("candidate does not identify a supplied template")
        template_id = template.id

    if selected.kind is StoryIntentKind.OFFER_QUEST:
        if selected.quest_id is None:
            raise StoryResolutionError("quest offer requires a quest id")
        quest_states[selected.quest_id] = QuestState.OFFERED
    elif selected.kind is StoryIntentKind.COMPLETE_QUEST:
        if selected.quest_id is None:
            raise StoryResolutionError("quest completion requires a quest id")
        quest_states[selected.quest_id] = QuestState.COMPLETED
    elif selected.kind is StoryIntentKind.RECRUIT_COMPANION:
        companion_id = selected.companion_id
        if companion_id is None:
            raise StoryResolutionError("recruitment requires a companion id")
        next_party = replace(party, member_ids=(*party.member_ids, companion_id))
        next_world = replace(world, party=next_party)
    elif selected.kind is StoryIntentKind.DEPART_COMPANION:
        companion_id = selected.companion_id
        if companion_id is None or companion_id == party.selected_hero_id:
            raise StoryResolutionError("selected hero cannot depart")
        next_party = replace(
            party,
            member_ids=tuple(
                member_id for member_id in party.member_ids if member_id != companion_id
            ),
        )
        next_world = replace(world, party=next_party)

    template_ids = story.resolved_template_ids
    if template_id is not None:
        template_ids = (*template_ids, template_id)
    next_story = StoryState(
        quest_states=quest_states,
        relationship_scores={
            (source_id, target_id): score
            for source_id, target_id, score in story.relationship_scores
        },
        resolved_candidate_ids=(*story.resolved_candidate_ids, selected.candidate_id),
        resolved_template_ids=template_ids,
    )
    event = StoryResolutionEvent(
        tick=world.tick,
        candidate_id=selected.candidate_id,
        template_id=template_id,
        kind=selected.kind,
        hero_id=selected.hero_id,
        reason_code=selected.reason_code,
        quest_id=selected.quest_id,
        companion_id=selected.companion_id,
    )
    return StoryResolution(next_world, next_story, event)


def _candidate_for_template(
    world: WorldState,
    story: StoryState,
    template: LifeEventTemplate,
    *,
    locations: frozenset[str],
    available_quests: frozenset[str],
    completed_objectives: frozenset[str],
) -> StoryIntent | None:
    party = world.party
    if party is None or template.id in story.resolved_template_ids:
        return None
    reason = f"template.{template.id}"
    if template.event_type is LifeEventType.QUEST_OFFER:
        quest_id = _string_field(template.effects, "quest_id")
        location_id = _string_field(template.triggers, "location_id")
        if (
            quest_id in available_quests
            and location_id in locations
            and story.quest_state(quest_id) is None
        ):
            return _make_intent(
                world.tick,
                party.selected_hero_id,
                StoryIntentKind.OFFER_QUEST,
                reason,
                quest_id=quest_id,
            )
    elif template.event_type is LifeEventType.QUEST_COMPLETION:
        quest_id = _string_field(template.effects, "quest_id")
        if (
            quest_id in completed_objectives
            and story.quest_state(quest_id) is QuestState.OFFERED
        ):
            return _make_intent(
                world.tick,
                party.selected_hero_id,
                StoryIntentKind.COMPLETE_QUEST,
                reason,
                quest_id=quest_id,
            )
    elif template.event_type is LifeEventType.COMPANION_RECRUITMENT:
        companion_id = _string_field(template.effects, "companion_id")
        quest_id = _string_field(template.triggers, "quest_id")
        relationship = _integer_field(template.triggers, "relationship_at_least")
        companion = world.adventurers.get(companion_id)
        score = story.relationship_score(party.selected_hero_id, companion_id)
        if (
            story.quest_state(quest_id) is QuestState.COMPLETED
            and score is not None
            and score >= relationship
            and companion is not None
            and companion.alive
            and companion_id not in party.member_ids
            and len(party.member_ids) < party.cap
        ):
            return _make_intent(
                world.tick,
                party.selected_hero_id,
                StoryIntentKind.RECRUIT_COMPANION,
                reason,
                companion_id=companion_id,
            )
    elif template.event_type is LifeEventType.COMPANION_DEPARTURE:
        companion_id = _string_field(template.effects, "companion_id")
        relationship = _integer_field(template.triggers, "relationship_below")
        companion = world.adventurers.get(companion_id)
        score = story.relationship_score(party.selected_hero_id, companion_id)
        if (
            companion_id != party.selected_hero_id
            and companion_id in party.member_ids
            and companion is not None
            and companion.alive
            and score is not None
            and score < relationship
        ):
            return _make_intent(
                world.tick,
                party.selected_hero_id,
                StoryIntentKind.DEPART_COMPANION,
                reason,
                companion_id=companion_id,
            )
    return None


def _make_intent(
    tick: int,
    hero_id: str,
    kind: StoryIntentKind,
    reason_code: str = "story.no-op",
    *,
    quest_id: str | None = None,
    companion_id: str | None = None,
) -> StoryIntent:
    candidate_id = story_candidate_id(
        kind=kind,
        tick=tick,
        hero_id=hero_id,
        reason_code=reason_code,
        quest_id=quest_id,
        companion_id=companion_id,
    )
    return StoryIntent(
        version=STORY_INTENT_VERSION,
        candidate_id=candidate_id,
        kind=kind,
        tick=tick,
        hero_id=hero_id,
        reason_code=reason_code,
        quest_id=quest_id,
        companion_id=companion_id,
    )


def _string_field(values: Mapping[str, object], key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str):
        raise TypeError(f"template {key} must be a string")
    return value


def _integer_field(values: Mapping[str, object], key: str) -> int:
    value = values.get(key)
    if type(value) is not int:
        raise TypeError(f"template {key} must be an integer")
    return value
