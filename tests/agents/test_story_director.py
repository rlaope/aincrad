from __future__ import annotations

from itertools import permutations

import pytest

from aincrad.agents import BaselineStoryDirector as ExportedBaselineStoryDirector
from aincrad.agents.story import BaselineStoryDirector, NoAllowedStoryIntent, StoryDirector
from aincrad.domain.models import WorldState
from aincrad.domain.story import (
    StoryIntent,
    StoryIntentKind,
    StoryPerception,
    story_candidate_id,
)


def _candidate(
    kind: StoryIntentKind,
    *,
    tick: int = 4,
    hero_id: str = "hero-1",
    reason_code: str | None = None,
    quest_id: str | None = None,
    companion_id: str | None = None,
) -> StoryIntent:
    reason = reason_code or f"candidate.{kind.value}"
    candidate_id = story_candidate_id(
        kind=kind,
        tick=tick,
        hero_id=hero_id,
        reason_code=reason,
        quest_id=quest_id,
        companion_id=companion_id,
    )
    return StoryIntent(
        version=1,
        candidate_id=candidate_id,
        kind=kind,
        tick=tick,
        hero_id=hero_id,
        reason_code=reason,
        quest_id=quest_id,
        companion_id=companion_id,
    )


def _all_candidates() -> tuple[StoryIntent, ...]:
    return (
        _candidate(StoryIntentKind.NO_OP),
        _candidate(StoryIntentKind.OFFER_QUEST, quest_id="quest-1"),
        _candidate(StoryIntentKind.RECRUIT_COMPANION, companion_id="companion-1"),
        _candidate(StoryIntentKind.DEPART_COMPANION, companion_id="companion-2"),
        _candidate(StoryIntentKind.COMPLETE_QUEST, quest_id="quest-2"),
    )


def test_baseline_story_director_is_a_story_director_and_returns_exact_candidate() -> None:
    with pytest.raises(TypeError):
        BaselineStoryDirector(kind_priority=())  # type: ignore[call-arg]

    director = BaselineStoryDirector()
    perception = StoryPerception(version=1, tick=4, hero_id="hero-1")
    candidates = _all_candidates()

    selected = director.choose(perception, candidates)

    assert ExportedBaselineStoryDirector is BaselineStoryDirector
    assert isinstance(director, StoryDirector)
    assert selected is candidates[-1]


def test_baseline_story_director_priority_is_order_independent_for_every_permutation() -> None:
    director = BaselineStoryDirector()
    perception = StoryPerception(version=1, tick=4, hero_id="hero-1")
    candidates = _all_candidates()
    expected = candidates[-1]

    for ordering in permutations(candidates):
        assert director.choose(perception, ordering) is expected


def test_baseline_story_director_uses_candidate_id_as_deterministic_same_kind_tiebreak() -> None:
    director = BaselineStoryDirector()
    perception = StoryPerception(version=1, tick=4, hero_id="hero-1")
    first = _candidate(StoryIntentKind.COMPLETE_QUEST, quest_id="quest-1")
    second = _candidate(StoryIntentKind.COMPLETE_QUEST, quest_id="quest-2")
    expected = min((first, second), key=lambda intent: intent.candidate_id)

    assert director.choose(perception, (first, second)) is expected
    assert director.choose(perception, (second, first)) is expected


def test_baseline_story_director_rejects_empty_candidates() -> None:
    with pytest.raises(NoAllowedStoryIntent):
        BaselineStoryDirector().choose(
            StoryPerception(version=1, tick=4, hero_id="hero-1"), ()
        )


@pytest.mark.parametrize(
    "candidate",
    [
        _candidate(StoryIntentKind.NO_OP, tick=5),
        _candidate(StoryIntentKind.NO_OP, hero_id="hero-2"),
    ],
)
def test_baseline_story_director_rejects_candidate_mismatched_to_perception(
    candidate: StoryIntent,
) -> None:
    with pytest.raises(ValueError):
        BaselineStoryDirector().choose(
            StoryPerception(version=1, tick=4, hero_id="hero-1"), (candidate,)
        )


def test_baseline_story_director_rejects_world_state_and_does_not_mutate_inputs() -> None:
    director = BaselineStoryDirector()
    perception = StoryPerception(version=1, tick=4, hero_id="hero-1")
    candidates = list(_all_candidates())
    before = list(candidates)

    director.choose(perception, candidates)

    assert candidates == before
    with pytest.raises(TypeError):
        director.choose(WorldState, candidates)  # type: ignore[arg-type]
